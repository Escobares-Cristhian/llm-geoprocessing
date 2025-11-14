def get_metadata_geoprocessing() -> str:
    return (
        "---------- INIT of METADATA of GEOPROCESSING ----------\n"
        "Available GEE geoprocesses (inputs → output → usefulness):\n"
        "\n"
        "1) rgb_single — Single-date RGB GeoTIFF\n"
        "   Inputs: product, bands='R,G,B', bbox='xmin,ymin,xmax,ymax', date, "
        "resolution, projection, apply_cloud_mask (true/false).\n"
        "   Output: GeoTIFF (3 bands). Usefulness: quick visual/export at chosen res/CRS.\n"
        "\n"
        "2) index_single — Single-date normalized difference GeoTIFF\n"
        "   Inputs: product, band1, band2, bbox, date, palette (ignored for TIF), "
        "resolution, projection, apply_cloud_mask (true/false).\n"
        "   Output: GeoTIFF (1 band). Usefulness: NDVI/NDWI-type rasters.\n"
        "\n"
        "3) rgb_composite — Tiled RGB composite (avoids 48 MB/request cap)\n"
        "   Inputs: product, bands, bbox, start, end, reducer, resolution, projection, apply_cloud_mask (true/false).\n"
        "   Output: List of GeoTIFF tile URLs + tiling meta (crs, crs_transform, rows, cols).\n"
        "   Usefulness: large areas at any res without changing analytics; tiles align perfectly "
        "via fixed grid (constant CRS+crs_transform).\n"
        "\n"
        "4) index_composite — Tiled ND composite\n"
        "   Inputs: product, band1, band2, bbox, start, end, reducer, resolution, projection, apply_cloud_mask (true/false).\n"
        "   Output: List of GeoTIFF tile URLs + tiling meta.\n"
        "   Usefulness: large single-band outputs at high resolution.\n"
        "\n\n"
        "Input tips:\n"
        "- 'product' must be unique, a single product a a time, string variable.\n"
        "- 'resolution=\"default\"' uses the product’s native nominal scale or \"float\" meters (no not put units, only number, e.g., 10).\n"
        "- 'projection=\"default\"' uses the product’s native CRS or \"string\" EPSG code.\n"
        "- 'apply_cloud_mask=true' applies basic cloud masking per product; 'false' uses raw data.\n"
        "- If resolution is explicitly in meters, UTM projections are preferred for best results (choose zone accordingly).\n"
        "- If resolution is explicitly in degrees, EPSG:4326 is preferred.\n"
        "- If projection is explicitly mentioned, but resolution is in other units, estimate best matching resolution in the target CRS units.\n"
        "---------- END of METADATA of GEOPROCESSING ----------\n"
    )


def get_documentation_geoprocessing() -> str:
    # When to use each geoprocess (short and focused).
    return (
        "---------- INIT of DOCUMENTATION of GEOPROCESSING ----------\n"
        "When to use each geoprocess:\n"
        "- rgb_single: single-day quicklook/export over small–medium areas at specific date.\n"
        "- index_single: single-day ND (e.g., NDVI/NDWI) over small–medium areas.\n"
        "- rgb_composite: multi-date RGB (mean/median/min/max/mosaic) to reduce clouds.\n"
        "- index_composite:  multi-date ND composites (e.g., seasonal NDVI).\n"
        "---------- END of DOCUMENTATION of GEOPROCESSING ----------\n"
    )
