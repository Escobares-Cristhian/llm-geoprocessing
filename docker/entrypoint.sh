#!/usr/bin/env bash
set -euo pipefail
# Ensure editable install stays in sync (cheap no-op if unchanged)
pip install -e . >/dev/null 2>&1 || true
exec "$@"

