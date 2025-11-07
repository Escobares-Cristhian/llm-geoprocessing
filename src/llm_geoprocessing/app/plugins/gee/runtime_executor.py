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
# Map geoprocess_name 'rgb_single' -> GET /tif/rgb_single, 'index_composite_tif' -> /tif/index_composite
def _gee_endpoint_from_name(name: str) -> str | None:
    if name.endswith("_tif"):
        base = name[:-4]
        return f"/tif/{base}"
    if name.endswith("_tif_tiled"):
        base = name[:-10]
        return f"/tif/{base}_tiled"
    return None


def _normalize_params_for_gee(params: Dict[str, Any]) -> Dict[str, Any]:
    """Make query params robust:
    - bbox: list/tuple -> "xmin,ymin,xmax,ymax"
    - bands: list/tuple -> comma-separated
    - palette: list/tuple -> comma-separated
    Leave others as-is.
    """
    out = dict(params or {})
    def _csv(v):
        return ",".join(str(x) for x in v)
    if "bbox" in out and isinstance(out["bbox"], (list, tuple)):
        if len(out["bbox"]) != 4:
            raise ValueError("bbox must have 4 numbers [xmin,ymin,xmax,ymax].")
        out["bbox"] = _csv(out["bbox"])
    for k in ("bands", "palette"):
        if k in out and isinstance(out[k], (list, tuple)):
            out[k] = _csv(out[k])
    return out

def _gee_http_execute(name: str, params: Dict[str, Any]) -> Dict[str, Any] | None:
    base_url = os.getenv("GEE_PLUGIN_URL", "http://gee:8000")
    path = _gee_endpoint_from_name(name)
    if not path:
        return None
    # Normalize certain params for robust encoding
    q = _normalize_params_for_gee(params)
    r = requests.get(base_url + path, params=q, timeout=180)
    r.raise_for_status()
    data = r.json()
    # Support tiled responses
    if isinstance(data, dict) and "tiles" in data:
        urls = [t.get("url") for t in data.get("tiles", []) if t.get("url")]
        if not urls:
            raise RuntimeError("GEE executor: tiled response without urls")
        return {"output_urls": urls, "tiling": data.get("tiling")}

    # Single url
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