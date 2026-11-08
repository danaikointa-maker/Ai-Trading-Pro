"""A live socket is one request that keeps costing CPU, so it gets a concurrency cap.

The cap has to survive three awkward realities, and each one is pinned here:

* a worker can be SIGKILLed mid-stream, so slots are leases that expire rather than
  counters someone has to remember to decrement;
* several workers (or hosts) must share one budget, so every backend is tested
  against the same contract;
* the shared store can fail, and when it does the socket must stay up while health
  admits the cap went local.
"""
from __future__ import annotations

import json
import time

import pytest

from services.api_gateway.wsquota import (GLOBAL_KEY, Lease, MemoryLeaseStore,
                                          SqliteLeaseStore, WebSocketQuota,
                                          build_lease_store)

fakeredis = pytest.importorskip("fakeredis", reason="fakeredis runs the real Lua")


def memory_store():
    return MemoryLeaseStore()


def sqlite_store(tmp_path):
    return SqliteLeaseStore(tmp_path / "ws.sqlite3")


def redis_store(_tmp_path):
    from services.api_gateway.wsquota import RedisLeaseStore

    return RedisLeaseStore(fakeredis.FakeStrictRedis(decode_responses=True),
                           prefix=f"no7:test:{time.time_ns()}")


ALL_STORES = [memory_store, sqlite_store, redis_store]


@pytest.fixture(params=ALL_STORES, ids=["memory", "sqlite", "redis"])
def store(request, tmp_path):
    factory = request.param
    return factory() if factory is memory_store else factory(tmp_path)


# ------------------------------------------------------------ the shared contract
def test_a_store_hands_out_exactly_the_limit(store):
    now = time.time()
    granted = [store.acquire("user:a", f"t{i}", 3, 0, 30.0, now)[0] for i in range(5)]
    assert granted == [True, True, True, False, False]
    held, total = store.counts("user:a", now)
    assert held == 3 and total == 3


def test_identities_do_not_share_each_others_slots(store):
    now = time.time()
    assert store.acquire("user:a", "t1", 1, 0, 30.0, now)[0] is True
    assert store.acquire("user:a", "t2", 1, 0, 30.0, now)[0] is False
    assert store.acquire("user:b", "t3", 1, 0, 30.0, now)[0] is True


def test_the_total_cap_binds_across_identities(store):
    now = time.time()
    assert store.acquire("user:a", "t1", 5, 2, 30.0, now)[0] is True
    assert store.acquire("user:b", "t2", 5, 2, 30.0, now)[0] is True
    assert store.acquire("user:c", "t3", 5, 2, 30.0, now)[0] is False, "total cap must bind"


def test_releasing_frees_the_slot_immediately(store):
    now = time.time()
    store.acquire("user:a", "t1", 1, 0, 30.0, now)
    assert store.acquire("user:a", "t2", 1, 0, 30.0, now)[0] is False
    store.release("user:a", "t1")
    assert store.acquire("user:a", "t2", 1, 0, 30.0, now)[0] is True


def test_a_lease_nobody_releases_expires(store):
    """The SIGKILL case: no decrement ever runs, so time has to do it."""
    now = time.time()
    store.acquire("user:a", "dead-worker", 1, 0, 10.0, now)
    assert store.acquire("user:a", "new", 1, 0, 10.0, now)[0] is False
    later = now + 11.0
    assert store.acquire("user:a", "new", 1, 0, 10.0, later)[0] is True
    held, _ = store.counts("user:a", later)
    assert held == 1, "the dead worker's slot is gone, not merely ignored"


def test_renew_keeps_a_slot_and_cannot_resurrect_a_dead_one(store):
    now = time.time()
    store.acquire("user:a", "t1", 2, 0, 10.0, now)
    assert store.renew("user:a", "t1", 10.0, now + 5) is True
    held, _ = store.counts("user:a", now + 12)
    assert held == 1, "renewal pushed the expiry out"
    assert store.renew("user:a", "never-existed", 10.0, now) is False


def test_two_processes_share_one_budget(tmp_path):
    """Two store objects on the same file/server are two workers for this purpose."""
    path = tmp_path / "shared.sqlite3"
    worker_a, worker_b = SqliteLeaseStore(path), SqliteLeaseStore(path)
    now = time.time()
    assert worker_a.acquire("user:a", "t1", 2, 0, 30.0, now)[0] is True
    assert worker_b.acquire("user:a", "t2", 2, 0, 30.0, now)[0] is True
    assert worker_b.acquire("user:a", "t3", 2, 0, 30.0, now)[0] is False, \
        "the third socket must be refused even though it reached a different worker"
    worker_a.release("user:a", "t1")
    assert worker_b.acquire("user:a", "t3", 2, 0, 30.0, now)[0] is True
    worker_a.close()
    worker_b.close()


def test_redis_reset_only_touches_its_own_prefix():
    client = fakeredis.FakeStrictRedis(decode_responses=True)
    from services.api_gateway.wsquota import RedisLeaseStore

    client.set("someone-elses-key", "keep me")
    store = RedisLeaseStore(client, prefix="no7:test:scoped")
    store.acquire("user:a", "t1", 2, 0, 30.0, time.time())
    store.reset()
    assert store.counts("user:a", time.time()) == (0, 0)
    assert client.get("someone-elses-key") == "keep me", "reset must never be a FLUSHDB"


# --------------------------------------------------------------------- the quota
def test_the_quota_refuses_over_the_cap_and_counts_it():
    quota = WebSocketQuota(MemoryLeaseStore(), per_identity=2, total=10, ttl_seconds=30)
    first, second = quota.acquire("user:a"), quota.acquire("user:a")
    assert isinstance(first, Lease) and isinstance(second, Lease)
    assert quota.acquire("user:a") is None
    assert quota.granted == 2 and quota.refused == 1
    quota.release(first)
    assert quota.acquire("user:a") is not None


def test_a_broken_store_keeps_sockets_alive_and_says_so():
    """Refusing to serve a dashboard because the cache blinked is the worse outcome."""

    class Broken:
        name = "redis"

        def acquire(self, *a, **k):
            raise ConnectionError("Error 111 connecting to 10.0.0.5:6379. Connection refused.")

        def renew(self, *a, **k):
            raise ConnectionError("down")

        def release(self, *a, **k):
            raise ConnectionError("down")

        def counts(self, *a, **k):
            raise ConnectionError("down")

        def reset(self):
            pass

    quota = WebSocketQuota(Broken(), per_identity=1, total=5, ttl_seconds=30)
    lease = quota.acquire("user:a")
    assert lease is not None and lease.degraded is True
    assert quota.acquire("user:a") is None, "the local fallback still enforces the cap"

    before = quota.degraded
    status = quota.status()
    assert quota.degraded == before, (
        "reading health must not count as a degradation — a 5s poll would otherwise "
        "inflate the number it reports")
    assert status["open"] == 1, (
        "with the shared store unreadable, `open` is this process's own view — "
        "which is exactly what `shared: false` below is warning about")
    assert status["degraded"] >= 1
    assert "Connection refused" in status["last_error"]
    assert status["shared"] is False
    assert "enforced against this process only" in status["warning"]


def test_a_memory_quota_admits_workers_would_multiply_it():
    status = WebSocketQuota(MemoryLeaseStore(), per_identity=4, total=8).status()
    assert status["shared"] is False
    assert "--workers N allows N times this cap" in status["warning"]


def test_an_expired_lease_is_retaken_on_renewal():
    clock = {"t": 1000.0}
    quota = WebSocketQuota(MemoryLeaseStore(), per_identity=1, total=4, ttl_seconds=10,
                           clock=lambda: clock["t"])
    lease = quota.acquire("user:a")
    clock["t"] += 30  # the lease lapsed while a payload was slow
    assert quota.renew(lease) is True, "the slot was free, so it is taken again"

    other = WebSocketQuota(quota.store, per_identity=1, total=4, ttl_seconds=10,
                           clock=lambda: clock["t"])
    assert other.acquire("user:a") is None, "the renewed lease still occupies the slot"


def test_build_lease_store_falls_back_and_explains(tmp_path):
    store, status = build_lease_store({"store": "redis", "redis_url": ""},
                                      path=tmp_path / "fallback.sqlite3")
    assert status["backend"] == "sqlite" and status["shared"] is True
    assert "no redis_url" in status["reason"]
    store.close()

    store, status = build_lease_store({"store": "redis", "redis_url": ""}, path=None)
    assert status["backend"] == "memory" and status["shared"] is False
    assert "per process again" in status["reason"]

    store, status = build_lease_store({"store": "memory"})
    assert status["backend"] == "memory" and status["reason"] == ""

    with pytest.raises(ValueError, match="unknown websocket quota store"):
        build_lease_store({"store": "cassandra"})


def test_build_lease_store_uses_a_live_client_when_it_pings():
    client = fakeredis.FakeStrictRedis(decode_responses=True)
    store, status = build_lease_store({"store": "redis", "redis_url": "redis://x:6379/0",
                                       "ws_key_prefix": "no7:test:build"},
                                      client_factory=lambda: client)
    assert status == {"requested": "redis", "backend": "redis", "shared": True,
                      "reason": "", "path": ""}
    assert store.acquire("user:a", "t1", 2, 0, 30.0, time.time())[0] is True


# ---------------------------------------------------------------- the live socket
def test_a_fourth_socket_is_refused_with_a_reason(client, token, monkeypatch):
    quota = client.app.state.ws_quota
    monkeypatch.setattr(quota, "per_identity", 2)
    quota.store.reset()

    first = client.websocket_connect(f"/ws/live?token={token}")
    second = client.websocket_connect(f"/ws/live?token={token}")
    ws1, ws2 = first.__enter__(), second.__enter__()
    try:
        ws1.receive_text()
        ws2.receive_text()
        with client.websocket_connect(f"/ws/live?token={token}") as ws3:
            message = json.loads(ws3.receive_text())
        assert message["code"] == 4429
        assert "too many open connections" in message["error"]
        assert "2 of 2 live sockets" in message["detail"]
    finally:
        first.__exit__(None, None, None)
        second.__exit__(None, None, None)
        quota.store.reset()


def test_closing_a_socket_gives_the_slot_back(client, token, monkeypatch):
    quota = client.app.state.ws_quota
    monkeypatch.setattr(quota, "per_identity", 1)
    quota.store.reset()
    try:
        with client.websocket_connect(f"/ws/live?token={token}") as ws:
            ws.receive_text()
        # Same identity, one slot: this only works if the first socket released it.
        with client.websocket_connect(f"/ws/live?token={token}") as ws:
            data = json.loads(ws.receive_text())
        assert data["type"] == "snapshot", "the slot was reused, not refused"
    finally:
        quota.store.reset()


def test_an_expired_token_cannot_keep_streaming(client, settings, monkeypatch):
    """The socket must not outlive the credential that opened it."""
    import jwt

    secret = settings.security["jwt_secret"]
    expiring = jwt.encode({"sub": "demo@no7.ai", "role": "admin", "iat": int(time.time()) - 10,
                           "exp": int(time.time()) + 1, "iss": "no7-ai-trading-pro"},
                          secret, algorithm="HS256")
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as caught:
        with client.websocket_connect(f"/ws/live?token={expiring}") as ws:
            ws.receive_text()           # first frame arrives while the token is valid
            for _ in range(5):          # then it expires mid-stream
                ws.receive_text()
    assert caught.value.code == 4401


def test_health_reports_the_socket_cap(client, auth):
    body = client.get("/api/system/health", headers=auth).json()["websockets"]
    assert body["enforced"] is True
    assert body["max_per_user"] >= 1 and body["max_total"] >= 1
    assert body["lease_ttl_seconds"] > 0
    assert "open" in body and "refused" in body
    assert body["store"] in ("memory", "sqlite", "redis")


def test_the_global_counter_sees_every_identity():
    quota = WebSocketQuota(MemoryLeaseStore(), per_identity=4, total=8, ttl_seconds=30)
    quota.acquire("user:a")
    quota.acquire("user:b")
    _, total = quota.counts(GLOBAL_KEY)
    assert total == 2, "the total cap can only work if it counts everyone"


def test_an_outage_cannot_hand_out_a_second_set_of_slots():
    """The slots Redis granted must still count when Redis stops answering."""

    class Flaky:
        name = "redis"

        def __init__(self):
            self.alive = True
            self.inner = MemoryLeaseStore()

        def _check(self):
            if not self.alive:
                raise ConnectionError("Error 111 connecting to 10.0.0.5:6379. Connection refused.")

        def acquire(self, *a, **k):
            self._check()
            return self.inner.acquire(*a, **k)

        def renew(self, *a, **k):
            self._check()
            return self.inner.renew(*a, **k)

        def release(self, *a, **k):
            self._check()
            return self.inner.release(*a, **k)

        def counts(self, *a, **k):
            self._check()
            return self.inner.counts(*a, **k)

        def reset(self):
            self.inner.reset()

    store = Flaky()
    quota = WebSocketQuota(store, per_identity=2, total=10, ttl_seconds=30)
    held = [quota.acquire("user:a"), quota.acquire("user:a")]
    assert all(lease is not None for lease in held)

    store.alive = False
    assert quota.acquire("user:a") is None, (
        "the two sockets granted before the outage must still occupy the cap")

    # Closing one gives exactly one slot back, not a clean slate.
    quota.release(held[0])
    assert quota.acquire("user:a") is not None
    assert quota.acquire("user:a") is None
