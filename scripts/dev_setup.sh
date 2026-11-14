#!/usr/bin/env bash
# Bootstrap a working development environment with one command.
#
#   ./scripts/dev_setup.sh              # venv + deps + .env + dashboard bundle
#   ./scripts/dev_setup.sh --no-ui      # backend only (skip npm install/build)
#   ./scripts/dev_setup.sh --rebuild-ui # force a fresh dashboard build
#   PYTHON=python3.11 ./scripts/dev_setup.sh
#
# Safe to run again at any time: every step checks what already exists, so this is
# also the recovery command after a machine wipe (.venv / node_modules / dist are
# git-ignored and disappear with the sandbox, the repository does not).
set -euo pipefail
cd "$(dirname "$0")/.."

WITH_UI=1
REBUILD_UI=0
for arg in "$@"; do
  case "$arg" in
    --no-ui) WITH_UI=0 ;;
    --rebuild-ui) REBUILD_UI=1 ;;
    -h|--help) awk 'NR>1 && /^#/{sub(/^# ?/,"");print;next} NR>1{exit}' "$0"; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
ok() { printf '    \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$1"; }

PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "error: $PYTHON_BIN not found — install Python 3.11+ or set PYTHON=..." >&2
  exit 1
fi
"$PYTHON_BIN" - <<'PY' || exit 1
import sys
if sys.version_info < (3, 11):
    sys.exit(f"error: Python 3.11+ required, found {sys.version.split()[0]}")
PY

# ---------------------------------------------------------------- 1. virtualenv
step "Python environment (.venv)"
if [ ! -x .venv/bin/python ]; then
  "$PYTHON_BIN" -m venv .venv
  ok "created .venv ($("$PYTHON_BIN" -V))"
else
  ok "reusing .venv ($(.venv/bin/python -V))"
fi
VENV_PY=".venv/bin/python"

# ---------------------------------------------------------------- 2. dependencies
step "Dependencies (requirements-dev.txt = runtime + ruff + pyarrow + fakeredis)"
"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet -r requirements-dev.txt
ok "installed: $("$VENV_PY" -c 'import fastapi,pandas,sklearn;print("fastapi",fastapi.__version__,"| pandas",pandas.__version__,"| scikit-learn",sklearn.__version__)')"

# ---------------------------------------------------------------- 3. .env
step "Local configuration (.env)"
if [ ! -f .env ]; then
  cp .env.example .env
  SECRET="$("$VENV_PY" -c 'import secrets;print(secrets.token_urlsafe(48))')"
  "$VENV_PY" - "$SECRET" <<'PY'
import pathlib, sys
secret = sys.argv[1]
path = pathlib.Path(".env")
lines = path.read_text().splitlines()
out = [f"NO7_JWT_SECRET={secret}" if line.startswith("NO7_JWT_SECRET=") else line
       for line in lines]
path.write_text("\n".join(out) + "\n")
PY
  ok "created .env from .env.example with a fresh NO7_JWT_SECRET (never commit it)"
else
  if grep -qE '^NO7_JWT_SECRET=\s*$' .env; then
    warn ".env exists but NO7_JWT_SECRET is empty — tokens will not survive a restart"
    echo "      python3 -c \"import secrets;print(secrets.token_urlsafe(48))\""
  else
    ok ".env already exists (left untouched)"
  fi
fi

# ---------------------------------------------------------------- 4. dashboard
step "Dashboard bundle (apps/web-dashboard/dist)"
if [ "$WITH_UI" -eq 0 ]; then
  warn "skipped (--no-ui): the API serves a placeholder page at / and"
  echo "      tests/test_pwa.py::test_spa_deep_links_are_served will fail"
elif ! command -v npm >/dev/null 2>&1; then
  warn "npm not found — install Node 20+ to build the dashboard"
elif [ "$REBUILD_UI" -eq 1 ] || [ ! -f apps/web-dashboard/dist/index.html ]; then
  (cd apps/web-dashboard && [ -d node_modules ] || npm install --no-audit --no-fund)
  (cd apps/web-dashboard && npm run build)
  ok "built apps/web-dashboard/dist ($(find apps/web-dashboard/dist -type f | wc -l) files)"
else
  ok "dist/index.html already there (use --rebuild-ui to redo it)"
fi

# ---------------------------------------------------------------- 5. what next
step "Ready"
cat <<'NEXT'
    run the app      ./scripts/run.sh                 # http://127.0.0.1:8000
                                                      # demo@no7.ai / no7demo1234
    run the gate     ./scripts/dev_check.sh           # ruff + 564 tests (~2 min)
    fast test loop   .venv/bin/python -m pytest tests/test_api.py -q
    frontend loop    cd apps/web-dashboard && npm run dev      # :5173, proxies /api
    read first       docs/DEVELOPMENT.md              # where things live, recipes,
                                                      # traps, and what to build next
NEXT
