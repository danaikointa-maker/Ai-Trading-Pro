# Pick the interpreter that actually has this project's dependencies.
#
#   source "$(dirname "$0")/python_bin.sh"    # sets $PY (and exports PYTHON)
#
# `./scripts/dev_setup.sh` installs everything into .venv, so a script that ran a
# bare `python3` picked the system interpreter instead and died with
# "No module named uvicorn" on a machine that was set up correctly. Order:
#
#   1. $PYTHON if the caller set one (CI, pyenv, conda, Windows py -3.11)
#   2. .venv/bin/python when the repo has a virtualenv
#   3. the active virtualenv ($VIRTUAL_ENV) if one is sourced
#   4. python3 from PATH
#
# Meant to be sourced from a script that already cd'ed to the repository root.
if [ -n "${PYTHON:-}" ]; then
  PY="${PYTHON}"
elif [ -x .venv/bin/python ]; then
  PY=".venv/bin/python"
elif [ -n "${VIRTUAL_ENV:-}" ] && [ -x "${VIRTUAL_ENV}/bin/python" ]; then
  PY="${VIRTUAL_ENV}/bin/python"
else
  PY="python3"
fi

if ! command -v "${PY}" >/dev/null 2>&1 && [ ! -x "${PY}" ]; then
  echo "error: no Python interpreter found (tried '${PY}') — run ./scripts/dev_setup.sh" >&2
  exit 1
fi
export PYTHON="${PY}"
