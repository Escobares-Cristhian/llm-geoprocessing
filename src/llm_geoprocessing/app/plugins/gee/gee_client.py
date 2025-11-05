import os, requests, webbrowser, tempfile, pathlib

BASE = os.getenv("GEE_PLUGIN_URL", "http://gee:8000")

def get_s2_rgb_thumb(bbox: tuple[float,float,float,float],
                     start: str, end: str,
                     mask: bool = True, width: int = 1280) -> str:
    params = {
        "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
        "start": start, "end": end,
        "mask": str(mask).lower(),
        "width": width
    }
    r = requests.get(f"{BASE}/thumb/s2/rgb", params=params, timeout=60)
    r.raise_for_status()
    return r.json()["png_url"]

def open_s2_rgb_thumb(bbox: tuple[float,float,float,float],
                      start: str, end: str,
                      mask: bool = True, width: int = 1280) -> None:
    url = get_s2_rgb_thumb(bbox, start, end, mask, width)
    if not webbrowser.open(url):
        p = pathlib.Path(tempfile.gettempdir()) / "s2_rgb_preview.png"
        with open(p, "wb") as f:
            f.write(requests.get(url, timeout=60).content)
        print(f"[GEE] Saved preview to {p}")

