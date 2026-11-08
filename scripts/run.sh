#!/usr/bin/env bash
# Start the whole app (API + dashboard) on port 8000.
#
# HTTPS is either terminated here or by a reverse proxy in front:
#
#   # 1) terminate TLS in uvicorn (self-signed for a LAN box):
#   NO7_TLS_CERT=certs/dev.crt NO7_TLS_KEY=certs/dev.key scripts/run.sh
#
#   # 2) put nginx/caddy in front (recommended) and tell the app which peers are
#   #    proxies, so the client IP and "was this HTTPS" come from the proxy:
#   NO7_TRUSTED_PROXIES=127.0.0.1/32,::1/128 scripts/run.sh
#
set -euo pipefail
cd "$(dirname "$0")/.."
# .venv first: dev_setup.sh installs the dependencies there, and a bare `python3`
# would be the system interpreter that has no uvicorn.
source scripts/python_bin.sh
PORT="${NO7_PORT:-8000}"
if [ ! -f apps/web-dashboard/dist/index.html ]; then
  echo "dashboard bundle missing -> building it once"
  ./scripts/build_ui.sh
fi

# uvicorn would otherwise apply its own --forwarded-allow-ips (default: loopback),
# rewriting the client address and scheme before the app can apply its policy. Two
# places deciding who the client is meant the stricter config could be bypassed, so
# the app owns that decision (services/api_gateway/netutil.py) and uvicorn does not.
ARGS=(--host 0.0.0.0 --port "${PORT}" --no-proxy-headers)
SCHEME="http"
if [ -n "${NO7_TLS_CERT:-}" ] || [ -n "${NO7_TLS_KEY:-}" ]; then
  if [ -z "${NO7_TLS_CERT:-}" ] || [ -z "${NO7_TLS_KEY:-}" ]; then
    echo "error: set both NO7_TLS_CERT and NO7_TLS_KEY, or neither" >&2
    exit 1
  fi
  ARGS+=(--ssl-certfile "${NO7_TLS_CERT}" --ssl-keyfile "${NO7_TLS_KEY}")
  SCHEME="https"
fi

echo "starting No7 AI Trading Pro on ${SCHEME}://127.0.0.1:${PORT} (login demo@no7.ai / no7demo1234)"
echo "perimeter: cors=[${NO7_CORS_ORIGINS:-}] trusted_proxies=[${NO7_TRUSTED_PROXIES:-127.0.0.1/32,::1/128}] csp=${NO7_CSP_MODE:-enforce}"
echo "python: ${PY}"
exec "${PY}" -m uvicorn services.api_gateway.app:app "${ARGS[@]}"
