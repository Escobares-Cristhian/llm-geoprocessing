from llm_geoprocessing.app.plugins.gee.preprocessing_plugin import get_metadata_preprocessing as _get_metadata_preprocessing
from llm_geoprocessing.app.plugins.gee.preprocessing_plugin import get_documentation_preprocessing as _get_documentation_preprocessing

def get_metadata_preprocessing() -> str:
    return _get_metadata_preprocessing()

def get_documentation_preprocessing() -> str:
    return _get_documentation_preprocessing()
