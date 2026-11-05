#!/usr/bin/env bash
# Start the whole app (API + dashboard) on port 8000.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${NO7_PORT:-8000}"
if [ ! -f apps/web-dashboard/dist/index.html ]; then
  echo "dashboard bundle missing -> building it once"
  ./scripts/build_ui.sh
fi
echo "starting No7 AI Trading Pro on http://127.0.0.1:${PORT} (login demo@no7.ai / no7demo1234)"
exec python3 -m uvicorn services.api_gateway.app:app --host 0.0.0.0 --port "${PORT}"
