"""Single-writer guard around the trading runtime.

Two runtimes pointed at one database would each generate signals from the same
tick and each send their own order, so the runtime takes a lease before it
starts ticking. These tests fix the behaviour of that lease: refuse while a live
owner holds it, take over once the heartbeat is stale, and never leave the
system locked out after a crash.
"""
from __future__ import annotations

import time

import pytest

from packages.persistence.db import Database
from services.api_gateway.state import (
    LEASE_KEY,
    LEASE_STALE_SECONDS,
    claim_runtime_lease,
    heartbeat_lease,
    lease_owner,
    release_runtime_lease,
)


@pytest.fixture()
def db(tmp_path):
    database = Database(str(tmp_path / "lease.sqlite3"))
    yield database
    database.close()


def test_first_claim_wins(db):
    ok, record = claim_runtime_lease(db, "host-a#1", now=1000.0)
    assert ok
    assert record["state"] == "held"
    assert record["owner"] == "host-a#1"
    assert db.kv_get(LEASE_KEY)["heartbeat"] == pytest.approx(1000.0)


def test_second_process_is_refused_while_the_heartbeat_is_fresh(db):
    claim_runtime_lease(db, "host-a#1", now=1000.0)
    ok, record = claim_runtime_lease(db, "host-a#2", now=1010.0)
    assert not ok
    assert record["state"] == "blocked"
    assert record["owner"] == "host-a#1"
    assert record["heartbeat_age_seconds"] == pytest.approx(10.0)
    # the holder must not be disturbed by a refused claim
    assert db.kv_get(LEASE_KEY)["owner"] == "host-a#1"


def test_stale_heartbeat_is_taken_over_after_a_crash(db):
    claim_runtime_lease(db, "host-a#1", now=1000.0)
    ok, record = claim_runtime_lease(db, "host-a#2", now=1000.0 + LEASE_STALE_SECONDS + 1)
    assert ok
    assert record["owner"] == "host-a#2"
    assert record["started_at"] == pytest.approx(1000.0 + LEASE_STALE_SECONDS + 1)


def test_same_owner_may_re_enter_and_keeps_its_start_time(db):
    claim_runtime_lease(db, "host-a#1", now=1000.0)
    ok, record = claim_runtime_lease(db, "host-a#1", now=1005.0)
    assert ok
    assert record["started_at"] == pytest.approx(1000.0)
    assert record["heartbeat"] == pytest.approx(1005.0)


def test_force_allows_a_second_runtime_but_records_it_as_shared(db):
    claim_runtime_lease(db, "host-a#1", now=1000.0)
    ok, record = claim_runtime_lease(db, "host-a#2", now=1001.0, force=True)
    assert ok
    assert record["state"] == "shared"


def test_heartbeat_refreshes_and_reports_a_lost_lease(db):
    claim_runtime_lease(db, "host-a#1", now=1000.0)
    refreshed = heartbeat_lease(db, "host-a#1", now=1012.0)
    assert refreshed["state"] == "held"
    assert db.kv_get(LEASE_KEY)["heartbeat"] == pytest.approx(1012.0)

    claim_runtime_lease(db, "host-a#2", now=2000.0)
    lost = heartbeat_lease(db, "host-a#1", now=2001.0)
    assert lost["state"] == "lost"
    assert lost["owner"] == "host-a#2"
    assert db.kv_get(LEASE_KEY)["owner"] == "host-a#2"


def test_release_only_clears_the_owners_own_lease(db):
    claim_runtime_lease(db, "host-a#1", now=1000.0)
    released, record = release_runtime_lease(db, "host-a#2")
    assert not released
    assert record["owner"] == "host-a#1"
    assert db.kv_get(LEASE_KEY)["owner"] == "host-a#1"
    released, _ = release_runtime_lease(db, "host-a#1")
    assert released
    assert db.kv_get(LEASE_KEY)["state"] == "released"
    # a released lease can be claimed immediately, no staleness wait
    ok, _ = claim_runtime_lease(db, "host-a#2", now=1001.0)
    assert ok


def test_owner_string_identifies_the_process():
    owner = lease_owner()
    assert "#" in owner
    assert owner.endswith(str(__import__("os").getpid()))


def test_runtime_refuses_to_start_ticking_when_another_owner_holds_the_lease(runtime):
    """The API must still answer, but this process must not trade."""
    runtime.db.kv_set(LEASE_KEY, {"state": "held", "owner": "other-host#999",
                                  "heartbeat": time.time(), "started_at": time.time()})
    try:
        assert runtime._claim_lease() is False
        assert runtime.lease["state"] == "blocked"
        health = runtime.health()
        assert health["status"] == "degraded"
        assert health["services"]["runtime"].startswith("blocked")
        assert health["runtime_lease"]["owner"] == "other-host#999"
        assert any(e["where"] == "runtime-lease" for e in runtime.errors), \
            "the refusal must be visible in the error log, not silent"
    finally:
        runtime.db.kv_set(LEASE_KEY, {"state": "held", "owner": lease_owner(),
                                      "heartbeat": time.time(), "started_at": time.time()})
        runtime.lease = {"state": "held", "owner": lease_owner()}


def test_a_blocked_runtime_cannot_release_the_live_owner_lease(runtime, tmp_path):
    """A refused process must shut down without freeing someone else's lease.

    The blocked record carries the *other* process as ``owner``, so releasing on
    shutdown has to use this process's own identity, not the record's.
    """
    from packages.persistence.db import Database

    live = Database(str(tmp_path / "live.sqlite3"))
    try:
        holder = "other-host#999"
        claim_runtime_lease(live, holder, now=time.time())
        rt = type(runtime).__new__(type(runtime))  # avoid a second full runtime
        from collections import deque

        from services.api_gateway.cluster import LocalSharedState

        rt.db, rt._owner = live, lease_owner()
        rt.lease, rt.errors = {"state": "unclaimed"}, deque(maxlen=5)
        rt.shared, rt.shared_status = LocalSharedState(), {"backend": "local"}
        rt.replica, rt._replica_frame = False, None
        assert rt._claim_lease() is False
        assert rt.lease["owner"] == holder
        release_runtime_lease(live, rt._owner)
        assert live.kv_get(LEASE_KEY)["owner"] == holder, "the live owner's lease must survive"
        assert live.kv_get(LEASE_KEY)["state"] == "held"
    finally:
        live.close()
