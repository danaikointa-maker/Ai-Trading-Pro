"""Snapshot replacement must preserve evidence on partial database failures."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from integrations.brokers.base import BrokerError
from packages.persistence.db import Database
from packages.shared_schemas.models import Position
from services.execution_gateway.gateway import ExecutionGateway


def position(ticket, broker_id="demo"):
    return Position(ticket=ticket, symbol="XAUUSD", direction="up", volume=0.1,
                    entry=2000, sl=1990, tp=2020, current_price=2001,
                    open_time=1, broker_id=broker_id)


@pytest.fixture
def snapshot(tmp_path):
    db = Database(tmp_path / "snapshot.db")
    gateway = ExecutionGateway(SimpleNamespace(execution={}), db)
    gateway.open_position_snapshot([position("kept")], broker_id="demo")
    gateway.open_position_snapshot([position("foreign", "other")], broker_id="other")
    yield gateway, db
    db.close()


@pytest.mark.parametrize("failure", ["insert", "delete"])
def test_snapshot_failure_rolls_back_entire_replacement(snapshot, failure):
    gateway, db = snapshot
    before = [dict(row) for row in db.query("SELECT * FROM open_positions ORDER BY ticket")]
    event, condition = ("INSERT", "NEW.ticket='second'") if failure == "insert" else (
        "DELETE", "OLD.ticket='kept'")
    db.execute(f"CREATE TRIGGER fail_snapshot BEFORE {event} ON open_positions "
               f"WHEN {condition} BEGIN SELECT RAISE(ABORT, 'snapshot injected failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="snapshot injected failure"):
        gateway.open_position_snapshot([position("first"), position("second")], broker_id="demo")
    assert [dict(row) for row in db.query("SELECT * FROM open_positions ORDER BY ticket")] == before
    db.execute("DROP TRIGGER fail_snapshot")
    gateway.open_position_snapshot([], broker_id="demo")
    assert [row["ticket"] for row in db.query("SELECT ticket FROM open_positions")] == ["foreign"]


@pytest.mark.parametrize("scope", [None, "", " "])
def test_empty_snapshot_requires_explicit_nonblank_scope(snapshot, scope):
    gateway, db = snapshot
    before = [dict(row) for row in db.query("SELECT * FROM open_positions")]
    with pytest.raises(BrokerError, match="scope"):
        gateway.open_position_snapshot([], broker_id=scope)
    assert [dict(row) for row in db.query("SELECT * FROM open_positions")] == before


def test_other_connection_never_observes_partial_snapshot(snapshot):
    gateway, db = snapshot
    observer = Database(db.path)
    seen = []

    def trace(sql):
        if sql.startswith("INSERT OR REPLACE INTO open_positions") or sql.startswith("DELETE FROM open_positions"):
            seen.append({row["ticket"] for row in observer.query("SELECT ticket FROM open_positions")})

    try:
        db._conn.set_trace_callback(trace)
        gateway.open_position_snapshot([position("first"), position("second")], broker_id="demo")
        assert len(seen) == 3
        assert all(tickets == {"kept", "foreign"} for tickets in seen)
        assert {row["ticket"] for row in observer.query("SELECT ticket FROM open_positions")} == {
            "first", "second", "foreign"}
        assert json.loads(observer.query_one("SELECT payload FROM open_positions WHERE ticket='foreign'")[0])["broker_id"] == "other"
    finally:
        db._conn.set_trace_callback(None)
        observer.close()


def test_snapshot_rechecks_collision_after_acquiring_writer_lock(snapshot):
    gateway, db = snapshot
    writer = Database(db.path)
    attempted = Event()

    def trace(sql):
        if sql.startswith("BEGIN IMMEDIATE"):
            attempted.set()

    db._conn.set_trace_callback(trace)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with writer.cursor() as cur:
                cur.execute("BEGIN IMMEDIATE")
                future = pool.submit(gateway.open_position_snapshot, [position("contended")], "demo")
                assert attempted.wait(5), "snapshot did not attempt writer lock"
                cur.execute("INSERT INTO open_positions(ticket,payload,updated_at) VALUES(?,?,?)",
                            ("contended", json.dumps(position("contended", "other").model_dump()), 1))
            with pytest.raises(BrokerError, match="collision"):
                future.result(timeout=10)
        assert json.loads(writer.query_one("SELECT payload FROM open_positions WHERE ticket='contended'")[0])["broker_id"] == "other"
        assert writer.query_one("SELECT ticket FROM open_positions WHERE ticket='kept'") is not None
    finally:
        db._conn.set_trace_callback(None)
        writer.close()