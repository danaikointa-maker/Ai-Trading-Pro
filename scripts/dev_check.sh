#!/usr/bin/env bash
# The gate every change has to pass before it is committed or opened as a PR.
#
#   ./scripts/dev_check.sh                      # lint + bundle check + all tests
#   ./scripts/dev_check.sh --lint-only          # just ruff (seconds)
#   ./scripts/dev_check.sh tests/test_api.py    # lint + that file only
#
# Stages, in the order a mistake is cheapest to find:
#   1. ruff check --select F,E9 .   undefined names, unused imports, syntax errors
#   2. dashboard bundle present     tests/test_pwa.py serves real files from dist/
#   3. pytest                       maths, risk gate, HTTP contract, invariants
set -euo pipefail
cd "$(dirname "$0")/.."

LINT_ONLY=0
PYTEST_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --lint-only) LINT_ONLY=1 ;;
    -h|--help) awk 'NR>1 && /^#/{sub(/^# ?/,"");print;next} NR>1{exit}' "$0"; exit 0 ;;
    *) PYTEST_ARGS+=("$arg") ;;
  esac
done

if [ -x .venv/bin/python ]; then PY=".venv/bin/python"; else PY="python3"; fi
step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
fail() { printf '\n\033[31m✗ %s\033[0m\n' "$1"; exit 1; }

START=$SECONDS

step "1/3 ruff (F = bugs, E9 = syntax)"
if ! "$PY" -m ruff --version >/dev/null 2>&1; then
  fail "ruff is missing — run ./scripts/dev_setup.sh (it is in requirements-dev.txt)"
fi
"$PY" -m ruff check --select F,E9 . || fail "lint failed"
printf '    clean\n'

if [ "$LINT_ONLY" -eq 1 ]; then
  printf '\n\033[32m✓ lint only — %ss\033[0m\n' "$((SECONDS - START))"
  exit 0
fi

step "2/3 dashboard bundle"
if [ -f apps/web-dashboard/dist/index.html ]; then
  printf '    apps/web-dashboard/dist/index.html present\n'
else
  printf '    missing -> building it once (npm run build)\n'
  ./scripts/build_ui.sh || fail "dashboard build failed (tests/test_pwa.py needs dist/)"
fi

step "3/3 pytest"
"$PY" -m pytest -q "${PYTEST_ARGS[@]}" || fail "tests failed"

printf '\n\033[32m✓ all gates passed in %ss\033[0m\n' "$((SECONDS - START))"
