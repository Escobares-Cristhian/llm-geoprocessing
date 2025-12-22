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


def is_postgis_enabled() -> bool:
    """
    Small feature flag so PostGIS is opt-in via env.

    POSTGIS_ENABLED=true|1|yes|on -> enabled
    Anything else                  -> disabled.
    """
    return os.getenv("POSTGIS_ENABLED", "false").lower() in {"1", "true", "yes", "on"}


def _pg_env_from_settings() -> dict:
    """
    Build a PG* env mapping from env vars so we can reuse the same
    configuration from both Python and CLI tools (psql / raster2pgsql).
    """
    return {
        "PGHOST": os.getenv("POSTGIS_HOST", "localhost"),
        "PGPORT": os.getenv("POSTGIS_PORT", "5432"),
        "PGDATABASE": os.getenv("POSTGIS_DB", "geollm"),
        "PGUSER": os.getenv("POSTGIS_USER", "geollm"),
        "PGPASSWORD": os.getenv("POSTGIS_PASSWORD", "geollm"),
    }


def _safe_table_name(base: str) -> str:
    # Convert accents (e.g., "iberá" -> "ibera") and drop any remaining non-ascii
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    base = base.lower()
    base = re.sub(r"[^a-z0-9_]+", "_", base)
    base = re.sub(r"_+", "_", base).strip("_")
    if not base:
        return "t"
    if not base[0].isalpha():
        return f"t_{base}"
    return base


def upload_raster_to_postgis(
    raster_path: Path | str,
    output_id: Optional[str] = None,
) -> Optional[str]:
    """
    Upload a GeoTIFF result into a PostGIS raster table using raster2pgsql + psql.

    Returns the fully qualified table name (schema.table) on success,
    or None if upload was skipped / failed.
    """
    if not is_postgis_enabled():
        # Feature disabled; keep existing behaviour.
        logger.debug("PostGIS upload disabled (POSTGIS_ENABLED is not true).")
        return None

    raster_path = Path(raster_path)

    if not raster_path.exists():
        logger.warning("PostGIS upload skipped: file does not exist: %s", raster_path)
        return None

    if shutil.which("raster2pgsql") is None or shutil.which("psql") is None:
        logger.error("PostGIS upload skipped: raster2pgsql or psql not found in PATH.")
        return None

    schema = os.getenv("POSTGIS_SCHEMA", "public")
    prefix = os.getenv("POSTGIS_TABLE_PREFIX", "gee_output_")
    srid_env = os.getenv("POSTGIS_SRID")
    srid: Optional[int] = None
    if srid_env:
        try:
            srid = int(srid_env)
        except ValueError:
            logger.warning("Invalid POSTGIS_SRID=%s, ignoring.", srid_env)

    # Table name: prefix + safe(output_id or file stem) + short timestamp
    base_name = output_id or raster_path.stem
    safe_base = _safe_table_name(base_name)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    table_name = f"{prefix}{safe_base}_{ts}"

    full_table = f"{schema}.{table_name}" if schema else table_name

    # Prepare environment
    env = os.environ.copy()
    env.update(_pg_env_from_settings())
    
    # --- Ensure extensions exist before attempting upload ---
    logger.info("Ensuring PostGIS extensions are enabled...")
    subprocess.run(
        ["psql", "-c", "CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS postgis_raster;"],
        env=env,
        check=False  # Don't crash if user lacks permissions, just try
    )
    # -------------------------------------------------------

    # Build raster2pgsql command
    cmd = ["raster2pgsql", "-I", "-C", "-M"]
    if srid is not None:
        cmd.extend(["-s", str(srid)])
    cmd.extend([str(raster_path), full_table])

    logger.info("Uploading raster %s to PostGIS table %s", raster_path, full_table)
    logger.debug("Running command: %s", " ".join(cmd))

    # Pipe raster2pgsql -> psql
    p1 = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
    )
    assert p1.stdout is not None
    p2 = subprocess.Popen(
        ["psql", "-v", "ON_ERROR_STOP=1", "-X"],
        stdin=p1.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
    )
    p1.stdout.close()  # allow p1 to receive a SIGPIPE if p2 exits

    out, err = p2.communicate()

    if p2.returncode != 0:
        logger.error("PostGIS upload failed (exit code %s): %s", p2.returncode, err)
        return None

    logger.debug("PostGIS upload output: %s", out)
    logger.info("PostGIS upload completed: %s", full_table)
    return full_table

