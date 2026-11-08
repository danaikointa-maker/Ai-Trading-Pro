"""The Redis paths, proved against a REAL redis-server — not a reimplementation.

``tests/test_ratelimit_shared.py`` runs the Redis store on fakeredis. That is a good
contract test, but fakeredis is a Python reimplementation: it cannot prove that this
Lua script is atomic on the real server, that ``PEXPIRE`` really removes idle
identities, that a wrong-typed key raises the error the limiter catches, or that a
server dying mid-flight degrades the way the docs claim.

So these tests start an actual ``redis-server`` process and talk to it over TCP.
Without that binary they skip, and ``./scripts/fetch_redis_server.sh`` puts one in
``.tools/bin`` without root (CI does exactly that, so the gate really runs them).
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import pytest

from services.api_gateway.cluster import RedisSharedState, build_shared_state
from services.api_gateway.ratelimit import (MemoryBucketStore, RateLimiter, RedisBucketStore,
                                            build_store)

ROOT = Path(__file__).resolve().parents[1]
redis = pytest.importorskip("redis", reason="pip install redis")


def _redis_server_binary() -> str | None:
    """Prefer an explicit path, then the repo's .tools/bin, then whatever is on PATH."""
    explicit = os.environ.get("NO7_REDIS_SERVER", "").strip()
    if explicit and Path(explicit).is_file():
        return explicit
    local = ROOT / ".tools" / "bin" / "redis-server"
    if local.is_file():
        return str(local)
    return shutil.which("redis-server")


SERVER_BINARY = _redis_server_binary()

pytestmark = pytest.mark.skipif(
    SERVER_BINARY is None,
    reason="no redis-server binary — run ./scripts/fetch_redis_server.sh",
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class RealRedisServer:
    """A throwaway redis-server: no persistence, loopback only, killable on demand."""

    def __init__(self) -> None:
        self.port = _free_port()
        self.dir = tempfile.mkdtemp(prefix="no7-redis-")
        self.proc = subprocess.Popen(
            [SERVER_BINARY, "--port", str(self.port), "--bind", "127.0.0.1",
             "--save", "", "--appendonly", "no", "--dir", self.dir],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        self._await_ready()

    @property
    def url(self) -> str:
        return f"redis://127.0.0.1:{self.port}/0"

    def client(self, **kwargs):
        return redis.Redis.from_url(self.url, decode_responses=True,
                                    socket_timeout=2, socket_connect_timeout=2, **kwargs)

    def _await_ready(self, timeout: float = 20.0) -> None:
        deadline = time.time() + timeout
        last = ""
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"redis-server exited: {self.proc.communicate()[0]}")
            try:
                if self.client().ping():
                    return
            except Exception as exc:  # noqa: BLE001 - still booting
                last = f"{type(exc).__name__}: {exc}"
            time.sleep(0.05)
        raise RuntimeError(f"redis-server never became ready ({last})")

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover - belt and braces
                self.proc.kill()
                self.proc.wait(timeout=10)
        shutil.rmtree(self.dir, ignore_errors=True)


@pytest.fixture(scope="module")
def redis_server():
    server = RealRedisServer()
    yield server
    server.stop()


@pytest.fixture()
def disposable_redis():
    """A server a test is allowed to kill."""
    server = RealRedisServer()
    yield server
    server.stop()


@pytest.fixture()
def prefix(request):
    """One key namespace per test, so nothing has to FLUSHDB."""
    return f"no7:test:{request.node.name[:40]}:{os.getpid()}"


# --------------------------------------------------------------- version / sanity
def test_it_is_a_real_redis_server(redis_server):
    info = redis_server.client().info("server")
    assert info["redis_version"].split(".")[0].isdigit()
    assert info.get("executable", SERVER_BINARY)
    # fakeredis reports its own module path here; a real server reports a process.
    assert int(info["process_id"]) > 0


# ------------------------------------------------------------------- Lua parity
def test_the_lua_bucket_decides_exactly_like_the_in_process_bucket(redis_server, prefix):
    """Same inputs, same answers — otherwise the backend changes the policy."""
    shared = RedisBucketStore(redis_server.client(), prefix=prefix)
    local = MemoryBucketStore()
    limit, rate, now = 5.0, 5.0 / 60.0, 1_000_000.0

    decisions_remote, decisions_local = [], []
    for step in range(12):
        clock = now + step * 4.0        # 4s at 5/60 per second refills 1/3 token
        allowed_r, tokens_r = shared.spend(("probe", "u"), limit, rate, clock)
        allowed_l, tokens_l = local.spend(("probe", "u"), limit, rate, clock)
        decisions_remote.append((allowed_r, round(tokens_r, 6)))
        decisions_local.append((allowed_l, round(tokens_l, 6)))

    assert decisions_remote == decisions_local
    assert [d[0] for d in decisions_remote][:5] == [True] * 5


def test_the_stored_balance_round_trips_exactly(redis_server, prefix):
    """Lua's tostring() is %.14g: it rounds the balance on every single spend.

    That rounding is what made a bucket sitting on exactly 1.000000 token allow one
    more request in memory than in Redis. The script writes %.17g instead, so the
    float64 that goes in is the float64 that comes back.
    """
    client = redis_server.client()
    store = RedisBucketStore(client, prefix=prefix)
    limit, rate, now = 5.0, 5.0 / 60.0, 1_000_000.0

    balances = []
    for step in range(6):
        _allowed, tokens = store.spend(("probe", "round"), limit, rate, now + step * 4.0)
        stored = client.hget(f"{prefix}:probe:round", "tokens")
        assert float(stored) == tokens, f"step {step}: {stored} != {tokens!r}"
        balances.append(tokens)

    assert any(float(f"{b:.14g}") != b for b in balances), (
        "this test only proves something while a balance needs more than 14 digits"
    )


def test_two_connections_spend_from_one_budget(redis_server, prefix):
    """Two processes = two connections. The budget must not double."""
    first = RedisBucketStore(redis_server.client(), prefix=prefix)
    second = RedisBucketStore(redis_server.client(), prefix=prefix)
    limit, rate, now = 6.0, 0.0001, 2_000.0

    allowed = [store.spend(("probe", "u"), limit, rate, now)[0]
               for _ in range(5) for store in (first, second)]

    assert sum(allowed) == 6, "a limit of 6 was handed out more than six times"
    assert allowed[:6] == [True] * 6 and allowed[6:] == [False] * 4


def test_refill_comes_from_the_callers_clock_not_the_servers(redis_server, prefix):
    store = RedisBucketStore(redis_server.client(), prefix=prefix)
    limit, rate = 10.0, 10.0 / 60.0
    now = 5_000.0
    assert all(store.spend(("probe", "u"), limit, rate, now)[0] for _ in range(10))
    assert store.spend(("probe", "u"), limit, rate, now)[0] is False

    # No sleeping: hand the store a clock 6 seconds later (10/60 * 6 = 1 token).
    allowed, tokens = store.spend(("probe", "u"), limit, rate, now + 6.0)
    assert allowed is True
    assert tokens < 0.001
    assert store.spend(("probe", "u"), limit, rate, now + 6.0)[0] is False


def test_idle_identities_carry_a_ttl_and_really_disappear(redis_server, prefix):
    client = redis_server.client()
    store = RedisBucketStore(client, prefix=prefix)
    # limit/rate = 1 second of window, so the key should be gone a moment later.
    store.spend(("probe", "ttl"), 1.0, 1.0, 10_000.0)
    key = f"{prefix}:probe:ttl"
    assert 0 < client.pttl(key) <= 1000

    deadline = time.time() + 5
    while client.exists(key) and time.time() < deadline:
        time.sleep(0.05)
    assert client.exists(key) == 0, "PEXPIRE did not remove the idle identity"


def test_reset_only_deletes_our_own_keys(redis_server, prefix):
    client = redis_server.client()
    store = RedisBucketStore(client, prefix=prefix)
    store.spend(("probe", "a"), 3.0, 1.0, 1.0)
    client.set("someone-elses-key", "keep me")

    store.reset()

    assert store.tracked == 0
    assert client.get("someone-elses-key") == "keep me", "reset() must not flush the database"
    client.delete("someone-elses-key")


def test_a_wrong_typed_key_raises_the_error_the_limiter_catches(redis_server, prefix):
    """Operational reality: someone SETs a string where the hash lives."""
    client = redis_server.client()
    client.set(f"{prefix}:probe:clash", "not-a-hash")
    store = RedisBucketStore(client, prefix=prefix)

    with pytest.raises(redis.exceptions.ResponseError):
        store.spend(("probe", "clash"), 5.0, 1.0, 1.0)

    # The limiter must survive it: degraded, local bucket, request still answered.
    limiter = RateLimiter({"probe": {"limit": 2, "window_seconds": 60}}, store=store,
                          clock=lambda: 42.0)
    assert limiter.check("clash", "probe")[0] is True
    assert limiter.degraded == 1
    assert "ResponseError" in limiter.last_error
    client.delete(f"{prefix}:probe:clash")


# ------------------------------------------------------------------ real races
_WORKER = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, {root!r})
    import redis
    from services.api_gateway.ratelimit import RedisBucketStore

    client = redis.Redis.from_url({url!r}, decode_responses=True)
    store = RedisBucketStore(client, prefix={prefix!r})
    allowed = 0
    for _ in range({spends}):
        ok, _tokens = store.spend(("probe", "shared"), {limit}, 0.0001, 7_000.0)
        allowed += 1 if ok else 0
    print(allowed)
    """
)


def test_four_processes_cannot_spend_more_than_the_limit(redis_server, prefix):
    """The property that matters: limit x workers must not become the real limit."""
    code = _WORKER.format(root=str(ROOT), url=redis_server.url, prefix=prefix,
                          spends=25, limit=40.0)
    procs = [subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True) for _ in range(4)]
    outs = []
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, f"worker failed: {err}"
        outs.append(int(out.strip()))

    assert sum(outs) == 40, f"limit 40 was handed out {sum(outs)} times across {outs}"
    tokens = float(redis_server.client().hget(f"{prefix}:probe:shared", "tokens"))
    assert tokens < 1.0


# ------------------------------------------------------------ dying mid-flight
def test_a_server_that_dies_mid_flight_degrades_and_marks_both_200s_and_429s(disposable_redis):
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from services.api_gateway.ratelimit import RateLimitMiddleware

    store = RedisBucketStore(disposable_redis.client(), prefix="no7:test:dying")
    limiter = RateLimiter({"default": {"limit": 2, "window_seconds": 60}}, store=store,
                          clock=lambda: 9_000.0)

    async def handler(request):
        return JSONResponse({"ok": True})

    middleware = RateLimitMiddleware(None, limiter=limiter, settings=None,
                                     trusted_proxies=["127.0.0.1/32"])
    middleware.app = Starlette(routes=[Route("/api/probe", handler)])
    client = TestClient(middleware)

    first = client.get("/api/probe")
    assert first.status_code == 200
    assert "x-ratelimit-degraded" not in first.headers, "healthy Redis must not look degraded"

    disposable_redis.stop()                      # the cache dies between requests

    # The fallback bucket starts full, so the limit of 2 is honoured again locally.
    served = [client.get("/api/probe") for _ in range(2)]
    assert [r.status_code for r in served] == [200, 200], "a dead cache must not take the API down"
    assert {r.headers["x-ratelimit-degraded"] for r in served} == {"redis"}

    denied = client.get("/api/probe")            # local bucket of 2 is now empty
    assert denied.status_code == 429
    assert denied.headers["x-ratelimit-degraded"] == "redis", "a degraded 429 must say so"
    assert int(denied.headers["retry-after"]) >= 1
    assert limiter.degraded >= 2
    assert "Error" in limiter.last_error or "refused" in limiter.last_error.lower()


def test_build_store_falls_back_when_the_port_is_dead(tmp_path):
    dead = f"redis://127.0.0.1:{_free_port()}/0"
    store, status = build_store({"store": "redis", "redis_url": dead},
                                path=tmp_path / "rl.sqlite3")

    assert status["backend"] == "sqlite" and status["shared"] is True
    assert "redis unreachable" in status["reason"]
    assert status["requested"] == "redis"
    store.close()


def test_build_store_uses_redis_when_it_is_really_there(redis_server, tmp_path, prefix):
    store, status = build_store({"store": "redis", "redis_url": redis_server.url,
                                 "key_prefix": prefix}, path=tmp_path / "rl.sqlite3")

    assert status["backend"] == "redis" and status["shared"] is True and status["reason"] == ""
    assert isinstance(store, RedisBucketStore)
    assert store.spend(("probe", "wired"), 2.0, 1.0, 1.0)[0] is True
    assert redis_server.client().exists(f"{prefix}:probe:wired") == 1


# -------------------------------------------------------------- cluster frames
def test_a_frame_published_by_one_process_is_read_by_another(redis_server):
    writer = RedisSharedState(redis_server.client(), prefix="no7:test:bus", default_ttl=10)
    reader = RedisSharedState(redis_server.client(), prefix="no7:test:bus", default_ttl=10)

    writer.publish("v1", {"role": "leader", "price": 3750.25, "symbol": "XAUUSD"})
    frame = reader.read("v1")

    assert frame == {"role": "leader", "price": 3750.25, "symbol": "XAUUSD"}
    assert reader.healthy() == {"ok": True, "backend": "redis", "error": ""}
    raw = redis_server.client().get("no7:test:bus:v1")
    assert json.loads(raw)["symbol"] == "XAUUSD"
    assert 0 < redis_server.client().ttl("no7:test:bus:v1") <= 10


def test_a_stale_frame_expires_instead_of_being_served(redis_server):
    state = RedisSharedState(redis_server.client(), prefix="no7:test:stale", default_ttl=1)
    state.publish("v1", {"role": "leader"}, ttl=1)
    assert state.read("v1") == {"role": "leader"}

    deadline = time.time() + 5
    while state.read("v1") is not None and time.time() < deadline:
        time.sleep(0.05)
    assert state.read("v1") is None, "a replica must never serve a frame older than the TTL"


def test_the_frame_bus_fails_closed_when_the_server_dies(disposable_redis):
    state = RedisSharedState(disposable_redis.client(), prefix="no7:test:dead", default_ttl=10)
    state.publish("v1", {"role": "leader"})
    assert state.read("v1") == {"role": "leader"}

    disposable_redis.stop()

    state.publish("v1", {"role": "leader"})      # must not raise: trading goes on
    assert state.read("v1") is None, "no frame is better than a stale one"
    health = state.healthy()
    assert health["ok"] is False and health["backend"] == "redis" and health["error"]


def test_build_shared_state_reports_redis_when_it_is_really_there(redis_server):
    class Settings:
        cluster = {"backend": "redis", "redis_url": redis_server.url,
                   "key_prefix": "no7:test:wire", "state_ttl_seconds": 7}

    state, status = build_shared_state(Settings(), env={})

    assert status == {"requested": "redis", "backend": "redis", "reason": "", "ttl_seconds": 7}
    assert isinstance(state, RedisSharedState)
    state.publish("v1", {"ok": True})
    assert state.read("v1") == {"ok": True}
    assert 0 < redis_server.client().ttl("no7:test:wire:v1") <= 7


def test_build_shared_state_falls_back_when_the_port_is_dead():
    class Settings:
        cluster = {"backend": "redis", "redis_url": f"redis://127.0.0.1:{_free_port()}/0"}

    state, status = build_shared_state(Settings(), env={})

    assert status["backend"] == "local"
    assert "redis unreachable" in status["reason"]
    assert state.healthy()["backend"] == "local"


# ------------------------------------------------- websocket quota, really shared
_WS_WORKER = (
    """
import sys
sys.path.insert(0, {root!r})
import redis
from services.api_gateway.wsquota import RedisLeaseStore

client = redis.Redis.from_url({url!r}, decode_responses=True)
store = RedisLeaseStore(client, prefix={prefix!r})
granted = 0
for i in range({attempts}):
    ok, _held, _used = store.acquire("user:shared", f"{worker}-{{i}}", {limit}, 0, 60.0, 10_000.0)
    granted += 1 if ok else 0
print(granted)
"""
)


def test_four_workers_cannot_exceed_one_socket_budget(redis_server, prefix):
    """`--workers N` must not multiply the socket cap, which is the whole point."""
    procs = []
    for worker in range(4):
        code = _WS_WORKER.format(root=str(ROOT), url=redis_server.url, prefix=prefix,
                                 attempts=5, limit=6, worker=f"w{worker}")
        procs.append(subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True))
    granted = []
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, f"worker failed: {err}"
        granted.append(int(out.strip()))

    assert sum(granted) == 6, f"a cap of 6 was handed out {sum(granted)} times across {granted}"
    assert redis_server.client().zcard(f"{prefix}:id:user:shared") == 6


def test_a_killed_worker_releases_its_socket_slot_by_expiry(redis_server, prefix):
    """No decrement ever runs for a SIGKILLed worker — only the lease TTL saves us."""
    from services.api_gateway.wsquota import RedisLeaseStore

    store = RedisLeaseStore(redis_server.client(), prefix=prefix)
    now = 20_000.0
    assert store.acquire("user:ghost", "dead", 1, 0, 30.0, now)[0] is True
    assert store.acquire("user:ghost", "new", 1, 0, 30.0, now)[0] is False

    # The caller's clock moves past the lease; the server never had to be told.
    assert store.acquire("user:ghost", "new", 1, 0, 30.0, now + 31)[0] is True
    held, _total = store.counts("user:ghost", now + 31)
    assert held == 1


def test_the_socket_quota_survives_the_server_disappearing(disposable_redis):
    from services.api_gateway.wsquota import RedisLeaseStore, WebSocketQuota

    quota = WebSocketQuota(RedisLeaseStore(disposable_redis.client(), prefix="no7:test:wsdie"),
                           per_identity=2, total=10, ttl_seconds=30)
    assert quota.acquire("user:a") is not None
    disposable_redis.stop()

    lease = quota.acquire("user:a")
    assert lease is not None and lease.degraded is True, "a dead cache must not kill the dashboard"
    assert quota.acquire("user:a") is None, "the local fallback still caps at 2"
    status = quota.status()
    assert status["degraded"] >= 1 and status["shared"] is False
    assert "Connection refused" in status["last_error"] or "Error" in status["last_error"]
