from __future__ import annotations
from typing import Dict, Any

from llm_geoprocessing.app.plugins.gee.runtime_executor import execute_action as gee_execute_action

# Wrapper for gee_execute_action called execute_action.
def execute_action(geoprocess_name: str, input_json: Dict[str, Any]) -> Dict[str, Any]:
    return gee_execute_action(geoprocess_name, input_json)