#!/usr/bin/env python3
"""
Run a previously generated geoprocess JSON without starting the whole program.

Usage:
  python -m llm_geoprocessing.app.cli.run_geoprocess_json --file /path/to/instructions.json

Optional env vars:
  GEE_PLUGIN_URL         Base URL for the GEE microservice (default: http://gee:8000)
  ACTIVE_PLUGIN_EXECUTOR Python module with execute_geoprocess(name, params) for a custom plugin
"""

import os
import json
import argparse
from llm_geoprocessing.app.llm.geoprocess_agent import geoprocess

from llm_geoprocessing.app.logging_config import get_logger
logger = get_logger("geollm")

def main() -> int:
    ap = argparse.ArgumentParser(description="Execute geoprocess(json_instructions) from a JSON file.")
    ap.add_argument("--file", required=True, help="Path to JSON file with the final instructions.")
    args = ap.parse_args()

    with open(args.file, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = geoprocess(data)
    logger.info(f"Geoprocess result: {result}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
