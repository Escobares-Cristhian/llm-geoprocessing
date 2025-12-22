from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import re
import unicodedata

from llm_geoprocessing.app.logging_config import get_logger

logger = get_logger("geollm")

# --- CONFIGURATION ---
# New SRID to avoid cache
MODIS_SRID = 96977

# STRICT WKT2_2019 DEFINITION for MODIS Sinusoidal
# This tells QGIS 3.40 exactly how to handle the Sinusoidal math.
MODIS_WKT2 = (
    'PROJCRS["MODIS_Sinusoidal",'
    'BASEGEOGCRS["Modis_Sphere",'
    'DATUM["Modis_Sphere",ELLIPSOID["Modis_Sphere",6371007.181,0,LENGTHUNIT["metre",1]]],'
    'PRIMEM["Greenwich",0,ANGLEUNIT["degree",0.0174532925199433]]],'
    'CONVERSION["Sinusoidal",'
    'METHOD["Sinusoidal"],'
    'PARAMETER["Longitude of natural origin",0,ANGLEUNIT["degree",0.0174532925199433],ID["EPSG",8802]],'
    'PARAMETER["False easting",0,LENGTHUNIT["metre",1],ID["EPSG",8806]],'
    'PARAMETER["False northing",0,LENGTHUNIT["metre",1],ID["EPSG",8807]]],'
    'CS[Cartesian,2],'
    'AXIS["easting (X)",east,ORDER[1],LENGTHUNIT["metre",1]],'
    'AXIS["northing (Y)",north,ORDER[2],LENGTHUNIT["metre",1]]]'
)

MODIS_PROJ4 = "+proj=sinu +R=6371007.181 +nadgrids=@null +wktext +no_defs"

def is_postgis_enabled() -> bool:
    return os.getenv("POSTGIS_ENABLED", "false").lower() in {"1", "true", "yes", "on"}

def _pg_env_from_settings() -> dict:
    return {
        "PGHOST": os.getenv("POSTGIS_HOST", "localhost"),
        "PGPORT": os.getenv("POSTGIS_PORT", "5432"),
        "PGDATABASE": os.getenv("POSTGIS_DB", "geollm"),
        "PGUSER": os.getenv("POSTGIS_USER", "geollm"),
        "PGPASSWORD": os.getenv("POSTGIS_PASSWORD", "geollm"),
    }

def _safe_table_name(base: str) -> str:
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    base = base.lower()
    base = re.sub(r"[^a-z0-9_]+", "_", base)
    base = re.sub(r"_+", "_", base).strip("_")
    if not base:
        return "t"
    if not base[0].isalpha():
        return f"t_{base}"
    return base

def _detect_modis_sinusoidal(tif: Path) -> bool:
    """
    Checks if the raster uses any Sinusoidal projection.
    """
    try:
        gdalinfo = shutil.which("gdalinfo")
        if not gdalinfo:
            return False

        proc = subprocess.run(
            [gdalinfo, "-json", str(tif)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            timeout=30,
        )
        info = proc.stdout or ""
        return "Sinusoidal" in info
    except Exception as e:
        logger.warning(f"SRS detection failed for {tif}: {e}")
        return False

def _upsert_modis_srid(env: dict) -> None:
    """
    Force-registers the clean WKT2 definition.
    """
    delete_sql = f"DELETE FROM spatial_ref_sys WHERE srid = {MODIS_SRID};"
    
    # We insert our correct WKT2 string.
    insert_sql = (
        "INSERT INTO spatial_ref_sys (srid, auth_name, auth_srid, srtext, proj4text) "
        f"VALUES ({MODIS_SRID}, 'SR-ORG', 6974, '{MODIS_WKT2}', '{MODIS_PROJ4}');"
    )
    
    try:
        # Delete old
        subprocess.run(
            ["psql", "-c", delete_sql],
            env=env, text=True, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        
        logger.info(f"Registering WKT2 Sinusoidal as SRID {MODIS_SRID}...")
        subprocess.run(
            ["psql", "-c", insert_sql],
            env=env, text=True, check=True
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to register MODIS SRID: {e.stderr}")

def upload_raster_to_postgis(
    raster_path: Path | str,
    output_id: Optional[str] = None,
) -> Optional[str]:
    
    if not is_postgis_enabled():
        return None

    raster_path = Path(raster_path)
    if not raster_path.exists():
        logger.warning("File not found: %s", raster_path)
        return None

    if shutil.which("raster2pgsql") is None or shutil.which("psql") is None:
        logger.error("raster2pgsql or psql not found.")
        return None

    env = os.environ.copy()
    env.update(_pg_env_from_settings())

    # Ensure Extensions
    subprocess.run(
        ["psql", "-c", "CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS postgis_raster;"],
        env=env, check=False 
    )

    # --- Configuration ---
    schema = os.getenv("POSTGIS_SCHEMA", "public")
    prefix = os.getenv("POSTGIS_TABLE_PREFIX", "gee_output_")
    srid = None
    
    # --- SMART DETECTION ---
    if _detect_modis_sinusoidal(raster_path):
        # 1. Register the clean WKT2 definition
        _upsert_modis_srid(env)
        # 2. Force the upload to use the NEW SRID 96977
        logger.info(f"Detected Sinusoidal: forcing WKT2 (SRID {MODIS_SRID})")
        srid = MODIS_SRID
    elif os.getenv("POSTGIS_SRID"):
        try:
            srid = int(os.getenv("POSTGIS_SRID"))
        except ValueError:
            pass

    # --- Table Name ---
    base_name = output_id or raster_path.stem
    safe_base = _safe_table_name(base_name)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    table_name = f"{prefix}{safe_base}_{ts}"
    full_table = f"{schema}.{table_name}" if schema else table_name

    # --- Build Command ---
    cmd = ["raster2pgsql", "-I", "-C", "-M"]
    if srid is not None:
        cmd.extend(["-s", str(srid)])
    
    cmd.extend([str(raster_path), full_table])

    logger.info("Uploading %s -> %s", raster_path.name, full_table)
    
    # --- Execute ---
    p1 = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True)
    p2 = subprocess.Popen(["psql", "-v", "ON_ERROR_STOP=1", "-X"], stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True)
    p1.stdout.close()
    out, err = p2.communicate()

    if p2.returncode != 0:
        logger.error("PostGIS upload failed: %s", err)
        return None

    return full_table