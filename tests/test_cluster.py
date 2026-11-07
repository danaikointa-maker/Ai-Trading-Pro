"""Shared state for more than one process.

The lease stops a second process from trading. This is the other half: a replica
must be able to *read* the leader's frames, and — when the backend it was asked
for is not usable — say so instead of pretending the cluster is fine.
"""
from __future__ import annotations

import time


from services.api_gateway.cluster import (LIVE_KEY, LocalSharedState, RedisSharedState,
                                          build_shared_state, decide_role, replica_payload)


class FakeRedis:
    """Just enough of the client surface: set/get/ping, with TTL recorded."""

    def __init__(self, fail_ping: bool = False) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.pings = 0
        self.fail_ping = fail_ping

    def set(self, key, value, ex=None):
        self.store[key] = value
        self.ttls[key] = ex
        return True

    def get(self, key):
        return self.store.get(key)

    def ping(self):
        self.pings += 1
        if self.fail_ping:
            raise ConnectionError("redis is down")
        return True


class FakeSettings:
    def __init__(self, cluster: dict) -> None:
        self.cluster = cluster


# --------------------------------------------------------------- local backend
def test_local_store_round_trip_and_expiry():
    store = LocalSharedState()
    store.publish("k", {"a": 1}, ttl=1)
    assert store.read("k") == {"a": 1}
    store._items["k"] = (time.time() - 1, {"a": 1})  # already expired
    assert store.read("k") is None
    assert "k" not in store._items, "expired frames are dropped, not kept forever"


def test_local_backend_is_the_default_and_says_nothing_is_shared():
    state, status = build_shared_state(FakeSettings({}), env={})
    assert isinstance(state, LocalSharedState)
    assert status["backend"] == "local"
    assert status["requested"] == "local"
    assert status["reason"] == ""


# --------------------------------------------------------------- redis backend
def test_redis_backend_uses_ttl_and_reads_json():
    client = FakeRedis()
    state, status = build_shared_state(
        FakeSettings({"backend": "redis", "redis_url": "redis://localhost:6379/0",
                      "state_ttl_seconds": 7}),
        client_factory=lambda: client, env={})
    assert status["backend"] == "redis"
    state.publish(LIVE_KEY, {"owner": "host#1", "payload": {"ok": True}})
    assert client.ttls[LIVE_KEY] == 7, "LIVE_KEY already carries the prefix"
    assert client.store[LIVE_KEY]
    assert state.read(LIVE_KEY)["payload"] == {"ok": True}
    assert state.healthy()["ok"] is True


def test_redis_bytes_payloads_and_broken_json_do_not_crash():
    client = FakeRedis()
    client.store["no7:k"] = b'{"x": 1}'
    state = RedisSharedState(client)
    assert state.read("k") == {"x": 1}
    client.store["no7:k"] = "not json"
    assert state.read("k") is None


def test_redis_health_reports_a_dead_server_instead_of_raising():
    state = RedisSharedState(FakeRedis(fail_ping=True))
    health = state.healthy()
    assert health["ok"] is False
    assert "redis is down" in health["error"]


def test_redis_requested_without_a_url_falls_back_and_explains():
    state, status = build_shared_state(FakeSettings({"backend": "redis"}), env={})
    assert status["backend"] == "local"
    assert status["requested"] == "redis"
    assert "no redis_url" in status["reason"]


def test_redis_requested_without_the_package_falls_back_and_explains(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_redis(name, *args, **kwargs):
        if name == "redis":
            raise ImportError("No module named 'redis'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_redis)
    state, status = build_shared_state(
        FakeSettings({"backend": "redis", "redis_url": "redis://x:6379"}), env={})
    assert isinstance(state, LocalSharedState)
    assert "not installed" in status["reason"]


def test_a_client_that_cannot_connect_falls_back_and_explains():
    def boom():
        raise ConnectionError("connection refused")

    state, status = build_shared_state(
        FakeSettings({"backend": "redis", "redis_url": "redis://x:6379"}),
        client_factory=boom, env={})
    assert status["backend"] == "local"
    assert "connection refused" in status["reason"]


def test_env_url_is_honoured_when_config_has_none():
    client = FakeRedis()
    state, status = build_shared_state(
        FakeSettings({"backend": "redis"}), client_factory=lambda: client,
        env={"NO7_REDIS_URL": "redis://env-host:6379/1"})
    assert status["backend"] == "redis"


# ------------------------------------------------------------------- replicas
def test_replica_payload_marks_the_frame_and_its_age():
    store = LocalSharedState()
    store.publish(LIVE_KEY, {"payload": {"price": 2000.0}, "owner": "host#1",
                             "published_at": time.time() - 2.0})
    frame = replica_payload(store)
    assert frame["price"] == 2000.0
    assert frame["replica"] is True
    assert frame["served_by"] == "host#1"
    assert 2.0 <= frame["frame_age_seconds"] <= 4.0


def test_replica_payload_is_none_when_the_leader_has_not_published():
    assert replica_payload(LocalSharedState()) is None
    store = LocalSharedState()
    store.publish(LIVE_KEY, {"payload": "not-a-dict"})
    assert replica_payload(store) is None


def test_role_table():
    assert decide_role("held", "local", False) == "leader"
    assert decide_role("shared", "redis", True) == "leader"
    assert decide_role("blocked", "redis", True) == "replica"
    assert decide_role("lost", "redis", True) == "replica"
    # nothing shared to read: the old, explicit "blocked" behaviour
    assert decide_role("blocked", "local", True) == "blocked"
    assert decide_role("blocked", "redis", False) == "blocked"
    assert decide_role("unclaimed", "local", False) == "solo"


# ------------------------------------------------------------ runtime wiring
def test_the_running_runtime_publishes_a_frame_readable_by_a_replica(runtime):
    runtime._maybe_publish(now=time.time() + 5)
    frame = runtime.shared.read(LIVE_KEY)
    assert frame is not None, "the leader must publish for replicas to exist"
    assert frame["owner"] == runtime._owner
    assert isinstance(frame["payload"], dict) and frame["payload"]

    served = replica_payload(runtime.shared)
    assert served["replica"] is True
    assert served["served_by"] == runtime._owner


def test_health_reports_the_cluster_role(runtime):
    health = runtime.health()
    cluster = health["cluster"]
    assert cluster["backend"] in ("local", "redis")
    assert cluster["role"] in ("leader", "replica", "blocked", "solo")
    assert "shared_health" in cluster
    if cluster["backend"] == "local":
        assert cluster["reason"] == ""


def test_a_redis_server_that_dies_after_build_does_not_break_health_or_reads():
    """A lazy client hides a dead server: reads must degrade, not raise."""
    client = FakeRedis()
    state = RedisSharedState(client)

    def dead_get(key):
        raise ConnectionError("Error 111 connecting: refused")

    client.get = dead_get
    assert state.read("k") is None
    health = state.healthy()
    assert health["ok"] is False
    assert "refused" in health["error"]


def test_build_probes_the_server_and_falls_back_with_the_reason():
    state, status = build_shared_state(
        FakeSettings({"backend": "redis", "redis_url": "redis://127.0.0.1:6399/0"}),
        client_factory=lambda: FakeRedis(fail_ping=True), env={})
    assert status["backend"] == "local"
    assert "unreachable" in status["reason"]
    assert "127.0.0.1:6399" in status["reason"]
    assert isinstance(state, LocalSharedState)


def test_publish_failure_is_recorded_not_raised():
    client = FakeRedis()

    def dead_set(key, value, ex=None):
        raise ConnectionError("gone")

    client.set = dead_set
    state = RedisSharedState(client)
    state.publish("k", {"a": 1})
    assert "gone" in state.last_error
