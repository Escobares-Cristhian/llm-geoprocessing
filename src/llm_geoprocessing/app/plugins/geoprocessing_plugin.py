from llm_geoprocessing.app.plugins.gee.geoprocessing_plugin import get_metadata_geoprocessing as _get_metadata_geoprocessing
from llm_geoprocessing.app.plugins.gee.geoprocessing_plugin import get_documentation_geoprocessing as _get_documentation_geoprocessing

def get_metadata_geoprocessing() -> str:
    return _get_metadata_geoprocessing()

def get_documentation_geoprocessing() -> str:
    return _get_documentation_geoprocessing()
