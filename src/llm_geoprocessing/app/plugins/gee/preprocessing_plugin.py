def get_metadata_preprocessing() -> str:
    # Only GEE dataset IDs (satellites/products) supported by this plugin.
    return (
        "GEE products:\n"
        "- COPERNICUS/S2_SR_HARMONIZED: Sentinel-2 Surface Reflectance\n"
        "- LANDSAT/LC08/C02/T1_L2: Landsat 8 Surface Reflectance\n"
        "- LANDSAT/LC09/C02/T1_L2: Landsat 9 Surface Reflectance\n"
        "- LANDSAT/LE07/C02/T1_L2: Landsat 7 Surface Reflectance\n"
        "- LANDSAT/LT05/C02/T1_L2: Landsat 5 Surface Reflectance\n"
        "- MODIS/006/MOD09GA: MODIS Terra Surface Reflectance\n"
        "- MODIS/006/MYD09GA: MODIS Aqua Surface Reflectance\n"
    )


def get_documentation_preprocessing() -> str:
    # Bands available per product (short, focused). Use exact GEE band names.
    return (
        "Bands by product:\n"
        "• COPERNICUS/S2_SR_HARMONIZED: "
        "B1(443), B2(490), B3(560), B4(665), B5(705), B6(740), B7(783), "
        "B8(842), B8A(865), B9(945), B11(1610), B12(2190), QA60.\n"
        "• LANDSAT/LC08/C02/T1_L2 (L8) & LANDSAT/LC09/C02/T1_L2 (L9): "
        "SR_B1(ultraBlue), SR_B2(Blue), SR_B3(Green), SR_B4(Red), "
        "SR_B5(NIR), SR_B6(SWIR1), SR_B7(SWIR2), ST_B10(thermal), QA_PIXEL, QA_RADSAT.\n"
        "• LANDSAT/LE07/C02/T1_L2 (L7): "
        "SR_B1(Blue), SR_B2(Green), SR_B3(Red), SR_B4(NIR), SR_B5(SWIR1), SR_B7(SWIR2), ST_B6, QA_PIXEL, QA_RADSAT.\n"
        "• LANDSAT/LT05/C02/T1_L2 (L5): "
        "SR_B1(Blue), SR_B2(Green), SR_B3(Red), SR_B4(NIR), SR_B5(SWIR1), SR_B7(SWIR2), ST_B6, QA_PIXEL, QA_RADSAT.\n"
        "• MODIS/006/MOD09GA (Terra) & MODIS/006/MYD09GA (Aqua): "
        "sur_refl_b01..b07 (b01 Red, b02 NIR, b03 Blue, b04 Green, b05 NIR2, b06 SWIR1, b07 SWIR2), "
        "plus qa bands. Note: b01–b02 at 250 m; b03–b07 at 500 m."
        "\n\n\n"
        "Available projections in GEE: <GEE CRS>: <Description and usual names>\n"
        "- EPSG:4326: WGS 84 (lat/lon)\n"
        "- EPSG:3857: Web Mercator (Google Maps, OSM)\n"
        "- EPSG:326XX / EPSG:327XX: UTM zones (XX = zone number, 6 for northern hemisphere, 7 for southern hemisphere). Example: EPSG:32606 for UTM zone 6N., EPSG:32733 for UTM zone 33S.\n"
        "- \"default\": product-native CRS. Do not put \"native\" or similar, only \"default\" is accepted.\n"
        "Do not assume availability of any CRS not listed here.\n"
    )
