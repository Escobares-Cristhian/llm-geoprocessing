"""
Runtime executor for geoprocess actions.

Goal:
- Keep geoprocess_agent.py stable while allowing different plugins.
- Dispatch by environment or by conventions.
- Default adaptor supports the GEE HTTP microservice presented in plugins/gee.

Conventions:
- Each action: {"geoprocess_name": str, "input_json": dict, "output_id": str}
- Returns a dict with "output_url" (minimal contract).
"""

from __future__ import annotations
import os, json, importlib, requests
from typing import Dict, Any

# --- Strategy 1: Explicit executor module via env var ---
# If set, import this module and call execute_geoprocess(name, params) -> dict
EXECUTOR_MODULE_ENV = "ACTIVE_PLUGIN_EXECUTOR"

def _try_module_executor(name: str, params: Dict[str, Any]) -> Dict[str, Any] | None:
    mod_path = os.getenv(EXECUTOR_MODULE_ENV)
    if not mod_path:
        # implicit runtime.py co-located at plugins/ (optional)
        mod_path = "llm_geoprocessing.app.plugins.runtime"
        try:
            importlib.import_module(mod_path)
        except Exception:
            return None
    try:
        mod = importlib.import_module(mod_path)
        if hasattr(mod, "execute_geoprocess"):
            return mod.execute_geoprocess(name, params)
    except Exception:
        # Fall through to other strategies
        return None
    return None

# --- Strategy 2: GEE HTTP microservice by naming convention ---
# Map geoprocess_name 'rgb_tif' -> GET /tif/rgb, 'index_composite_tif' -> /tif/index_composite
def _gee_endpoint_from_name(name: str) -> str | None:
    if not name.endswith("_tif"):
        return None
    base = name[:-4]  # strip '_tif'
    return f"/tif/{base}"

def _gee_http_execute(name: str, params: Dict[str, Any]) -> Dict[str, Any] | None:
    base_url = os.getenv("GEE_PLUGIN_URL", "http://gee:8000")
    path = _gee_endpoint_from_name(name)
    if not path:
        return None
    # All params passed as-is; endpoints validate.
    r = requests.get(base_url + path, params=params, timeout=180)
    r.raise_for_status()
    data = r.json()
    # Expect 'tif_url' in current GEE service
    url = data.get("tif_url") or data.get("url") or data.get("result")
    if not url:
        raise RuntimeError(f"GEE executor: unexpected response keys: {list(data.keys())}")
    return {"output_url": url}

# --- Public API ---
def execute_action(geoprocess_name: str, input_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute the given geoprocess using the best available adaptor.

    Returns a dict with at least:
        {"output_url": "<download or resource url>"}
    """
    # 1) Try explicit/implicit Python module executor
    out = _try_module_executor(geoprocess_name, input_json)
    if out:
        return out

    # 2) Try GEE HTTP adaptor
    out = _gee_http_execute(geoprocess_name, input_json)
    if out:
        return out

    # 3) Nothing matched
    raise RuntimeError(f"No executor available for geoprocess '{geoprocess_name}'. "
                       f"Set {EXECUTOR_MODULE_ENV} or provide a runtime adaptor.")
