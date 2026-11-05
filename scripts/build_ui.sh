#!/usr/bin/env bash
# Build the Vue dashboard into apps/web-dashboard/dist (served by FastAPI at /).
set -euo pipefail
cd "$(dirname "$0")/../apps/web-dashboard"
[ -d node_modules ] || npm install --no-audit --no-fund
npm run build
echo "built -> apps/web-dashboard/dist"
