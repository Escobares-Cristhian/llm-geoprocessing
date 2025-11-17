from llm_geoprocessing.app.logging_config import get_logger
logger = get_logger("geollm")

def get_metadata_geoprocessing() -> str:
    logger.info("Using DUMMY metadata geoprocessing instructions.")
    return (
        "- Geoprocessing Functions:\n"
        "    - cut_by_vector(product_id: str, area_of_interest: dict) -> str: Cuts out the specified area from the product.\n"
        "        - product_id: Identifier of the satellite product (e.g., 'A', 'B', etc.).\n"
        "        - area_of_interest: Path to the vector file defining the area of interest. Could be a GeoJSON, Geopackage, or Shapefile.\n"
        "    - cut_by_bbox(product_id: str, bbox: list, geodesic: bool) -> str: Cuts out the specified bounding box from the product.\n"
        "        - product_id: Identifier of the satellite product (e.g., 'A', 'B', etc.).\n"
        "        - bbox: List of coordinates [min_lon, min_lat, max_lon, max_lat].\n"
        "        - geodesic: Boolean indicating whether to use geodesic calculations.\n"
        "    - cut_by_vector_item(product_id: str, vector_path: str, item_id: str) -> str: Cuts out the area defined by a specific item in the vector file from the product.\n"
        "        - product_id: Identifier of the satellite product (e.g., 'A', 'B', etc.).\n"
        "        - vector_path: Path to the vector file (GeoJSON, Geopackage, or Shapefile).\n"
        "        - item_id: Identifier of the specific item in the vector file.\n"
        "    - calculate_normalized_difference(product_id1: str, product_id2: str) -> str: Calculates the normalized difference between two products.\n"
        "        - product_id1: Identifier of the first satellite product (e.g., 'A', 'B', etc.).\n"
        "        - product_id2: Identifier of the second satellite product (e.g., 'A', 'B', etc.).\n"
        "    - reducer_date(product_id: str, method: str, date_initial: str, date_end: str) -> str: Reduces the product over a date range using the specified method.\n"
        "        - product_id: Identifier of the satellite product (e.g., 'A', 'B', etc.).\n"
        "        - method: Reduction method (e.g., 'mean', 'max', 'min').\n"
        "        - date_initial: Start date in 'YYYY-MM-DD' format.\n"
        "        - date_end: End date in 'YYYY-MM-DD' format.\n"
        "    - reducer_space(product_id: str, method: str, scale: float) -> str: Reduces the product spatially using the specified method and scale.\n"
        "        - product_id: Identifier of the satellite product (e.g., 'A', 'B', etc.).\n"
        "        - method: Reduction method (e.g., 'mean', 'max', 'min').\n"
        "        - scale: Scale in meters for the spatial reduction.\n"
    )

def get_documentation_geoprocessing() -> str:
    logger.info("Using DUMMY documentation geoprocessing instructions.")
    return (
        "Geoprocessing Functions Documentation:\n"
        "- cut_by_vector(product_id: str, area_of_interest: dict) -> str: Cuts out the specified area from the product.\n"
        "- cut_by_bbox(product_id: str, bbox: list, geodesic: bool) -> str: Cuts out the specified bounding box from the product.\n"
        "- cut_by_vector_item(product_id: str, vector_path: str, item_id: str) -> str: Cuts out the area defined by a specific item in the vector file from the product.\n"
        "- calculate_normalized_difference(product_id1: str, product_id2: str) -> str: Calculates the normalized difference between two products, must have same resolution and projection.\n"
        "- reducer_date(product_id: str, method: str, date_initial: str, date_end: str) -> str: Reduces the product over a date range using the specified method.\n"
        "- reducer_space(product_id: str, method: str, scale: float) -> str: Reduces the product spatially using the specified method and scale.\n"
        ""
        "General Notes:\n"
        "- Product IDs (e.g., 'A', 'B', etc.) refer to the products defined in the 'products' object of the JSON schema.\n"
        "- Ensure that the input parameters are valid and correspond to available data and capabilities.\n"
        "- Refer to 'Available Data and Preprocessing Options' for details on data products and preprocessing functions.\n"
        ""
        "Optimization notes:\n"
        "- If in some part of the geoprocessing is involved some cutting operation, then the cutting should be done as first step on all involved products."
    )