import math
from fastapi import FastAPI, HTTPException, Query
import os, ee, json
from datetime import datetime, timedelta

from logging_config import get_logger
logger = get_logger("gee_geoprocess")

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
        # 1. Parse floats
        parts = [float(x) for x in bbox_str.split(",")]
        if len(parts) != 4:
            raise ValueError
        xmin, ymin, xmax, ymax = parts
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid bbox format. Expected 'xmin,ymin,xmax,ymax'. Got: '{bbox_str}'")

    # 2. logical validation
    if xmin >= xmax or ymin >= ymax:
        raise HTTPException(status_code=400, detail=f"Invalid bbox dimensions: min must be strictly less than max. Expected 'xmin,ymin,xmax,ymax'. Got: '{bbox_str}'")

    # 3. Sanity check for Lat/Lon vs Meters
    # If coordinates are > 180, the user likely passed Web Mercator (meters), 
    # which causes the "Empty" error because the box is off the WGS84 map.
    if abs(xmin) > 360 or abs(ymin) > 180: # loose bounds to catch meter-coordinates
        raise HTTPException(
            status_code=400, 
            detail="Coordinates appear to be in Meters instead of Degrees (Lat/Lon). ). Please provide Lat/Lon (WGS84) decimal degrees."
        )

    # 4. Return geometry
    return ee.Geometry.Rectangle(
        [xmin, ymin, xmax, ymax], 
        proj='EPSG:4326', 
        geodesic=False
    )

def _bbox_vals(bbox_str: str) -> tuple[float, float, float, float]:
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
    # Handle MODIS Thermal (1km) specifically
    if "MOD11" in p or "MYD11" in p:
        return 1000.0
    if "MODIS" in p:
        return 250.0
    return 30.0

def _approx_dims_from_bbox_and_scale(bbox_str: str, scale_m: float) -> tuple[int, int]:
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
        raise HTTPException(status_code=400, detail="Could not infer native projection and scale for the given product and parameters.")

# ---------- Cloud masking helpers (hardcoded per collection) ----------
def _has_band(img: ee.Image, name: str) -> ee.ComputedObject:
    return img.bandNames().contains(name)

def _mask_s2_sr(img: ee.Image) -> ee.Image:
    # Prefer SCL when present (mask clouds, cirrus, shadows, snow/ice)
    def _from_scl(i):
        scl = i.select('SCL')
        mask = (scl.neq(3)     # Cloud shadows
                .And(scl.neq(7))  # Unclassified / low prob clouds
                .And(scl.neq(8))  # Medium prob clouds
                .And(scl.neq(9))  # High prob clouds
                .And(scl.neq(10)) # Thin cirrus
                .And(scl.neq(11)) # Snow / Ice
               )
        return i.updateMask(mask)
    # Fallback to legacy QA60 (bit 10: opaque cloud, bit 11: cirrus)
    def _from_qa60(i):
        qa = i.select('QA60')
        cloud  = qa.bitwiseAnd(1 << 10).eq(0)
        cirrus = qa.bitwiseAnd(1 << 11).eq(0)
        return i.updateMask(cloud.And(cirrus))
    return ee.Image(ee.Algorithms.If(_has_band(img, 'SCL'),
                                     _from_scl(img),
                                     ee.Algorithms.If(_has_band(img, 'QA60'), _from_qa60(img), img)))

def _mask_landsat_c2_sr(img: ee.Image) -> ee.Image:
    # QA_PIXEL bits (C2 L2): 1=dilated cloud, 3=cloud, 4=cloud shadow, 5=snow, 6=clear
    qa = img.select('QA_PIXEL')
    not_dilated = qa.bitwiseAnd(1 << 1).eq(0)
    not_cloud   = qa.bitwiseAnd(1 << 3).eq(0)
    not_shadow  = qa.bitwiseAnd(1 << 4).eq(0)
    not_snow    = qa.bitwiseAnd(1 << 5).eq(0)
    is_clear    = qa.bitwiseAnd(1 << 6).neq(0)
    mask = not_dilated.And(not_cloud).And(not_shadow).And(not_snow).And(is_clear)
    return img.updateMask(mask)

# # HARD MASK FOR MODIS
# def _mask_modis_sr(img: ee.Image) -> ee.Image:
#     # MOD09GA 'state_1km': 0-1 cloud state (0=clear), 2 cloud shadow (0=no),
#     # 8-9 cirrus (0=none), 10 internal cloud flag (0=no)
#     qa = img.select('state_1km')
#     cloud_state_clear = qa.bitwiseAnd(3).eq(0)                          # bits 0-1
#     no_shadow         = qa.rightShift(2).bitwiseAnd(1).eq(0)            # bit 2
#     no_cirrus         = qa.rightShift(8).bitwiseAnd(3).eq(0)            # bits 8-9
#     no_internal_cloud = qa.rightShift(10).bitwiseAnd(1).eq(0)           # bit 10
#     mask = cloud_state_clear.And(no_shadow).And(no_cirrus).And(no_internal_cloud)
#     return img.updateMask(mask)

# SOFT MASK FOR MODIS
def _mask_modis_sr(img: ee.Image) -> ee.Image:
    qa = img.select('state_1km')

    # Bits 0–1: 0=clear, 1=cloudy, 2=mixed, 3=unknown
    cloud_state    = qa.bitwiseAnd(3)
    not_cloud      = cloud_state.neq(1)            # reject only 'cloudy' (keep mixed/unknown)

    # Bit 2: cloud shadow (1=yes)
    no_shadow      = qa.rightShift(2).bitwiseAnd(1).eq(0)

    # Bits 8–9: cirrus (0=none, 1=small, 2=average, 3=high)
    cirrus_level   = qa.rightShift(8).bitwiseAnd(3)
    accept_cirrus  = cirrus_level.lte(1)           # allow none or small

    # Bit 10: internal cloud flag; skip to avoid overmasking (or require eq(0) only if you want stricter)
    mask = not_cloud.And(no_shadow).And(accept_cirrus)

    return img.updateMask(mask)

def _apply_cloud_mask_by_product(img: ee.Image, product: str) -> ee.Image:
    p = (product or '').upper()
    try:
        if 'COPERNICUS/S2_SR' in p or 'S2_SR_HARMONIZED' in p:
            return _mask_s2_sr(img)
        if 'LANDSAT/' in p and '/C02/' in p and ('_L2' in p or p.endswith('_L2')):
            return _mask_landsat_c2_sr(img)
        if 'MODIS/061/MOD09' in p:
            return _mask_modis_sr(img)
        # Default: return as-is (e.g., radar, thermal-only, or unknown products)
        return img
    except Exception:
        # Be conservative if any band is missing: don't change the image.
        return img

# ---------- Tiling helpers (client-side, fixed grid) ----------
def _region_in_crs(region: ee.Geometry, crs: str, scale: float) -> ee.Geometry:
    # max_error for transform (1000 pixel), only used to avoid precision issues
    max_error = abs(float(scale)) * 1000.0

    try:
        return ee.Geometry(region).transform(crs, max_error)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not transform region to the target CRS.")

def _projected_bbox(region: ee.Geometry, crs: str) -> tuple[float, float, float, float]:
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
    
    # 1. Calculate the bounding box in the target CRS
    minx, miny, maxx, maxy = _projected_bbox(region, crs)
    
    # 2. Align grid to standard origin to ensure consistent tiling
    origin_x, origin_y, gx0, gy0, gx1, gy1 = _align_to_grid(minx, miny, maxx, maxy, scale)

    tile_w = tile_size * scale
    tile_h = tile_size * scale

    cols = max(int(math.ceil((gx1 - gx0) / tile_w)), 1)
    rows = max(int(math.ceil((gy1 - gy0) / tile_h)), 1)

    tiles = []
    
    # REMOVED: region_proj = region.transform(crs, 1) 
    # We don't need the complex polygon anymore, the bbox grid is sufficient.

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
            
            # Create the exact tile geometry
            rect = ee.Geometry.Rectangle([x_left, y_bot, x_right, y_top], proj=crs, geodesic=False)
            
            # --- CRITICAL FIX ---
            # Do NOT use rect.intersection(region_proj).
            # It causes "Empty Geometry" errors on edge tiles due to precision.
            # Passing the full 'rect' is safe; we avoid ROI masking here to
            # keep edge pixels intact and prevent 0-filled seams on merge.
            
            tiles.append({
                "r": r, 
                "c": c, 
                "geom": rect, # Use the full rectangle
                "bbox_crs": [x_left, y_bot, x_right, y_top]
            })

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

def _get_download_url(img: ee.Image, params: dict, tag: str) -> str:
    try:
        return img.getDownloadURL(params)
    except ee.ee_exception.EEException as exc:
        logger.debug(f"GEE download error [{tag}]: {exc}")
        raise HTTPException(status_code=401, detail=f"{tag}: {exc}")

def _resolve_crs_scale(
    *,
    product: str,
    region: ee.Geometry,
    sample_band: str,
    start: str,
    end: str,
    projection: str,
    resolution: str,
    log_tag: str,
) -> tuple[str, float]:
    """
    Resolve target CRS and scale starting from product-native values
    and applying optional projection/resolution overrides.
    """
    if projection == "default" or resolution == "default":
        crs_nat, scale_nat = _infer_native_proj(product, region, sample_band, start, end)
        logger.debug("-" * 60)
        logger.debug(f"[{log_tag}] Native CRS/scale: crs={crs_nat}, scale={scale_nat}")
        if projection == "default" and resolution != "default":
            scale_nat = float(resolution)
        elif projection != "default" and resolution == "default":
            crs_nat = projection
        logger.debug(f"[{log_tag}] User overrides applied -> crs={crs_nat}, scale={scale_nat}")
        logger.debug("-" * 60)
    else:
        crs_nat, scale_nat = projection, float(resolution)
        logger.debug(f"[{log_tag}] Using custom CRS/scale -> crs={crs_nat}, scale={scale_nat}")
    return crs_nat, scale_nat

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
def _collection(product: str, region: ee.Geometry, start: str, end: str, cloud_mask: bool = False) -> ee.ImageCollection:
    col = ee.ImageCollection(product).filterBounds(region).filterDate(start, end)
    if cloud_mask:
        col = col.map(lambda i: _apply_cloud_mask_by_product(ee.Image(i), product))
    return col

# --- scale+offset helpers ---
def _band_scale_offset(img: ee.Image, band: str, product: str) -> tuple[float, float]:
    """
    Try to read per-band scale/offset from metadata (various common keys).
    If absent (which is the case for Landsat C2 L2 and S2 SR in GEE), fall back by product family.
    """
    s, o = None, None
    try:
        info = img.select([band]).getInfo()  # one client-side hit
        bmeta = (info.get('bands', [{}])[0] or {})
        props = (bmeta.get('properties') or {})
        # Do NOT default here — we need to detect absence.
        for k in ('scale', 'SCALE', 'scale_factor', 'SCALE_FACTOR'):
            if props.get(k) is not None:
                s = float(props.get(k)); break
        for k in ('offset', 'OFFSET', 'add_offset', 'ADD_OFFSET'):
            if props.get(k) is not None:
                o = float(props.get(k)); break
    except Exception:
        pass

    if s is None or o is None:
        # No usable per-band metadata: choose by asset id / product id.
        # (GEE doesn't expose these for LANDSAT C2 L2 or S2 SR.)
        try:
            asset_id = (img.get('system:asset_id') or img.get('system:id')).getInfo()
        except Exception:
            asset_id = ''
        pid = ((product or '') + '|' + (asset_id or '')).upper()

        # Landsat Collection 2 Level-2 (optical SR / thermal ST)
        if ('LANDSAT/LC08/C02/T1_L2' in pid) or ('LANDSAT/LC09/C02/T1_L2' in pid):
            if band.startswith('SR_B'):
                s, o = 2.75e-5, -0.2
            elif band.startswith('ST_B'):
                s, o = 0.00341802, 149.0

        # Sentinel-2 SR (harmonized or not) — reflectance is scale 1e-4, no offset
        elif 'COPERNICUS/S2_SR' in pid:
            s, o = 1e-4, 0.0

        # MODIS LST (Temperature & Emissivity)
        elif 'MODIS/' in pid and ('MOD11A1' in pid or 'MYD11A1' in pid):
            if 'LST_' in band:
                s, o = 0.02, 0.0  # Converts DN to Kelvin
            elif 'Emis_' in band:
                s, o = 0.002, 0.49 # Specific scale/offset for emissivity bands

        # Final fallback
        if s is None: s = 1.0
        if o is None: o = 0.0

    logger.debug(f"[_band_scale_offset] product~='{product}', band={band}, scale={s}, offset={o}")
    return s, o

# Apply scale+offset to 1..N bands
def _apply_scale_offset_multi(img: ee.Image, product: str, bands: list[str] | None) -> ee.Image:
    if bands is None:
        # use all band names from the image
        bands = ee.Image(img).bandNames().getInfo()

    scaled = []
    for b in bands:
        s, o = _band_scale_offset(img, b, product)
        scaled_band = img.select([b]).multiply(s).add(o).rename(b)
        scaled.append(scaled_band)

    out = ee.Image.cat(scaled)
    return ee.Image(out.copyProperties(img, img.propertyNames()))


# --- n-band image builders ---
def _bands_image_single(
    product: str,
    bands_csv: str | None,
    region: ee.Geometry,
    date: str,
    cloud_mask: bool = False,
    apply_scale_offset: bool = False,
) -> ee.Image:
    start, end = _date_and_next(date)
    col = _collection(product, region, start, end, cloud_mask=cloud_mask)
    img = col.mosaic()

    bands_list = None
    if bands_csv:
        bands_list = [s.strip() for s in bands_csv.split(",") if s.strip()]
        if bands_list:
            img = img.select(bands_list)

    if apply_scale_offset:
        img = _apply_scale_offset_multi(img, product, bands_list)

    return img

def _bands_image_composite(
    product: str,
    bands_csv: str | None,
    region: ee.Geometry,
    start: str,
    end: str,
    reducer: str,
    cloud_mask: bool = False,
    apply_scale_offset: bool = False,
) -> ee.Image:
    col = _collection(product, region, start, end, cloud_mask=cloud_mask)

    bands_list = None
    if bands_csv:
        bands_list = [s.strip() for s in bands_csv.split(",") if s.strip()]
        if bands_list:
            col = col.select(bands_list)

    how = _resolve_reducer(reducer)
    img = col.mosaic() if how == "mosaic" else getattr(col, how)()

    if apply_scale_offset:
        img = _apply_scale_offset_multi(img, product, bands_list)

    return img


# --- RGB image builders ---
def _rgb_image_single(
    product: str,
    bands_csv: str,
    region: ee.Geometry,
    date: str,
    cloud_mask: bool = False,
    apply_scale_offset: bool = False,
) -> ee.Image:
    b = [s.strip() for s in bands_csv.split(",")]
    if len(b) != 3:
        raise HTTPException(status_code=400, detail="Provide exactly 3 bands in RGB order, comma-separated.")
    start, end = _date_and_next(date)
    img = _collection(product, region, start, end, cloud_mask=cloud_mask).mosaic().select(b)

    if apply_scale_offset:
        img = _apply_scale_offset_multi(img, product, b)

    return img

def _rgb_image_composite(
    product: str,
    bands_csv: str,
    region: ee.Geometry,
    start: str,
    end: str,
    reducer: str,
    cloud_mask: bool = False,
    apply_scale_offset: bool = False,
) -> ee.Image:
    b = [s.strip() for s in bands_csv.split(",")]
    if len(b) != 3:
        raise HTTPException(status_code=400, detail="Provide exactly 3 bands in RGB order, comma-separated.")
    col = _collection(product, region, start, end, cloud_mask=cloud_mask).select(b)
    how = _resolve_reducer(reducer)
    if how == "mosaic":
        img = col.mosaic()
    else:
        img = getattr(col, how)()
    if apply_scale_offset:
        img = _apply_scale_offset_multi(img, product, b)

    return img

# --- Normalized Difference Index builders ---
def _scaled_nd(img: ee.Image, b1: str, b2: str, s1: float, o1: float, s2: float, o2: float) -> ee.Image:
    return img.expression(
        '((b1*s1 + o1) - (b2*s2 + o2)) / ((b1*s1 + o1) + (b2*s2 + o2))',
        {'b1': img.select(b1), 'b2': img.select(b2),
         's1': ee.Number(s1),  'o1': ee.Number(o1),
         's2': ee.Number(s2),  'o2': ee.Number(o2)}
    ).rename('nd')

def _nd_image_single(product: str, b1: str, b2: str, region: ee.Geometry, date: str, cloud_mask: bool = False) -> ee.Image:
    start, end = _date_and_next(date)
    col  = _collection(product, region, start, end, cloud_mask=cloud_mask)
    first = ee.Image(col.first())
    s1, o1 = _band_scale_offset(first, b1, product)
    s2, o2 = _band_scale_offset(first, b2, product)
    col_nd = col.map(lambda im: _scaled_nd(ee.Image(im), b1, b2, s1, o1, s2, o2))
    img_nd = col_nd.mosaic()
    return img_nd

def _nd_image_composite(product: str, b1: str, b2: str, region: ee.Geometry, start: str, end: str, reducer: str, cloud_mask: bool = False) -> ee.Image:
    col   = _collection(product, region, start, end, cloud_mask=cloud_mask)
    first = ee.Image(col.first())
    s1, o1 = _band_scale_offset(first, b1, product)
    s2, o2 = _band_scale_offset(first, b2, product)
    col_nd = col.map(lambda im: _scaled_nd(ee.Image(im), b1, b2, s1, o1, s2, o2))
    how = _resolve_reducer(reducer)
    img = col_nd.mosaic() if how == "mosaic" else getattr(col_nd, how)()
    return img


# --- Endpoints (return a signed URL for GeoTIFF download) ---
@app.get("/tif/bands_single")
def bands_single(
    product: str = Query(..., description="GEE image or collection id"),
    bands: str = Query(
        "",
        description="Comma-separated band names (1..N). Leave empty or 'None' to export all bands.",
    ),
    bbox: str = Query(..., description="xmin,ymin,xmax,ymax (lon/lat)"),
    date: str = Query(..., description="YYYY-MM-DD"),
    resolution: str = Query("default"),
    projection: str = Query("default"),
    tile_size: int = Query(1024, description="tile size in pixels (edge)"),
    max_tiles: int = Query(25, description="safety cap on total tiles"),
    apply_scale_offset: bool = Query(False),
    apply_cloud_mask: bool = Query(False),
):
    _init_ee()
    region = _parse_bbox(bbox)

    # Interpret bands parameter: empty / 'none' / 'all' -> all bands
    bands_arg = bands.strip()
    if bands_arg.lower() in ("", "none", "all"):
        bands_arg = None

    img = _bands_image_single(
        product,
        bands_arg,
        region,
        date,
        cloud_mask=bool(apply_cloud_mask),
        apply_scale_offset=bool(apply_scale_offset),
    )

    # Use first requested band as sample when available, otherwise let
    # _infer_native_proj fall back to the first band in the image.
    sample_band = ""
    if bands_arg:
        sample_band = bands_arg.split(",")[0].strip()

    start_iso, end_iso = _date_and_next(date)
    crs_nat, scale_nat = _resolve_crs_scale(
        product=product,
        region=region,
        sample_band=sample_band,
        start=start_iso,
        end=end_iso,
        projection=projection,
        resolution=resolution,
        log_tag="bands_single",
    )

    region_proj = _region_in_crs(region, crs_nat, scale_nat)
    img = img.clip(region_proj)

    logger.debug(f"[bands_single] grid -> crs={crs_nat}, scale={scale_nat}, tile={tile_size}px")
    tiles, meta = _tile_rects(crs_nat, region_proj, scale_nat, tile_size)
    if len(tiles) > max_tiles:
        logger.info(f"Too many tiles: {len(tiles)} > max_tiles={max_tiles}")
        raise HTTPException(
            status_code=400,
            detail=f"Too many tiles: {len(tiles)} > max_tiles={max_tiles}",
        )

    img = img.reproject(crs=crs_nat, crsTransform=meta["crs_transform"])
    common = {"format": "GEO_TIFF", "crs": crs_nat, "crs_transform": meta["crs_transform"]}

    out_tiles = []
    for t in tiles:
        params = dict(common)
        params["region"] = t["geom"]
        url = _get_download_url(img, params, "bands_single")
        out_tiles.append(
            {"row": t["r"], "col": t["c"], "bbox_crs": t["bbox_crs"], "url": url}
        )

    return {"tiling": meta, "tiles": out_tiles}

@app.get("/tif/bands_composite")
def bands_composite(
    product: str = Query(..., description="GEE collection id"),
    bands: str = Query(
        "",
        description="Comma-separated band names (1..N). Leave empty or 'None' to export all bands.",
    ),
    bbox: str = Query(..., description="xmin,ymin,xmax,ymax (lon/lat)"),
    start: str = Query(..., description="YYYY-MM-DD inclusive"),
    end: str = Query(..., description="YYYY-MM-DD inclusive"),
    reducer: str = Query("mean"),
    resolution: str = Query("default"),
    projection: str = Query("default"),
    tile_size: int = Query(1024, description="tile size in pixels (edge)"),
    max_tiles: int = Query(25, description="safety cap on total tiles"),
    apply_scale_offset: bool = Query(False),
    apply_cloud_mask: bool = Query(False),
):
    _init_ee()
    region = _parse_bbox(bbox)

    # end inclusive
    try:
        end_iso = (datetime.strptime(end, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid end date. Use 'YYYY-MM-DD'.")

    # Normalize "all bands" case
    bands_arg = bands.strip()
    if bands_arg.lower() in ("", "none", "all"):
        bands_arg = None

    img = _bands_image_composite(
        product,
        bands_arg,
        region,
        start,
        end_iso,
        reducer,
        cloud_mask=bool(apply_cloud_mask),
        apply_scale_offset=bool(apply_scale_offset),
    )

    sample_band = ""
    if bands_arg:
        sample_band = bands_arg.split(",")[0].strip()

    crs_nat, scale_nat = _resolve_crs_scale(
        product=product,
        region=region,
        sample_band=sample_band,
        start=start,
        end=end_iso,
        projection=projection,
        resolution=resolution,
        log_tag="bands_composite",
    )

    region_proj = _region_in_crs(region, crs_nat, scale_nat)
    img = img.clip(region_proj)

    logger.debug(f"[bands_composite] grid -> crs={crs_nat}, scale={scale_nat}, tile={tile_size}px")
    tiles, meta = _tile_rects(crs_nat, region_proj, scale_nat, tile_size)
    if len(tiles) > max_tiles:
        logger.info(f"Too many tiles: {len(tiles)} > max_tiles={max_tiles}")
        raise HTTPException(
            status_code=400,
            detail=f"Too many tiles: {len(tiles)} > max_tiles={max_tiles}",
        )

    img = img.reproject(crs=crs_nat, crsTransform=meta["crs_transform"])
    common = {"format": "GEO_TIFF", "crs": crs_nat, "crs_transform": meta["crs_transform"]}

    out_tiles = []
    for t in tiles:
        params = dict(common)
        params["region"] = t["geom"]
        url = _get_download_url(img, params, "bands_composite")
        out_tiles.append(
            {"row": t["r"], "col": t["c"], "bbox_crs": t["bbox_crs"], "url": url}
        )

    return {"tiling": meta, "tiles": out_tiles}

@app.get("/tif/rgb_single")
def rgb_single(
    product: str = Query(..., description="GEE image or collection id"),
    bands: str   = Query(..., description="Comma-separated 3 bands in RGB order"),
    bbox: str    = Query(..., description="xmin,ymin,xmax,ymax (lon/lat)"),
    date: str    = Query(..., description="YYYY-MM-DD"),
    resolution: str = Query("default"),
    projection: str = Query("default"),
    tile_size: int = Query(1024, description="tile size in pixels (edge)"),
    max_tiles: int = Query(25, description="safety cap on total tiles"),
    apply_cloud_mask: bool = Query(False),
    apply_scale_offset: bool = Query(False),
):
    _init_ee()
    region = _parse_bbox(bbox)
    img = _rgb_image_single(
        product,
        bands,
        region,
        date,
        cloud_mask=bool(apply_cloud_mask),
        apply_scale_offset=bool(apply_scale_offset),
    )

    # Resolve CRS & scale from native projection plus optional overrides
    first_band = bands.split(",")[0].strip()
    start_iso, end_iso = _date_and_next(date)
    crs_nat, scale_nat = _resolve_crs_scale(
        product=product,
        region=region,
        sample_band=first_band,
        start=start_iso,
        end=end_iso,
        projection=projection,
        resolution=resolution,
        log_tag="rgb_single",
    )

    region_proj = _region_in_crs(region, crs_nat, scale_nat)
    img = img.clip(region_proj)

    logger.debug(f"[rgb_single] grid -> crs={crs_nat}, scale={scale_nat}, tile={tile_size}px")
    tiles, meta = _tile_rects(crs_nat, region_proj, scale_nat, tile_size)
    if len(tiles) > max_tiles:
        logger.info(f"Too many tiles: {len(tiles)} > max_tiles={max_tiles}")
        raise HTTPException(status_code=400, detail=f"Too many tiles: {len(tiles)} > max_tiles={max_tiles}")

    img = img.reproject(crs=crs_nat, crsTransform=meta["crs_transform"])
    common = {"format": "GEO_TIFF", "crs": crs_nat, "crs_transform": meta["crs_transform"]}

    out_tiles = []
    for t in tiles:
        params = dict(common)
        params["region"] = t["geom"]
        url = _get_download_url(img, params, "rgb_single")
        out_tiles.append({"row": t["r"], "col": t["c"], "bbox_crs": t["bbox_crs"], "url": url})

    return {"tiling": meta, "tiles": out_tiles}

@app.get("/tif/rgb_composite")
def rgb_composite(
    product: str = Query(..., description="GEE collection id"),
    bands: str   = Query(..., description="Comma-separated 3 bands in RGB order"),
    bbox: str    = Query(..., description="xmin,ymin,xmax,ymax (lon/lat)"),
    start: str   = Query(..., description="YYYY-MM-DD inclusive"),
    end: str     = Query(..., description="YYYY-MM-DD inclusive"),
    reducer: str = Query("mean"),
    resolution: str = Query("default"),
    projection: str = Query("default"),
    tile_size: int = Query(1024, description="tile size in pixels (edge)"),
    max_tiles: int = Query(25, description="safety cap on total tiles"),
    apply_cloud_mask: bool = Query(False),
    apply_scale_offset: bool = Query(False),
):
    _init_ee()
    region = _parse_bbox(bbox)
    # end inclusive
    try:
        end_iso = (datetime.strptime(end, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid end date. Use 'YYYY-MM-DD'.")
    img = _rgb_image_composite(
        product,
        bands,
        region,
        start,
        end_iso,
        reducer,
        cloud_mask=bool(apply_cloud_mask),
        apply_scale_offset=bool(apply_scale_offset),
    )

    first_band = bands.split(",")[0].strip()
    crs_nat, scale_nat = _resolve_crs_scale(
        product=product,
        region=region,
        sample_band=first_band,
        start=start,
        end=end_iso,
        projection=projection,
        resolution=resolution,
        log_tag="rgb_composite",
    )

    region_proj = _region_in_crs(region, crs_nat, scale_nat)
    img = img.clip(region_proj)

    logger.debug(f"[rgb_composite] grid -> crs={crs_nat}, scale={scale_nat}, tile={tile_size}px")
    tiles, meta = _tile_rects(crs_nat, region_proj, scale_nat, tile_size)
    if len(tiles) > max_tiles:
        logger.info(f"Too many tiles: {len(tiles)} > max_tiles={max_tiles}")
        raise HTTPException(status_code=400, detail=f"Too many tiles: {len(tiles)} > max_tiles={max_tiles}")

    # Use crs + per-tile dimensions (omit crs_transform to avoid overspecification with dimensions).
    img = img.reproject(crs=crs_nat, crsTransform=meta["crs_transform"])
    common = {"format": "GEO_TIFF", "crs": crs_nat, "crs_transform": meta["crs_transform"]}

    out_tiles = []
    for t in tiles:
        params = dict(common)
        params["region"] = t["geom"]
        url = _get_download_url(img, params, "rgb_composite")
        out_tiles.append({"row": t["r"], "col": t["c"], "bbox_crs": t["bbox_crs"], "url": url})

    logger.info("DONE ALL TILES")
    return {"tiling": meta, "tiles": out_tiles}

@app.get("/tif/index_single")
def index_single(
    product: str = Query(..., description="GEE image or collection id"),
    band1: str   = Query(..., description="First band for ND numerator"),
    band2: str   = Query(..., description="Second band for ND denominator"),
    bbox: str    = Query(..., description="xmin,ymin,xmax,ymax (lon/lat)"),
    date: str    = Query(..., description="YYYY-MM-DD"),
    palette: str = Query("", description="Comma colors (ignored for GeoTIFF data)"),
    resolution: str = Query("default"),
    projection: str = Query("default"),
    tile_size: int = Query(2048, description="tile size in pixels (edge)"),
    max_tiles: int = Query(25, description="safety cap on total tiles"),
    apply_cloud_mask: bool = Query(False)
):
    _init_ee()
    region = _parse_bbox(bbox)
    img = _nd_image_single(product, band1, band2, region, date, cloud_mask=bool(apply_cloud_mask))

    start_iso, end_iso = _date_and_next(date)
    crs_nat, scale_nat = _resolve_crs_scale(
        product=product,
        region=region,
        sample_band=band1,
        start=start_iso,
        end=end_iso,
        projection=projection,
        resolution=resolution,
        log_tag="index_single",
    )

    region_proj = _region_in_crs(region, crs_nat, scale_nat)
    img = img.clip(region_proj)

    logger.debug(f"[index_single] grid -> crs={crs_nat}, scale={scale_nat}, tile={tile_size}px")
    tiles, meta = _tile_rects(crs_nat, region_proj, scale_nat, tile_size)
    if len(tiles) > max_tiles:
        logger.info(f"Too many tiles: {len(tiles)} > max_tiles={max_tiles}")
        raise HTTPException(status_code=400, detail=f"Too many tiles: {len(tiles)} > max_tiles={max_tiles}")

    img = img.reproject(crs=crs_nat, crsTransform=meta["crs_transform"])
    common = {"format": "GEO_TIFF", "crs": crs_nat, "crs_transform": meta["crs_transform"]}

    out_tiles = []
    for t in tiles:
        params = dict(common)
        params["region"] = t["geom"]
        url = _get_download_url(img, params, "index_single")
        out_tiles.append({"row": t["r"], "col": t["c"], "bbox_crs": t["bbox_crs"], "url": url})

    return {"tiling": meta, "tiles": out_tiles}

@app.get("/tif/index_composite")
def index_composite(
    product: str = Query(..., description="GEE collection id"),
    band1: str   = Query(..., description="First band for ND numerator"),
    band2: str   = Query(..., description="Second band for ND denominator"),
    bbox: str    = Query(..., description="xmin,ymin,xmax,ymax (lon/lat)"),
    start: str   = Query(..., description="YYYY-MM-DD inclusive"),
    end: str     = Query(..., description="YYYY-MM-DD inclusive"),
    reducer: str = Query("mean"),
    resolution: str = Query("default"),
    projection: str = Query("default"),
    tile_size: int = Query(2048, description="tile size in pixels (edge)"),
    max_tiles: int = Query(25, description="safety cap on total tiles"),
    apply_cloud_mask: bool = Query(False)
):
    _init_ee()
    region = _parse_bbox(bbox)
    # end inclusive
    try:
        end_iso = (datetime.strptime(end, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid end date. Use 'YYYY-MM-DD'.")
    img = _nd_image_composite(product, band1, band2, region, start, end_iso, reducer, cloud_mask=bool(apply_cloud_mask))

    crs_nat, scale_nat = _resolve_crs_scale(
        product=product,
        region=region,
        sample_band=band1,
        start=start,
        end=end_iso,
        projection=projection,
        resolution=resolution,
        log_tag="index_composite",
    )

    region_proj = _region_in_crs(region, crs_nat, scale_nat)
    img = img.clip(region_proj)

    logger.debug(f"[index_composite] grid -> crs={crs_nat}, scale={scale_nat}, tile={tile_size}px")
    tiles, meta = _tile_rects(crs_nat, region_proj, scale_nat, tile_size)
    if len(tiles) > max_tiles:
        logger.info(f"Too many tiles: {len(tiles)} > max_tiles={max_tiles}")
        raise HTTPException(status_code=400, detail=f"Too many tiles: {len(tiles)} > max_tiles={max_tiles}")

    # Use crs + per-tile dimensions (omit crs_transform to avoid overspecification with dimensions).
    img = img.reproject(crs=crs_nat, crsTransform=meta["crs_transform"])
    common = {"format": "GEO_TIFF", "crs": crs_nat, "crs_transform": meta["crs_transform"]}

    out_tiles = []
    for t in tiles:
        params = dict(common)
        params["region"] = t["geom"]
        url = _get_download_url(img, params, "index_composite")
        out_tiles.append({"row": t["r"], "col": t["c"], "bbox_crs": t["bbox_crs"], "url": url})

    return {"tiling": meta, "tiles": out_tiles}
