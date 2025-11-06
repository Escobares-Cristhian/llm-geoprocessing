def get_metadata_preprocessing() -> str:
    # Short list of available satellites/sensors suitable for the functions.
    return (
        "Available GEE Satellites/Sensors:\n"
        "- Sentinel‑2 SR (COPERNICUS/S2_SR_HARMONIZED)\n"
        "- Landsat 8/9 SR (LANDSAT/LC08/C02/T1_L2, LANDSAT/LC09/C02/T1_L2)\n"
        "- Landsat 5 SR (LANDSAT/LT05/C02/T1_L2)\n"
        "- MODIS Surface Reflectance (MODIS/061/MOD09GA)\n"
        "- Sentinel‑1 GRD (C‑band) (COPERNICUS/S1_GRD)\n"
    )

def get_documentation_preprocessing() -> str:
    # Focused text; preprocessing is just listing usable sources for the geoprocesses.
    return (
        "Preprocessing (GEE):\n"
        "- Use the listed satellites/sensors directly with the geoprocesses.\n"
        "- Choose bands that exist in the selected product:"
        "    - Sentinal-2: B1, B2, B3, B4, B5, B6, B7, B8, B8A, B9, B10, B11, B12\n"
        "    - Landsat 8/9: SR_B1, SR_B2, SR_B3, SR_B4, SR_B5, SR_B6, SR_B7, SR_QA_AEROSOL, ST_B10, ST_ATRAN, ST_CDIST, ST_DRAD, ST_EMIS, ST_EMSD, ST_QA, ST_TRAD, ST_URAD, QA_PIXEL, QA_RADSAT\n"
        "    - Landsat 5: SR_B1, SR_B2, SR_B3, SR_B4, SR_B5, SR_B6, SR_B7\n"
        "    - MODIS: sur_refl_b01, sur_refl_b02, sur_refl_b03, sur_refl_b04, sur_refl_b05, sur_refl_b06, sur_refl_b07\n"        
        "- Provide bbox (lon/lat) and dates; no additional preprocessing is required here.\n"
    )
