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
        "- Choose bands that exist in the selected product (e.g., S2: B2,B3,B4; Landsat 8: SR_B2,SR_B3,SR_B4).\n"
        "- Provide bbox (lon/lat) and dates; no additional preprocessing is required here.\n"
    )
