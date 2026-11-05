"""Shared fixtures.

Every test runs against a throwaway storage root so the developer database,
trained models and backtest reports are never touched.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="no7-tests-"))
os.environ.setdefault("NO7_DB_PATH", str(_TMP / "db" / "test.sqlite3"))
os.environ.setdefault("NO7_DATA_DIR", str(_TMP / "datasets"))
os.environ.setdefault("NO7_MODEL_DIR", str(_TMP / "models"))
os.environ.setdefault("NO7_BACKTEST_DIR", str(_TMP / "backtests"))
os.environ.setdefault("NO7_LOG_DIR", str(_TMP / "logs"))
os.environ.setdefault("NO7_FEED_MODE", "simulate")
os.environ.setdefault("NO7_JWT_SECRET", "test-secret-key-for-pytest-only-32bytes")
os.environ.setdefault("NO7_SIM_SPEED", "0")


@pytest.fixture(scope="session")
def settings():
    from packages.shared_schemas.settings import reload_settings

    s = reload_settings()
    assert "no7-tests-" in str(s.paths["database"]), "tests must not touch the real database"
    return s


@pytest.fixture(scope="session")
def runtime(settings):
    from services.api_gateway.state import TradingRuntime

    rt = TradingRuntime(settings)
    yield rt
    rt.stop()


@pytest.fixture(scope="session")
def client(runtime):
    from fastapi.testclient import TestClient

    from services.api_gateway.app import create_app

    app = create_app(runtime)
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def token(client):
    res = client.post("/api/auth/login", json={"email": "demo@no7.ai", "password": "no7demo1234"})
    assert res.status_code == 200, res.text
    return res.json()["token"]


@pytest.fixture(scope="session")
def auth(token):
    return {"Authorization": f"Bearer {token}"}
