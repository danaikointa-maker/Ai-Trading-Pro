from __future__ import annotations

import io
import json

from scripts.check_mt5_market_runtime import inspect_runtime


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False


def _opener(health, schema):
    payloads = iter((health, schema))

    def open_url(url, timeout):
        assert timeout == 4
        assert url.endswith(("/api/system/health", "/api/openapi.json"))
        return Response(json.dumps(next(payloads)).encode())

    return open_url


def test_runtime_preflight_reports_simulation_and_missing_route():
    report = inspect_runtime("http://127.0.0.1:18080", _opener(
        {"status": "ok", "feed_mode": "simulate", "feed": {"mode": "simulate"}},
        {"paths": {"/api/bridge/poll": {"post": {}}}},
    ))
    assert report["ready"] is False
    assert report["feed_mode"] == "simulate"
    assert report["checks"] == {
        "health_api": True, "publisher_route": False, "publisher_fresh": False,
    }


def test_runtime_preflight_requires_route_and_fresh_mt5_publisher():
    report = inspect_runtime("https://api.example.test", _opener(
        {"status": "ok", "feed_mode": "mt5_demo_publisher",
         "feed": {"fresh": True}},
        {"paths": {"/api/market/publish/mt5": {"post": {}}}},
    ))
    assert report["ready"] is True


def test_runtime_preflight_fails_closed_when_health_api_unreachable():
    def offline(_url, timeout):
        raise OSError("offline")

    report = inspect_runtime("http://127.0.0.1:18080", offline)
    assert report["ready"] is False
    assert report["checks"]["health_api"] is False
    assert "error" in report
