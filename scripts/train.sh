#!/usr/bin/env bash
# Retrain the forecast model for one symbol through the running API.
#
#   TOKEN=$(curl -s -X POST localhost:8000/api/auth/login \
#     -H 'Content-Type: application/json' \
#     -d '{"email":"demo@no7.ai","password":"no7demo1234"}' \
#     | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
#   TOKEN=$TOKEN ./scripts/train.sh XAUUSD
set -euo pipefail
SYMBOL="${1:-XAUUSD}"
BASE="${NO7_BASE:-http://127.0.0.1:8000}"
if [ -z "${TOKEN:-}" ]; then
  echo "set TOKEN to a logged-in bearer token (see the comment at the top of this file)" >&2
  exit 2
fi
curl -s -X POST "${BASE}/api/forecast/train" \
  -H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json' \
  -d "{\"symbol\":\"${SYMBOL}\"}" | python3 -m json.tool
