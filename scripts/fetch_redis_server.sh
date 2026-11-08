#!/usr/bin/env bash
# Put a real `redis-server` binary on this machine without root and without a build.
#
#   ./scripts/fetch_redis_server.sh            # -> .tools/bin/redis-server (+ redis-cli)
#   NO7_REDIS_BIN_DIR=/tmp/no7tools ./scripts/fetch_redis_server.sh
#
# Why: the shared rate-limit store and the cluster frame bus can run on Redis, and a
# claim about Redis is only worth something when it was proved against the real server
# (fakeredis runs the same Lua, but it is still a reimplementation). Most sandboxes and
# CI images have no redis-server and no way to apt-get one, so this pulls the binary
# that the `redislite` wheel ships — an unmodified upstream build — and unpacks it.
#
# The binary is deliberately NOT committed: .tools/ is git-ignored, re-run this after a
# machine wipe.
set -euo pipefail
cd "$(dirname "$0")/.."

BIN_DIR="${NO7_REDIS_BIN_DIR:-.tools/bin}"
if [ -x "${BIN_DIR}/redis-server" ]; then
  echo "already there: ${BIN_DIR}/redis-server ($("${BIN_DIR}/redis-server" --version | cut -d' ' -f1-3))"
  exit 0
fi

source scripts/python_bin.sh
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

echo "downloading the redislite wheel (it carries a prebuilt redis-server)…"
"$PY" -m pip download redislite --no-deps --quiet --dest "${WORK}"
WHEEL="$(ls "${WORK}"/redislite-*.whl 2>/dev/null | head -1)"
[ -n "${WHEEL}" ] || { echo "error: no redislite wheel for this platform" >&2; exit 1; }

"$PY" - "${WHEEL}" "${WORK}/x" <<'PY'
import sys, zipfile
zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])
PY

mkdir -p "${BIN_DIR}"
found=0
for name in redis-server redis-cli; do
  src="$(find "${WORK}/x" -type f -name "${name}" | head -1)"
  if [ -n "${src}" ]; then
    install -m 0755 "${src}" "${BIN_DIR}/${name}"
    echo "  ${BIN_DIR}/${name}  ($(( $(stat -c%s "${BIN_DIR}/${name}") / 1024 )) KiB)"
    found=$((found + 1))
  fi
done
[ "${found}" -gt 0 ] || { echo "error: the wheel contained no redis binaries" >&2; exit 1; }

echo
echo "version: $("${BIN_DIR}/redis-server" --version | cut -d' ' -f1-3)"
cat <<NEXT

next — run the platform against the real thing:
  ${BIN_DIR}/redis-server --port 6379 --save '' --appendonly no &
  NO7_RATELIMIT_STORE=redis NO7_CLUSTER_BACKEND=redis \\
    NO7_REDIS_URL=redis://127.0.0.1:6379/0 ./scripts/run.sh
  curl -s localhost:8000/api/system/health | python3 -m json.tool | grep -A4 ratelimit
NEXT
