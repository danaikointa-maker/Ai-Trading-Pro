#!/usr/bin/env bash
# Run the whole regression net (unit + API contract + formula invariants).
#
# For the full gate (lint + dashboard bundle + these tests) use ./scripts/dev_check.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/python_bin.sh
exec "${PY}" -m pytest tests/ -q "$@"
