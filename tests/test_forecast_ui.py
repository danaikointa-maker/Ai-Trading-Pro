"""Run forecast disclosure checks against the actual Vue store."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_forecast_cache_ui():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    root = Path(__file__).resolve().parents[1] / 'apps/web-dashboard'
    result = subprocess.run([node, str(root / 'scripts/forecast-cache-smoke.mjs')],
                            cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=90)
    assert result.returncode == 0, result.stderr or result.stdout
    assert 'null, revocation, version and symbol changes are enforced' in result.stdout