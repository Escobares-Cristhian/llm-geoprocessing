#!/usr/bin/env bash

set -u

# Directory where this script lives (tests/gee_plugins_json_tests)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Repo root (two levels up from tests/gee_plugins_json_tests)
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

TEST_DIR="${SCRIPT_DIR}"
LOG_FILE="${TEST_DIR}/gee_plugins_json_tests.log"

# Build images and start gee service
(
  cd "$ROOT_DIR" || exit 1
  docker compose -f docker/compose.dev.yaml build gee maie-dev
  docker compose -f docker/compose.dev.yaml up -d gee
)

# Start with a clean log file
: > "$LOG_FILE"

shopt -s nullglob
json_files=("${TEST_DIR}"/*.json)

if [ ${#json_files[@]} -eq 0 ]; then
  echo "No JSON instruction files found in ${TEST_DIR}" | tee -a "$LOG_FILE"
  exit 1
fi

for json in "${json_files[@]}"; do
  # Path to use inside the container (relative to repo root)
  rel_json="${json#"${ROOT_DIR}/"}"
  if [[ "$rel_json" == "$json" ]]; then
    # Fallback, should not normally happen
    rel_json="$(basename "$json")"
  fi

  echo "=== Running ${rel_json} ===" | tee -a "$LOG_FILE"

  # Run docker compose from repo root and capture all output
  docker_output=$(
    cd "$ROOT_DIR" || exit 1
    docker compose -f docker/compose.dev.yaml run --rm maie-dev \
      python -m llm_geoprocessing.app.dev_tests.run_geoprocess_json \
      --file "$rel_json" 2>&1
  )
  exit_code=$?

  # Append run output to log
  printf '%s\n' "$docker_output" >> "$LOG_FILE"

  # Consider it failed if:
  #  - exit code != 0, OR
  #  - we see "Action '... ' failed" in the output
  if [ $exit_code -ne 0 ] || grep -q "Action '.*' failed" <<< "$docker_output"; then
    echo "=== FAILED: ${rel_json} ===" | tee -a "$LOG_FILE"
    echo "=== Last 100 lines of 'gee' logs ===" | tee -a "$LOG_FILE"
    (
      cd "$ROOT_DIR" || exit 1
      docker compose -f docker/compose.dev.yaml logs --no-log-prefix gee | tail -n 100
    ) >> "$LOG_FILE" 2>&1
    exit 1
  else
    echo "=== OK: ${rel_json} ===" | tee -a "$LOG_FILE"
  fi

  echo "" | tee -a "$LOG_FILE"
done

echo "All JSON tests completed successfully." | tee -a "$LOG_FILE"

