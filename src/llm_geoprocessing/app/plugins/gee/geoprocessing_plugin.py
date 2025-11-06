def get_metadata_geoprocessing() -> str:
    # Short, complete, laser‑focused list of capabilities.
    return (
        "Geoprocessing Capabilities (GEE):\n"
        "- rgb_tif: Export an RGB GeoTIFF from a single date.\n"
        "- index_tif: Export a normalized‑difference (ND) GeoTIFF from a single date.\n"
        "- rgb_composite_tif: Export an RGB GeoTIFF composited over a date range.\n"
        "- index_composite_tif: Export an ND GeoTIFF composited over a date range.\n"
    )

def get_documentation_geoprocessing() -> str:
    # Definitions, inputs, outputs, usefulness. Short and focused.
    return (
        "GEE Geoprocesses:\n"
        "1) rgb_tif(product,bands,bbox,date,resolution,projection) -> GeoTIFF\n"
        "   - Definition: Builds an RGB image from 3 bands on a single date and returns a GeoTIFF URL.\n"
        "   - Inputs:\n"
        "     • product: GEE image/collection id (e.g., 'COPERNICUS/S2_SR_HARMONIZED').\n"
        "     • bands: 3 comma‑separated bands in RGB order (e.g., 'B4,B3,B2').\n"
        "     • bbox: xmin,ymin,xmax,ymax (lon/lat, EPSG:4326).\n"
        "     • date: 'YYYY‑MM‑DD' (inclusive).\n"
        "     • resolution: meters/pixel or 'default'.\n"
        "     • projection: CRS like 'EPSG:4326' or 'default'.\n"
        "   - Output: URL to a GeoTIFF with 3 bands (R,G,B). Useful for cartography and quick inspection.\n"
        "\n"
        "2) index_tif(product,band1,band2,bbox,date,palette,resolution,projection) -> GeoTIFF\n"
        "   - Definition: Computes normalized difference (band1−band2)/(band1+band2) and returns GeoTIFF URL.\n"
        "   - Inputs: as above; 'palette' is accepted but not applied to GeoTIFF data.\n"
        "   - Output: Single‑band GeoTIFF ('nd'). Useful for vegetation/water/thermal indices.\n"
        "\n"
        "3) rgb_composite_tif(product,bands,bbox,start,end,reducer,resolution,projection) -> GeoTIFF\n"
        "   - Definition: Reduces an image collection over a date range using a reducer and returns RGB GeoTIFF URL.\n"
        "   - Reducer: mean|min|max|median|mosaic (strings).\n"
        "   - Output: 3‑band RGB GeoTIFF. Useful to mitigate clouds and temporal noise.\n"
        "\n"
        "4) index_composite_tif(product,band1,band2,bbox,start,end,palette,reducer,resolution,projection) -> GeoTIFF\n"
        "   - Definition: Per‑image ND, then collection reduced by the chosen reducer; returns GeoTIFF URL.\n"
        "   - Output: Single‑band ND GeoTIFF. Useful for seasonal or multi‑date analysis.\n"
        "\n"
        "Notes:\n"
        "- No cloud masking is applied.\n"
        "- If 'resolution' or 'projection' are 'default', product native values are used.\n"
    )
