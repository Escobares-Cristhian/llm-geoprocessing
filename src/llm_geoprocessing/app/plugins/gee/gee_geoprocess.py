import math
from fastapi import FastAPI, HTTPException, Query
import os, ee, json, math
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
        ee.Initialize()  # container must be pre-authorized (gcloud/EE token)

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

def _bbox_vals(bbox_str: str) -> tuple[float,float,float,float]:
    xmin, ymin, xmax, ymax = [float(x) for x in bbox_str.split(",")]
    return xmin, ymin, xmax, ymax

def _date_and_next(day: str) -> tuple[str, str]:
    """
    Given 'YYYY-MM-DD', return (that date ISO, next date ISO).
    """
    try:
        d = datetime.strptime(day, "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date. Use 'YYYY-MM-DD'.")
    return (d.isoformat(), (d + timedelta(days=1)).isoformat())

def _guess_default_scale(product: str) -> float:
    p = (product or "").upper()
    if "S2" in p or "SENTINEL-2" in p:
        return 10.0
    if "LANDSAT" in p or "LC08" in p or "LC09" in p or "LT05" in p:
        return 30.0
    if "MODIS" in p:
        return 250.0
    return 30.0

def _approx_dims_from_bbox_and_scale(bbox_str: str, scale_m: float) -> tuple[int,int]:
    xmin, ymin, xmax, ymax = _bbox_vals(bbox_str)
    lat_mid = (ymin + ymax) / 2.0
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat_mid))
    width_m  = max((xmax - xmin) * m_per_deg_lon, 0.0)
    height_m = max((ymax - ymin) * m_per_deg_lat, 0.0)
    if scale_m <= 0:
        return 0, 0
    w_px = int(max(round(width_m  / scale_m), 1))
    h_px = int(max(round(height_m / scale_m), 1))
    return w_px, h_px

def _infer_native_proj(product: str, region: ee.Geometry, sample_band: str, start: str | None = None, end: str | None = None) -> tuple[str, float]:
    """Infer product-native CRS and nominal scale (meters) from the first image in the (filtered) collection.
       Fallbacks to heuristics if anything fails."""
    try:
        col = ee.ImageCollection(product).filterBounds(region)
        if start and end:
            col = col.filterDate(start, end)
        first = ee.Image(col.sort("system:time_start").first())
        # Ensure we select an existing band
        band_to_use = sample_band
        try:
            _ = first.select(sample_band)
        except Exception:
            band_to_use = ee.String(first.bandNames().get(0)).getInfo()
        proj = first.select(band_to_use).projection()
        crs = proj.crs().getInfo()
        scale = float(proj.nominalScale().getInfo())
        return crs, scale
    except Exception:
        # Heuristic fallback
        return "EPSG:3857", _guess_default_scale(product)

# ---------- Tiling helpers (client-side, fixed grid) ----------
def _projected_bbox(region: ee.Geometry, crs: str) -> tuple[float,float,float,float]:
    # Bounds in target CRS (server-side transform, client fetch min/max)
    bounds = ee.Geometry(region).transform(crs, 1).bounds(1, crs)
    coords = bounds.coordinates().get(0).getInfo()
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return (min(xs), min(ys), max(xs), max(ys))

def _align_to_grid(minx: float, miny: float, maxx: float, maxy: float, scale: float):
    # Stable grid origin aligned to pixel edges (north-up: negative scale on Y)
    origin_x = math.floor(minx / scale) * scale
    origin_y = math.ceil(maxy / scale) * scale
    grid_minx = origin_x
    grid_maxx = math.ceil(maxx / scale) * scale
    grid_miny = math.floor(miny / scale) * scale
    grid_maxy = origin_y
    return origin_x, origin_y, grid_minx, grid_miny, grid_maxx, grid_maxy

def _tile_rects(crs: str, region: ee.Geometry, scale: float, tile_size: int):
    """Return (tiles, meta) where tiles is a list of ee.Geometry rectangles (proj=crs)."""
    minx, miny, maxx, maxy = _projected_bbox(region, crs)
    origin_x, origin_y, gx0, gy0, gx1, gy1 = _align_to_grid(minx, miny, maxx, maxy, scale)

    tile_w = tile_size * scale
    tile_h = tile_size * scale

    cols = max(int(math.ceil((gx1 - gx0) / tile_w)), 1)
    rows = max(int(math.ceil((gy1 - gy0) / tile_h)), 1)

    tiles = []
    region_proj = region.transform(crs, 1)
    grid_meta = {
        "crs": crs,
        "crs_transform": [scale, 0, origin_x, 0, -scale, origin_y],
        "tile_size_px": tile_size,
        "rows": rows,
        "cols": cols,
        "origin_x": origin_x,
        "origin_y": origin_y,
        "tile_w_m": tile_w,
        "tile_h_m": tile_h,
    }

    for r in range(rows):
        y_top = origin_y - r * tile_h
        y_bot = y_top - tile_h
        for c in range(cols):
            x_left = origin_x + c * tile_w
            x_right = x_left + tile_w
            rect = ee.Geometry.Rectangle([x_left, y_bot, x_right, y_top], proj=crs, geodesic=False)
            # clip to the projected region to avoid overfetch
            tile_geom = rect.intersection(region_proj, 1)
            tiles.append({"r": r, "c": c, "geom": tile_geom, "bbox_crs": [x_left, y_bot, x_right, y_top]})

    return tiles, grid_meta

def _safe_download_params(
    *,
    region: ee.Geometry,
    bbox_str: str,
    resolution: str,
    projection: str,
    default_scale: float | None,
    product_hint: str,
    bands_count: int
) -> dict:
    """
    Build params for getDownloadURL while:
      - honoring 'default' resolution/projection,
      - preventing EE 'thumbnail' size limit (~48 MB).
    """
    params: dict = {"region": region, "format": "GEO_TIFF"}

    # 1) Resolve scale (meters/pixel)
    if resolution == "default":
        scale = default_scale if default_scale and default_scale > 0 else _guess_default_scale(product_hint)
    else:
        try:
            scale = float(resolution)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid resolution. Use a number or 'default'.")

    # 2) Projection (only if user requested a specific CRS)
    if projection != "default":
        params["crs"] = projection  # e.g., EPSG:4326

    # 3) Estimate size and decide between scale vs dimensions
    w_px, h_px = _approx_dims_from_bbox_and_scale(bbox_str, scale)
    if w_px == 0 or h_px == 0:
        w_px = h_px = 1

    bytes_per_sample = 4  # float32
    est_bytes = w_px * h_px * max(bands_count, 1) * bytes_per_sample
    limit_bytes = 45 * 1024 * 1024  # headroom under EE ~48MB

    if est_bytes <= limit_bytes:
        params["scale"] = float(scale)
    else:
        max_pixels = int(limit_bytes // (max(bands_count, 1) * bytes_per_sample))
        area = max(w_px * h_px, 1)
        ratio = math.sqrt(area / max_pixels)
        new_w = max(int(w_px / ratio), 1)
        new_h = max(int(h_px / ratio), 1)
        params["dimensions"] = f"{new_w}x{new_h}"

    return params

def _resolve_reducer(name: str):
    name = (name or "mean").lower()
    if name in ("mean", "avg", "promedio"):
        return "mean"
    if name in ("median", "mediana"):
        return "median"
    if name in ("min", "minimum", "mínimo", "minimo"):
        return "min"
    if name in ("max", "maximum", "máximo", "maximo"):
        return "max"
    if name in ("mosaic", "mosaico"):
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
@app.get("/tif/rgb_single")
def rgb_single(product: str = Query(..., description="GEE image or collection id"),
            bands: str   = Query(..., description="Comma-separated 3 bands in RGB order"),
            bbox: str    = Query(..., description="xmin,ymin,xmax,ymax (lon/lat)"),
            date: str    = Query(..., description="YYYY-MM-DD"),
            resolution: str = Query("default"),
            projection: str = Query("default")):
    _init_ee()
    region = _parse_bbox(bbox)
    img = _rgb_image_single(product, bands, region, date)

    # If resolution is default, reproject to product-native CRS/scale to avoid 1-pixel artifacts
    if resolution == "default":
        first_band = bands.split(",")[0].strip()
        start, end = _date_and_next(date)
        crs_nat, scale_nat = _infer_native_proj(product, region, first_band, start, end)
        print(f"[GEE][rgb_single] Using default resolution -> crs={crs_nat}, scale_m={scale_nat}")
        img = img.reproject(crs=crs_nat, scale=scale_nat)
        default_scale = scale_nat
    else:
        default_scale = None

    params = _safe_download_params(
        region=region, bbox_str=bbox, resolution=resolution, projection=projection,
        default_scale=default_scale, product_hint=product, bands_count=3
    )
    url = img.getDownloadURL(params)
    return {"tif_url": url}

@app.get("/tif/rgb_composite_tiled")
def rgb_composite_tiled(product: str = Query(..., description="GEE collection id"),
                        bands: str   = Query(..., description="Comma-separated 3 bands in RGB order"),
                        bbox: str    = Query(..., description="xmin,ymin,xmax,ymax (lon/lat)"),
                        start: str   = Query(..., description="YYYY-MM-DD inclusive"),
                        end: str     = Query(..., description="YYYY-MM-DD inclusive"),
                        reducer: str = Query("mean"),
                        resolution: str = Query("default"),
                        projection: str = Query("default"),
                        tile_size: int = Query(1365, description="tile size in pixels (edge)"),
                        max_tiles: int = Query(25, description="safety cap on total tiles")):
    _init_ee()
    region = _parse_bbox(bbox)
    # end inclusive
    try:
        end_iso = (datetime.strptime(end, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid end date. Use 'YYYY-MM-DD'.")
    img = _rgb_image_composite(product, bands, region, start, end_iso, reducer)

    # Resolve CRS & scale (keep your chosen resolution)
    if projection == "default" or resolution == "default":
        # Get default native projection/scale
        first_band = bands.split(",")[0].strip()
        crs_nat, scale_nat = _infer_native_proj(product, region, first_band, start, end_iso)
        
        print("-"*60)
        print(f"Native CRS/scale: crs={crs_nat}, scale={scale_nat}")
        # Apply user projection/resolution overrides
        if projection == "default" and resolution != "default":
            scale_nat = float(resolution)
        elif projection != "default" and resolution == "default":
            crs_nat = projection
        print(f"User overrides applied: crs={crs_nat}, scale={scale_nat}")
        print("-"*60)
    else:
        crs_nat, scale_nat = projection, float(resolution)

    print(f"[GEE][rgb_composite_tiled] grid -> crs={crs_nat}, scale={scale_nat}, tile={tile_size}px")
    img = img.reproject(crs=crs_nat, scale=scale_nat)

    tiles, meta = _tile_rects(crs_nat, region, scale_nat, tile_size)
    if len(tiles) > max_tiles:
        raise HTTPException(status_code=400, detail=f"Too many tiles: {len(tiles)} > max_tiles={max_tiles}")

    # # Common params: fixed grid via crs (dimensions per tile)
    # common = {"format": "GEO_TIFF", "crs": crs_nat}

    # out_tiles = []
    # for t in tiles:
    #     params = dict(common)
    #     # Use the exact tile rectangle so extents align with the fixed grid (avoid irregular polygon bounds).
    #     params["region"] = ee.Geometry.Rectangle(t["bbox_crs"], proj=crs_nat, geodesic=False)

    #     # Compute exact pixel dimensions for this tile at chosen scale; force a fixed pixel grid per tile.
    #     w = t['bbox_crs'][2] - t['bbox_crs'][0]
    #     h = t['bbox_crs'][3] - t['bbox_crs'][1]
    #     w_px = int(max(round(w / scale_nat), 1))
    #     h_px = int(max(round(h / scale_nat), 1))
    #     params["dimensions"] = f"{w_px}x{h_px}"

    #     print(f"Tile r={t['r']} c={t['c']} bbox_crs={t['bbox_crs']}")
    #     print(f"  -> size: {w_px}x{h_px} px at scale {scale_nat} m/px")
        
    #     url = img.getDownloadURL(params)
    #     out_tiles.append({"row": t["r"], "col": t["c"], "bbox_crs": t["bbox_crs"], "url": url})
    # print("DONE ALL TILES")

    # return {"tiling": meta, "tiles": out_tiles}


    # ----- INIT: Option 1 ----------------------------------------------------
    # Use crs + per-tile dimensions (omit crs_transform to avoid overspecification with dimensions).
    common = {"format": "GEO_TIFF", "crs": crs_nat, "crs_transform": meta["crs_transform"]}

    out_tiles = []
    for t in tiles:
        params = dict(common)

        params["region"] = t["geom"]
        url = img.getDownloadURL(params)
        out_tiles.append({"row": t["r"], "col": t["c"], "bbox_crs": t["bbox_crs"], "url": url})

    return {"tiling": meta, "tiles": out_tiles}
    # ----- END: Option 1 ----------------------------------------------------

    # # ----- INIT: Option 2 ----------------------------------------------------
    # # Use crs + per-tile dimensions (omit crs_transform to avoid overspecification with dimensions).
    # common = {"format": "GEO_TIFF", "crs": crs_nat}

    # out_tiles = []
    # for t in tiles:
    #     params = dict(common)
    #     # Use fixed tile rectangle and fixed pixel dimensions for stable requests.
    #     params["region"] = ee.Geometry.Rectangle(t["bbox_crs"], proj=crs_nat, geodesic=False)
        
    #     w = t['bbox_crs'][2] - t['bbox_crs'][0]
    #     h = t['bbox_crs'][3] - t['bbox_crs'][1]
    #     w_px = int(max(round(w / scale_nat), 1))
    #     h_px = int(max(round(h / scale_nat), 1))
    #     params["dimensions"] = f"{w_px}x{h_px}"
        
    #     url = img.getDownloadURL(params)
    #     out_tiles.append({"row": t["r"], "col": t["c"], "bbox_crs": t["bbox_crs"], "url": url})

    # return {"tiling": meta, "tiles": out_tiles}
    # # ----- END: Option 2 ----------------------------------------------------

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

    if resolution == "default":
        start, end = _date_and_next(date)
        crs_nat, scale_nat = _infer_native_proj(product, region, band1, start, end)
        print(f"[GEE][index_tif] Using default resolution -> crs={crs_nat}, scale_m={scale_nat}")
        img = img.reproject(crs=crs_nat, scale=scale_nat)
        default_scale = scale_nat
    else:
        default_scale = None

    params = _safe_download_params(
        region=region, bbox_str=bbox, resolution=resolution, projection=projection,
        default_scale=default_scale, product_hint=product, bands_count=1
    )
    url = img.getDownloadURL(params)
    return {"tif_url": url}


@app.get("/tif/index_composite_tiled")
def index_composite_tiled(product: str = Query(..., description="GEE collection id"),
                          band1: str   = Query(..., description="First band for ND numerator"),
                          band2: str   = Query(..., description="Second band for ND denominator"),
                          bbox: str    = Query(..., description="xmin,ymin,xmax,ymax (lon/lat)"),
                          start: str   = Query(..., description="YYYY-MM-DD inclusive"),
                          end: str     = Query(..., description="YYYY-MM-DD inclusive"),
                          reducer: str = Query("mean"),
                          resolution: str = Query("default"),
                          projection: str = Query("default"),
                          tile_size: int = Query(3072, description="tile size in pixels (edge)"),
                          max_tiles: int = Query(25, description="safety cap on total tiles")):
    _init_ee()
    region = _parse_bbox(bbox)
    # end inclusive
    try:
        end_iso = (datetime.strptime(end, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid end date. Use 'YYYY-MM-DD'.")
    img = _nd_image_composite(product, band1, band2, region, start, end_iso, reducer)

    if projection == "default" or resolution == "default":
        crs_nat, scale_nat = _infer_native_proj(product, region, band1, start, end_iso)
    else:
        crs_nat, scale_nat = projection, float(resolution)

    print(f"[GEE][index_composite_tiled] grid -> crs={crs_nat}, scale={scale_nat}, tile={tile_size}px")
    img = img.reproject(crs=crs_nat, scale=scale_nat)

    tiles, meta = _tile_rects(crs_nat, region, scale_nat, tile_size)
    if len(tiles) > max_tiles:
        raise HTTPException(status_code=400, detail=f"Too many tiles: {len(tiles)} > max_tiles={max_tiles}")


    # ----- INIT: Option 1 ----------------------------------------------------
    # Use crs + per-tile dimensions (omit crs_transform to avoid overspecification with dimensions).
    common = {"format": "GEO_TIFF", "crs": crs_nat, "crs_transform": meta["crs_transform"]}

    out_tiles = []
    for t in tiles:
        params = dict(common)

        params["region"] = t["geom"]
        url = img.getDownloadURL(params)
        out_tiles.append({"row": t["r"], "col": t["c"], "bbox_crs": t["bbox_crs"], "url": url})

    return {"tiling": meta, "tiles": out_tiles}
    # ----- END: Option 1 ----------------------------------------------------

    # # ----- INIT: Option 2 ----------------------------------------------------
    # # Use crs + per-tile dimensions (omit crs_transform to avoid overspecification with dimensions).
    # common = {"format": "GEO_TIFF", "crs": crs_nat}

    # out_tiles = []
    # for t in tiles:
    #     params = dict(common)
    #     # Use fixed tile rectangle and fixed pixel dimensions for stable requests.
    #     params["region"] = ee.Geometry.Rectangle(t["bbox_crs"], proj=crs_nat, geodesic=False)
        
    #     w = t['bbox_crs'][2] - t['bbox_crs'][0]
    #     h = t['bbox_crs'][3] - t['bbox_crs'][1]
    #     w_px = int(max(round(w / scale_nat), 1))
    #     h_px = int(max(round(h / scale_nat), 1))
    #     params["dimensions"] = f"{w_px}x{h_px}"
        
    #     url = img.getDownloadURL(params)
    #     out_tiles.append({"row": t["r"], "col": t["c"], "bbox_crs": t["bbox_crs"], "url": url})

    # return {"tiling": meta, "tiles": out_tiles}
    # # ----- END: Option 2 ----------------------------------------------------



