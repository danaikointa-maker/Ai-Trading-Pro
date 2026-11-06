"""Rate limiting must stop abuse without touching normal use.

The bucket is unit-tested with a fake clock, and the middleware with a throwaway
ASGI app, so no real order is ever sent to prove a limit works.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api_gateway.ratelimit import RateLimiter, RateLimitMiddleware


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# --------------------------------------------------------------------- buckets
def test_burst_of_limit_is_allowed_then_blocked():
    clock = Clock()
    limiter = RateLimiter({"default": {"limit": 3, "window_seconds": 60}}, clock=clock)

    assert [limiter.check("ip:1.2.3.4", "default")[0] for _ in range(3)] == [True, True, True]
    allowed, remaining, retry = limiter.check("ip:1.2.3.4", "default")
    assert allowed is False
    assert remaining == 0
    assert 1.0 <= retry <= 60.0


def test_budget_refills_over_time():
    clock = Clock()
    limiter = RateLimiter({"default": {"limit": 2, "window_seconds": 60}}, clock=clock)
    assert limiter.check("u", "default")[0]
    assert limiter.check("u", "default")[0]
    assert not limiter.check("u", "default")[0]

    clock.advance(30)  # half the window -> one token back (rate = 2/60)
    assert limiter.check("u", "default")[0]
    assert not limiter.check("u", "default")[0]

    clock.advance(60)  # fully refilled, capped at the limit
    assert all(limiter.check("u", "default")[0] for _ in range(2))


def test_identities_do_not_share_a_budget():
    limiter = RateLimiter({"order": {"limit": 1, "window_seconds": 60}}, clock=Clock())
    assert limiter.check("user:a", "order")[0]
    assert not limiter.check("user:a", "order")[0]
    assert limiter.check("user:b", "order")[0]


def test_rules_follow_the_route():
    assert RateLimiter.rule_for("/api/trading/order", "POST") == "order"
    assert RateLimiter.rule_for("/api/trading/close-all", "POST") == "order"
    assert RateLimiter.rule_for("/api/explain", "POST") == "explain"
    assert RateLimiter.rule_for("/api/backtests", "POST") == "backtest"
    assert RateLimiter.rule_for("/api/forecast/train", "POST") == "train"
    # A GET never spends the order budget, and unknown paths fall through.
    assert RateLimiter.rule_for("/api/trading/order", "GET") == "default"
    assert RateLimiter.rule_for("/api/system/config", "GET") == "default"


def test_rule_table_is_capped():
    limiter = RateLimiter({"default": {"limit": 1000, "window_seconds": 60}},
                          clock=Clock(), max_keys=10)
    for i in range(50):
        limiter.check(f"ip:{i}", "default")
    assert limiter.tracked <= 10


# ------------------------------------------------------------------ middleware
def _app(limit: int) -> FastAPI:
    app = FastAPI()
    # Override every rule the test paths can hit, so the numbers are the test's
    # and not whatever config/app.yaml currently ships.
    rules = {name: {"limit": limit, "window_seconds": 60}
             for name in ("order", "explain", "backtest", "train", "default")}
    app.add_middleware(RateLimitMiddleware, limiter=RateLimiter(rules), settings=None)

    @app.post("/api/trading/order")
    def order():  # pragma: no cover - body is irrelevant to the limiter
        return {"ok": True}

    @app.get("/api/system/health")
    def health():  # pragma: no cover
        return {"status": "ok"}

    return app


def test_middleware_returns_429_with_retry_after():
    client = TestClient(_app(limit=2))
    assert client.post("/api/trading/order").status_code == 200
    assert client.post("/api/trading/order").status_code == 200
    blocked = client.post("/api/trading/order")
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
    assert blocked.json()["rule"] == "order"


def test_middleware_reports_remaining_tokens():
    client = TestClient(_app(limit=3))
    first = client.post("/api/trading/order")
    assert first.headers["x-ratelimit-remaining"] == "2"


def test_health_probes_are_never_rate_limited():
    client = TestClient(_app(limit=2))
    assert all(client.get("/api/system/health").status_code == 200 for _ in range(20))


# --------------------------------------------------------- the real application
def test_real_api_allows_normal_dashboard_traffic(runtime):
    """Polling the state endpoints must not be throttled for a real session."""
    app = __import__("services.api_gateway.app", fromlist=["create_app"]).create_app(runtime)
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"email": "demo@no7.ai", "password": "no7demo1234"})
        assert login.status_code == 200
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        for _ in range(40):
            assert client.get("/api/system/health").status_code == 200
            assert client.get("/api/trading/state", headers=headers).status_code == 200
        assert app.state.ratelimit.tracked >= 0
