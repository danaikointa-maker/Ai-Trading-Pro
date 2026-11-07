"""Rate limiting must stop abuse without touching normal use.

The bucket is unit-tested with a fake clock, and the middleware with a throwaway
ASGI app, so no real order is ever sent to prove a limit works.
"""
from __future__ import annotations

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


# ------------------------------------------------------- shared store (workers)
def test_memory_stores_do_not_share_budgets():
    """The default: two workers each get their own full budget (documented limit)."""
    rules = {"default": {"limit": 1, "window_seconds": 60}}
    a = RateLimiter(rules, clock=Clock())
    b = RateLimiter(rules, clock=Clock())
    assert a.check("ip:1.1.1.1", "default")[0] is True
    assert b.check("ip:1.1.1.1", "default")[0] is True, "memory stores are per process by design"


def test_sqlite_store_is_shared_between_limiter_instances(tmp_path):
    """Two limiters over one file behave like two workers over one budget."""
    from services.api_gateway.ratelimit import SqliteBucketStore

    path = tmp_path / "ratelimit.sqlite3"
    rules = {"default": {"limit": 3, "window_seconds": 60}}
    clock = Clock()
    worker_a = RateLimiter(rules, clock=clock, store=SqliteBucketStore(path))
    worker_b = RateLimiter(rules, clock=clock, store=SqliteBucketStore(path))

    allowed = [worker_a.check("user:x", "default")[0],
               worker_b.check("user:x", "default")[0],
               worker_a.check("user:x", "default")[0]]
    assert allowed == [True, True, True]
    # the fourth request is refused no matter which worker takes it
    assert worker_b.check("user:x", "default")[0] is False
    assert worker_a.check("user:x", "default")[0] is False


def test_sqlite_store_survives_a_restart(tmp_path):
    from services.api_gateway.ratelimit import SqliteBucketStore

    path = tmp_path / "ratelimit.sqlite3"
    rules = {"default": {"limit": 2, "window_seconds": 60}}
    clock = Clock()
    first = RateLimiter(rules, clock=clock, store=SqliteBucketStore(path))
    assert first.check("ip:9.9.9.9", "default")[0] is True
    first.store.close()

    second = RateLimiter(rules, clock=clock, store=SqliteBucketStore(path))
    assert second.tracked == 1, "buckets must be on disk, not in the old process"
    assert second.check("ip:9.9.9.9", "default")[0] is True   # second of two tokens
    assert second.check("ip:9.9.9.9", "default")[0] is False  # budget spent across the restart


def test_sqlite_store_refills_on_the_shared_clock(tmp_path):
    from services.api_gateway.ratelimit import SqliteBucketStore

    rules = {"default": {"limit": 2, "window_seconds": 60}}
    clock = Clock()
    a = RateLimiter(rules, clock=clock, store=SqliteBucketStore(tmp_path / "rl.sqlite3"))
    b = RateLimiter(rules, clock=clock, store=SqliteBucketStore(tmp_path / "rl.sqlite3"))
    assert a.check("ip:r", "default")[0] is True
    assert b.check("ip:r", "default")[0] is True
    assert a.check("ip:r", "default")[0] is False
    clock.advance(30)   # half the window -> one token back (2 per 60s)
    assert b.check("ip:r", "default")[0] is True
    assert a.check("ip:r", "default")[0] is False


def test_sqlite_store_never_hands_out_more_than_the_limit(tmp_path):
    """Concurrent spends must be serialised: no double-spend of the same token."""
    from concurrent.futures import ThreadPoolExecutor

    from services.api_gateway.ratelimit import SqliteBucketStore

    rules = {"default": {"limit": 10, "window_seconds": 60}}
    clock = Clock()
    limiters = [RateLimiter(rules, clock=clock, store=SqliteBucketStore(tmp_path / "rl.sqlite3"))
                for _ in range(3)]

    def attempt(i: int) -> bool:
        return limiters[i % len(limiters)].check("ip:race", "default")[0]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(40)))
    assert sum(results) == 10, f"expected exactly the limit, got {sum(results)}"


def test_make_store_rejects_unknown_kinds_loudly(tmp_path):
    import pytest as _pytest

    from services.api_gateway.ratelimit import MemoryBucketStore, make_store

    assert isinstance(make_store(None), MemoryBucketStore)
    assert isinstance(make_store("memory"), MemoryBucketStore)
    with _pytest.raises(ValueError):
        make_store("redis")           # not implemented: refuses instead of pretending
    with _pytest.raises(ValueError):
        make_store("sqlite")          # needs a path


def test_app_builds_the_configured_store(runtime, monkeypatch, tmp_path):
    """`ratelimit.store: sqlite` in config must reach the limiter the app serves."""
    from packages.shared_schemas.settings import get_settings
    from services.api_gateway import app as app_module
    from services.api_gateway.ratelimit import SqliteBucketStore

    settings = get_settings()
    cfg = {**settings.app.get("ratelimit", {}), "store": "sqlite",
           "store_path": str(tmp_path / "rl.sqlite3")}
    monkeypatch.setitem(settings.app, "ratelimit", cfg)

    app = app_module.create_app(runtime)
    store = app.state.ratelimit.store
    assert isinstance(store, SqliteBucketStore)
    assert store.path == tmp_path / "rl.sqlite3"
    store.close()
