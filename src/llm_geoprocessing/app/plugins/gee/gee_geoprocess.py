from fastapi import FastAPI, HTTPException, Query
import os, ee
import json

app = FastAPI(title="GEE Plugin")

def _init_ee() -> None:
    key_path = os.environ.get("EE_PRIVATE_KEY_PATH", "/keys/gee-sa.json")
    if os.path.exists(key_path):
        with open(key_path, "r") as f:
            key = json.load(f)
        sa_email  = key.get("client_email")
        project   = os.environ.get("EE_PROJECT") or key.get("project_id")
        creds = ee.ServiceAccountCredentials(sa_email, key_path)
        ee.Initialize(creds, project=project)
    else:
        # fallback to user OAuth in container, if mounted
        project = os.environ.get("EE_PROJECT")
        ee.Initialize(project=project)

@app.on_event("startup")
def startup():
    _init_ee()

def _mask_s2_sr(image: ee.Image) -> ee.Image:
    # Use SCL (scene classification) for SR: keep vegetation(4), bare soil(5), water(6), snow/ice(11); mask clouds/shadows/etc.
    scl = image.select("SCL")
    clear = (
        scl.eq(4)   # Vegetation
        .Or(scl.eq(5))  # Bare soils
        .Or(scl.eq(6))  # Water
        .Or(scl.eq(11)) # Snow/ice (optional; remove if you don't want snow)
    )
    return image.updateMask(clear).divide(10000)

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/thumb/s2/rgb")
def s2_rgb_thumb(
    bbox: str = Query(..., description="xmin,ymin,xmax,ymax (lon/lat)"),
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    mask: bool = Query(True),
    width: int = Query(1280)
):
    try:
        xmin, ymin, xmax, ymax = [float(x) for x in bbox.split(",")]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid bbox")

    region = ee.Geometry.Rectangle([xmin, ymin, xmax, ymax])
    col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
           .filterBounds(region)
           .filterDate(start, end))
    if mask:
        col = col.map(_mask_s2_sr)
    img = col.median().clip(region)
    vis = {"bands": ["B4","B3","B2"], "min": 0, "max": 0.3}
    url = img.getThumbURL({**vis, "region": region, "dimensions": width, "format": "png"})
    return {"png_url": url}

