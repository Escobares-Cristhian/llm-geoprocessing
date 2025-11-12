def get_metadata_geoprocessing() -> str:
    return (
        "Available GEE geoprocesses (inputs → output → usefulness):\n"
        "\n"
        "1) rgb_single — Single-date RGB GeoTIFF\n"
        "   Inputs: product, bands='R,G,B', bbox='xmin,ymin,xmax,ymax', date, "
        "resolution (meters or 'default'), projection (CRS or 'default'), apply_cloud_mask (true/false).\n"
        "   Output: GeoTIFF (3 bands). Usefulness: quick visual/export at chosen res/CRS.\n"
        "\n"
        "2) index_tif — Single-date normalized difference GeoTIFF\n"
        "   Inputs: product, band1, band2, bbox, date, palette (ignored for TIF), "
        "resolution, projection, apply_cloud_mask (true/false).\n"
        "   Output: GeoTIFF (1 band). Usefulness: NDVI/NDWI-type rasters.\n"
        "\n"
        "3) rgb_composite_tif_tiled — Tiled RGB composite (avoids 48 MB/request cap)\n"
        "   Inputs: product, bands, bbox, start, end, reducer, resolution, projection, apply_cloud_mask (true/false).\n"
        "   Output: List of GeoTIFF tile URLs + tiling meta (crs, crs_transform, rows, cols).\n"
        "   Usefulness: large areas at any res without changing analytics; tiles align perfectly "
        "via fixed grid (constant CRS+crs_transform).\n"
        "\n"
        "4) index_composite_tif_tiled — Tiled ND composite\n"
        "   Inputs: product, band1, band2, bbox, start, end, reducer, resolution, projection, apply_cloud_mask (true/false).\n"
        "   Output: List of GeoTIFF tile URLs + tiling meta.\n"
        "   Usefulness: large single-band outputs at high resolution.\n"
        "\n\n"
        "Input tips:\n"
        "- 'resolution=\"default\"' uses the product’s native nominal scale; "
        "- 'projection=\"default\"' uses the product’s native CRS.\n"
        "- 'apply_cloud_mask=true' applies basic cloud masking per product; 'false' uses raw data.\n"
    )


def get_documentation_geoprocessing() -> str:
    # When to use each geoprocess (short and focused).
    return (
        "When to use each geoprocess:\n"
        "- rgb_single: single-day quicklook/export over small–medium areas at specific date.\n"
        "- index_tif: single-day ND (e.g., NDVI/NDWI) over small–medium areas.\n"
        "- rgb_composite_tif_tiled: multi-date RGB (mean/median/min/max/mosaic) to reduce clouds.\n"
        "- index_composite_tif_tiled:  multi-date ND composites (e.g., seasonal NDVI).\n"
    )
