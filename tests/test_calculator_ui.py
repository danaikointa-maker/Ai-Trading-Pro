"""The calculator disclosure is accurate and stays read-only."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def test_calculator_ui_disclosure_and_read_only_scope():
    node = shutil.which("node")
    if not node:
        import pytest

        pytest.skip("node is not installed")
    root = Path(__file__).resolve().parents[1] / "apps" / "web-dashboard"
    result = subprocess.run(
        [node, str(root / "scripts" / "calculator-smoke.mjs")],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr or result.stdout
