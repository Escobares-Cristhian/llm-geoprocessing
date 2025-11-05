def get_metadata_geoprocessing() -> str:
    print("Using DUMMY metadata geoprocessing instructions.")
    return (
        "- Geoprocessing Functions:\n"
        "    - open_s2_rgb_thumb(bbox: tuple, start: str, end: str, mask: bool, width: int) -> str: Download a thumbnail of Sentinel-2 RGB data from GEE.\n"
        "        - bbox: Bounding box defined as (xmin, ymin, xmax, ymax) in lon/lat coordinates.\n"
        "        - start: Start date in 'YYYY-MM-DD' format. Inclusive.\n"
        "        - end: End date in 'YYYY-MM-DD' format. Exclusive.\n"
        "        - mask: Boolean indicating whether to apply cloud masking.\n"
        "        - width: Width of the thumbnail image in pixels.\n"
    )

def get_documentation_geoprocessing() -> str:
    print("Using DUMMY documentation geoprocessing instructions.")
    return (
        "Geoprocessing Functions Documentation:\n"
        "- open_s2_rgb_thumb(bbox: tuple, start: str, end: str, mask: bool, width: int) -> str: Download a thumbnail of Sentinel-2 RGB data from GEE.\n"
        "    - Considerations:\n"
        "        - The function retrieves data from the 'COPERNICUS/S2_SR_HARMONIZED' collection in GEE.\n"
        "        - Cloud masking is performed using the Scene Classification Layer (SCL) if 'mask' is set to True.\n"
        "        - The resulting image is a median composite over the specified date range.\n"
        "        - The thumbnail is returned as a PNG image URL.\n"
        "        - Used to get instant visual images of areas of interest.\n"
        "General Notes:\n"
        "- Product IDs (e.g., 'A', 'B', etc.) refer to the products defined in the 'products' object of the JSON schema.\n"
        "- Ensure that the input parameters are valid and correspond to available data and capabilities.\n"
        "- Refer to 'Available Data and Preprocessing Options' for details on data products and preprocessing functions.\n"
        ""
        "Optimization notes:\n"
        "- None"
    )