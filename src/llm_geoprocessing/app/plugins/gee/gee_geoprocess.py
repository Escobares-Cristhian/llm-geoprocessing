from fastapi import FastAPI, HTTPException, Query
import os, ee, json
from datetime import datetime, timedelta

app = FastAPI(title="GEE Plugin")

# --- EE bootstrap (Service Account if available; else default) ---
_INITIALIZED = False

def _init_ee() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return

    key_path = os.environ.get("EE_PRIVATE_KEY_PATH", "/keys/gee-sa.json")
    if os.path.exists(key_path):
        with open(key_path, "r") as f:
            key = json.load(f)
        sa_email = key.get("client_email")
        project  = os.environ.get("EE_PROJECT") or key.get("project_id")
        creds = ee.ServiceAccountCredentials(sa_email, key_path)
        ee.Initialize(creds, project=project)
    else:
        # Falls back to whatever auth the container has (must be pre-authorized)
        ee.Initialize()

    _INITIALIZED = True

# --- Helpers (small, focused) ---
def _parse_bbox(bbox_str: str) -> ee.Geometry:
    try:
        xmin, ymin, xmax, ymax = [float(x) for x in bbox_str.split(",")]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid bbox. Expected 'xmin,ymin,xmax,ymax'.")
    if not (xmin < xmax and ymin < ymax):
        raise HTTPException(status_code=400, detail="Invalid bbox coordinates.")
    return ee.Geometry.Rectangle([xmin, ymin, xmax, ymax], proj=None, geodesic=False)

def _date_and_next(day: str) -> tuple[str, str]:
    try:
        d = datetime.strptime(day, "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date. Use 'YYYY-MM-DD'.")
    return (d.isoformat(), (d + timedelta(days=1)).isoformat())

def _image_default_scale(img: ee.Image) -> float | None:
    # Try to infer nominal scale from the first band to honor "default" resolution.
    try:
        return float(ee.Number(img.select(0).projection().nominalScale()).getInfo())
    except Exception:
        return None

def _download_params(region: ee.Geometry, resolution: str, projection: str, default_scale: float | None = None) -> dict:
    # IMPORTANT: use 'format': 'GEO_TIFF' for getDownloadURL (not 'fileFormat').
    params: dict = {"region": region, "format": "GEO_TIFF"}
    if resolution != "default":
        try:
            params["scale"] = float(resolution)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid resolution. Use a number or 'default'.")
    elif default_scale is not None:
        params["scale"] = float(default_scale)
    if projection != "default":
        params["crs"] = projection  # e.g., "EPSG:4326"
    return params

def _resolve_reducer(name: str):
    name = (name or "mean").lower()
    if name in ("mean", "avg"):
        return "mean"
    if name in ("median",):
        return "median"
    if name in ("min", "minimum"):
        return "min"
    if name in ("max", "maximum"):
        return "max"
    if name in ("mosaic",):
        return "mosaic"
    raise HTTPException(status_code=400, detail="Invalid reducer. Use mean|min|max|median|mosaic.")

# --- Core builders ---
def _collection(product: str, region: ee.Geometry, start: str, end: str) -> ee.ImageCollection:
    col = ee.ImageCollection(product).filterBounds(region).filterDate(start, end)
    return col

def _rgb_image_single(product: str, bands_csv: str, region: ee.Geometry, date: str) -> ee.Image:
    b = [s.strip() for s in bands_csv.split(",")]
    if len(b) != 3:
        raise HTTPException(status_code=400, detail="Provide exactly 3 bands in RGB order, comma-separated.")
    start, end = _date_and_next(date)
    img = _collection(product, region, start, end).mosaic().select(b).clip(region)
    return img

def _rgb_image_composite(product: str, bands_csv: str, region: ee.Geometry, start: str, end: str, reducer: str) -> ee.Image:
    b = [s.strip() for s in bands_csv.split(",")]
    if len(b) != 3:
        raise HTTPException(status_code=400, detail="Provide exactly 3 bands in RGB order, comma-separated.")
    col = _collection(product, region, start, end).select(b)
    how = _resolve_reducer(reducer)
    if how == "mosaic":
        img = col.mosaic()
    else:
        img = getattr(col, how)()
    return img.clip(region)

def _nd_image_single(product: str, b1: str, b2: str, region: ee.Geometry, date: str) -> ee.Image:
    start, end = _date_and_next(date)
    col = _collection(product, region, start, end)
    img = col.mosaic().normalizedDifference([b1, b2]).rename("nd").clip(region)
    return img

def _nd_image_composite(product: str, b1: str, b2: str, region: ee.Geometry, start: str, end: str, reducer: str) -> ee.Image:
    col = _collection(product, region, start, end)
    col_nd = col.map(lambda im: im.normalizedDifference([b1, b2]).rename("nd"))
    how = _resolve_reducer(reducer)
    if how == "mosaic":
        img = col_nd.mosaic()
    else:
        img = getattr(col_nd, how)()
    return img.clip(region)

# --- Endpoints (return a signed URL for GeoTIFF download) ---
@app.get("/tif/rgb")
def rgb_tif(product: str = Query(..., description="GEE image or collection id"),
            bands: str   = Query(..., description="Comma-separated 3 bands in RGB order"),
            bbox: str    = Query(..., description="xmin,ymin,xmax,ymax (lon/lat)"),
            date: str    = Query(..., description="YYYY-MM-DD"),
            resolution: str = Query("default"),
            projection: str = Query("default")):
    _init_ee()
    region = _parse_bbox(bbox)
    img = _rgb_image_single(product, bands, region, date)
    default_scale = _image_default_scale(img) if resolution == "default" else None
    url = img.getDownloadURL(_download_params(region, resolution, projection, default_scale))
    return {"tif_url": url}

@app.get("/tif/index")
def index_tif(product: str = Query(..., description="GEE image or collection id"),
              band1: str   = Query(..., description="First band for ND numerator"),
              band2: str   = Query(..., description="Second band for ND denominator"),
              bbox: str    = Query(..., description="xmin,ymin,xmax,ymax (lon/lat)"),
              date: str    = Query(..., description="YYYY-MM-DD"),
              palette: str = Query("", description="Comma colors (ignored for GeoTIFF data)"),
              resolution: str = Query("default"),
              projection: str = Query("default")):
    _init_ee()
    region = _parse_bbox(bbox)
    img = _nd_image_single(product, band1, band2, region, date)
    default_scale = _image_default_scale(img) if resolution == "default" else None
    url = img.getDownloadURL(_download_params(region, resolution, projection, default_scale))
    return {"tif_url": url}

@app.get("/tif/rgb_composite")
def rgb_composite_tif(product: str = Query(..., description="GEE collection id"),
                      bands: str   = Query(..., description="Comma-separated 3 bands in RGB order"),
                      bbox: str    = Query(..., description="xmin,ymin,xmax,ymax (lon/lat)"),
                      start: str   = Query(..., description="YYYY-MM-DD inclusive"),
                      end: str     = Query(..., description="YYYY-MM-DD inclusive"),
                      reducer: str = Query("mean"),
                      resolution: str = Query("default"),
                      projection: str = Query("default")):
    _init_ee()
    region = _parse_bbox(bbox)
    # end is inclusive: EE filterDate is [start, end), so add one day
    try:
        end_iso = (datetime.strptime(end, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid end date. Use 'YYYY-MM-DD'.")
    img = _rgb_image_composite(product, bands, region, start, end_iso, reducer)
    default_scale = _image_default_scale(img) if resolution == "default" else None
    url = img.getDownloadURL(_download_params(region, resolution, projection, default_scale))
    return {"tif_url": url}

@app.get("/tif/index_composite")
def index_composite_tif(product: str = Query(..., description="GEE collection id"),
                        band1: str   = Query(..., description="First band for ND numerator"),
                        band2: str   = Query(..., description="Second band for ND denominator"),
                        bbox: str    = Query(..., description="xmin,ymin,xmax,ymax (lon/lat)"),
                        start: str   = Query(..., description="YYYY-MM-DD inclusive"),
                        end: str     = Query(..., description="YYYY-MM-DD inclusive"),
                        palette: str = Query("", description="Comma colors (ignored for GeoTIFF data)"),
                        reducer: str = Query("mean"),
                        resolution: str = Query("default"),
                        projection: str = Query("default")):
    _init_ee()
    region = _parse_bbox(bbox)
    try:
        end_iso = (datetime.strptime(end, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid end date. Use 'YYYY-MM-DD'.")
    img = _nd_image_composite(product, band1, band2, region, start, end_iso, reducer)
    default_scale = _image_default_scale(img) if resolution == "default" else None
    url = img.getDownloadURL(_download_params(region, resolution, projection, default_scale))
    return {"tif_url": url}
