import os, requests

BASE = os.getenv("GEE_PLUGIN_URL", "http://gee:8000")

def _get(path: str, params: dict) -> str:
    r = requests.get(f"{BASE}{path}", params=params, timeout=120)
    r.raise_for_status()
    return r.json()["tif_url"]

def rgb_single(product: str, bands: str, bbox: tuple[float,float,float,float], date: str,
            resolution: str="default", projection: str="default") -> str:
    return _get("/tif/rgb_single", {
        "product": product, "bands": bands,
        "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
        "date": date, "resolution": resolution, "projection": projection
    })

def index_tif(product: str, band1: str, band2: str, bbox: tuple[float,float,float,float], date: str,
              palette: str="", resolution: str="default", projection: str="default") -> str:
    return _get("/tif/index", {
        "product": product, "band1": band1, "band2": band2,
        "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
        "date": date, "palette": palette, "resolution": resolution, "projection": projection
    })