"""The shell scripts are part of the product, so they get tested like code.

The bug this file exists for: ``scripts/run.sh`` ran a bare ``python3``. On a machine
set up the documented way (``./scripts/dev_setup.sh`` installs everything into
``.venv``) that picks the *system* interpreter, so the very first command a new
developer runs died with ``No module named uvicorn``. One shared chooser
(``scripts/python_bin.sh``) now answers "which Python" for every script, and these
tests keep it that way.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted((ROOT / "scripts").glob("*.sh"))
CHOOSER = ROOT / "scripts" / "python_bin.sh"

# Modules that only exist once this project's dependencies are installed. Running any
# of them with the wrong interpreter is the failure mode above; stdlib modules
# (json.tool, venv, …) work with any Python and need no chooser.
PROJECT_MODULES = ("uvicorn", "pytest", "ruff", "pip install")

needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def test_there_are_scripts_to_check():
    assert SCRIPTS, "scripts/*.sh disappeared"
    assert CHOOSER.exists(), "scripts/python_bin.sh is the single source of truth"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
@needs_bash
def test_every_script_is_syntactically_valid(script: Path):
    done = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert done.returncode == 0, f"{script.name}: {done.stderr.strip()}"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_every_script_is_executable(script: Path):
    if script.name == "python_bin.sh":
        pytest.skip("sourced, never executed directly")
    assert os.access(script, os.X_OK), f"chmod +x scripts/{script.name}"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_project_dependencies_are_never_run_with_a_bare_python3(script: Path):
    """`python3 -m uvicorn` is the bug; `"${PY}" -m uvicorn` is the fix."""
    offenders = []
    for number, line in enumerate(script.read_text().splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue  # a comment showing the user a copy-pasteable command is fine
        if "python3" not in stripped and "python " not in stripped:
            continue
        if any(named in stripped for named in ('${PY}', "${PYTHON", "$PYTHON", ".venv/bin/python")):
            continue  # already names the right interpreter (or prints it as advice)
        if any(module in stripped for module in PROJECT_MODULES):
            offenders.append(f"{script.name}:{number}: {stripped}")
    assert not offenders, (
        "these lines would use the system interpreter, which has no project "
        "dependencies — source scripts/python_bin.sh and use \"${PY}\":\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_scripts_that_need_python_use_the_shared_chooser(script: Path):
    body = script.read_text()
    if script.name in {"python_bin.sh", "dev_setup.sh", "build_ui.sh"}:
        pytest.skip("creates the venv itself, or runs no Python at all")
    if '"${PY}"' not in body:
        pytest.skip("runs no Python")
    assert "source scripts/python_bin.sh" in body, (
        f"scripts/{script.name} uses $PY without sourcing scripts/python_bin.sh"
    )


def _choose(cwd: Path, env: dict[str, str]) -> str:
    """Run the chooser in `cwd` and report the interpreter it settled on."""
    full = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **env}
    done = subprocess.run(
        ["bash", "-c", 'set -euo pipefail; source scripts/python_bin.sh; echo "${PY}"'],
        cwd=cwd, env=full, capture_output=True, text=True,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


@pytest.fixture()
def fake_repo(tmp_path: Path) -> Path:
    (tmp_path / "scripts").mkdir()
    shutil.copy(CHOOSER, tmp_path / "scripts" / "python_bin.sh")
    return tmp_path


@needs_bash
def test_the_repo_venv_wins_over_the_system_interpreter(fake_repo: Path):
    venv_python = fake_repo / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\nexec /usr/bin/env python3 \"$@\"\n")
    venv_python.chmod(0o755)

    assert _choose(fake_repo, {}) == ".venv/bin/python"


@needs_bash
def test_without_a_venv_it_falls_back_to_path(fake_repo: Path):
    assert _choose(fake_repo, {}) == "python3"


@needs_bash
def test_an_explicit_PYTHON_always_wins(fake_repo: Path):
    venv_python = fake_repo / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\nexit 0\n")
    venv_python.chmod(0o755)

    # CI, pyenv and conda set PYTHON; honouring it is what makes the same scripts
    # work where there is no .venv at all.
    assert _choose(fake_repo, {"PYTHON": sys.executable}) == sys.executable


@needs_bash
def test_an_activated_virtualenv_is_used_when_the_repo_has_none(fake_repo: Path):
    other = fake_repo / "elsewhere"
    (other / "bin").mkdir(parents=True)
    (other / "bin" / "python").write_text("#!/bin/sh\nexit 0\n")
    (other / "bin" / "python").chmod(0o755)

    assert _choose(fake_repo, {"VIRTUAL_ENV": str(other)}) == str(other / "bin" / "python")


@needs_bash
def test_run_sh_really_starts_with_the_venv_interpreter():
    """The exact command dev_setup.sh tells people to run, with a PATH that has no venv."""
    if not (ROOT / ".venv" / "bin" / "python").exists():
        pytest.skip("no .venv in this checkout (CI installs dependencies globally)")
    done = subprocess.run(
        ["bash", "-c", 'source scripts/python_bin.sh; "${PY}" -c "import uvicorn, fastapi; print(1)"'],
        cwd=ROOT, env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True,
    )
    assert done.returncode == 0, f"run.sh would fail the same way again: {done.stderr.strip()}"
    assert done.stdout.strip() == "1"
