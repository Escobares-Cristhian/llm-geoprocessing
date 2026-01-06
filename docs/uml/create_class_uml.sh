mkdir -p docs/uml

PYTHONPATH=src python3 -c "import llm_geoprocessing; print(llm_geoprocessing.__file__)"
PYTHONPATH=src python3 -c "import cli; print(cli.__file__)"
export PYTHONPATH=src

pyreverse --verbose --source-roots src --max-depth 50 \
  -o puml -d docs/uml -p llm_geoprocessing -A -S -m y \
  --ignore=tests,docs,docker,secrets,utils,tmp,gee_out \
  llm_geoprocessing cli

