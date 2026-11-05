#!/usr/bin/env bash
# Run the whole regression net (unit + API contract + formula invariants).
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 -m pytest tests/ -q "$@"
