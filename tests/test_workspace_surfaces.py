"""P2.3 runtime-bound authorization and process-global job isolation."""
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from starlette.requests import Request
from fastapi.testclient import TestClient
import pytest

from services.api_gateway.auth import create_token
from services.api_gateway import deps
from services.api_gateway.routes import backtest, ws


def settings(workspace):
    return SimpleNamespace(security={"workspace_id": workspace, "require_auth": True,
                                     "jwt_secret": "workspace-surface-test-secret-32bytes"})


def runtime(workspace):
    return SimpleNamespace(db=SimpleNamespace(workspace_id=workspace, query_one=Mock(
        return_value={"email": "same@example.com", "role": "admin", "active": 1})),
        settings=settings(workspace))


def test_rest_refuses_runtime_workspace_mismatch_before_user_query(monkeypatch):
    config = settings("team-a")
    other = runtime("team-b")
    monkeypatch.setattr(deps, "get_settings", lambda: config)
    app = FastAPI()
    app.state.runtime = other

    @app.get("/private")
    def private(user=deps.User):
        return user

    token, _ = create_token(config, "same@example.com", "admin")
    with TestClient(app) as client:
        response = client.get("/private", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 503
    other.db.query_one.assert_not_called()


def test_websocket_refuses_runtime_workspace_mismatch_before_user_query():
    other = runtime("team-b")
    config = settings("team-a")
    token, _ = create_token(config, "same@example.com")
    authority, code = ws._authority(other, config, token)
    assert authority is None
    assert code == 1011
    other.db.query_one.assert_not_called()


def test_process_global_backtest_job_does_not_cross_workspace():
    # Worker records must include their workspace; same job id is not a grant.
    key = "P2-FOREIGN-JOB"
    backtest.JOBS[key] = {"workspace_id": "team-a", "state": "done", "report_id": "private"}
    try:
        with pytest.raises(Exception) as exc:
            backtest.job(key, runtime("team-b"), {"email": "same@example.com"})
        assert getattr(exc.value, "status_code", None) == 404
    finally:
        backtest.JOBS.pop(key, None)


def test_job_with_unknown_workspace_is_not_disclosed():
    key = "P2-LEGACY-JOB"
    backtest.JOBS[key] = {"state": "done", "report_id": "unknown-owner"}
    try:
        with pytest.raises(Exception) as exc:
            backtest.job(key, runtime("team-a"), {"email": "same@example.com"})
        assert getattr(exc.value, "status_code", None) == 404
    finally:
        backtest.JOBS.pop(key, None)


def test_same_workspace_can_read_workspace_owned_job():
    key = "P2-LOCAL-JOB"
    backtest.JOBS[key] = {"workspace_id": "team-a", "state": "done"}
    try:
        assert backtest.job(key, runtime("team-a"), {"email": "same@example.com"})["state"] == "done"
    finally:
        backtest.JOBS.pop(key, None)


def test_runtime_dependency_blocks_unauthenticated_routes_before_writes(monkeypatch):
    monkeypatch.setattr(deps, "get_settings", lambda: settings("team-a"))
    app = FastAPI()
    app.state.runtime = runtime("team-b")
    request = Request({"type": "http", "app": app})
    with pytest.raises(Exception) as exc:
        deps.get_runtime(request)
    assert getattr(exc.value, "status_code", None) == 503