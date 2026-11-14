"""Run the real Vue store/SFC using the installed Vite and Vue toolchain."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_position_disclosure_ui():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    root = Path(__file__).resolve().parents[1] / "apps" / "web-dashboard"
    result = subprocess.run([node, str(root / "scripts" / "positions-smoke.mjs")],
                            cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=90)
    assert result.returncode == 0, result.stderr or result.stdout
    assert "unknown, owned empty, stale and unavailable states all behave" in result.stdout