from __future__ import annotations

import os
import re
import shutil
import subprocess
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from llm_geoprocessing.app.logging_config import get_logger

logger = get_logger("geollm")


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

    # Ensure extensions exist
    subprocess.run(
        ["psql", "-c", "CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS postgis_raster;"],
        env=env,
        check=False,
    )

    schema = os.getenv("POSTGIS_SCHEMA", "public")
    prefix = os.getenv("POSTGIS_TABLE_PREFIX", "gee_output_")

    # Table name
    base_name = output_id or raster_path.stem
    safe_base = _safe_table_name(base_name)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    table_name = f"{prefix}{safe_base}_{ts}"
    full_table = f"{schema}.{table_name}" if schema else table_name

    # Build raster2pgsql command (no SRID override)
    cmd = ["raster2pgsql", "-I", "-C", "-M", str(raster_path), full_table]

    logger.info("Uploading %s -> %s", raster_path.name, full_table)

    # Execute: raster2pgsql | psql
    p1 = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True)
    p2 = subprocess.Popen(
        ["psql", "-v", "ON_ERROR_STOP=1", "-X"],
        stdin=p1.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
    )
    p1.stdout.close()
    _, err = p2.communicate()

    if p2.returncode != 0:
        logger.error("PostGIS upload failed: %s", err)
        return None

    return full_table