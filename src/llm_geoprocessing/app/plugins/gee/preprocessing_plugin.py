def get_metadata_preprocessing() -> str:
    print("Using DUMMY metadata preprocessing instructions.")
    return (
        "SATELLITE DATA\n"
        "- Sentinel-2 RGB: High-resolution optical imagery with 10m spatial resolution.\n"
        "    - Available Dates: From 2015-06-23 to present.\n"
        "    - Bands: RGB (only available, not need to ask for others).\n"
        "    - Resolution: 10 meters per pixel (native is the only available, not need to ask for others).\n"
        "    - Projection: EPSG:4326 (WGS84). (native is the only available, not need to ask for others).\n"
        
        ""
    )

def get_documentation_preprocessing() -> str:
    print("Using DUMMY documentation preprocessing instructions.")
    return (
        "Preprocessing Functions:\n"
        "- No preprocessing function, only a ready-to-use geoprocessing functions.\n"
        ""
    )