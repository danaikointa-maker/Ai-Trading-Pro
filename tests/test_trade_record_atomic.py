"""Trade completion and snapshot removal share one transaction, using local SQLite only."""
import json
import sqlite3
from types import SimpleNamespace

import pytest

from integrations.brokers.base import BrokerError
from packages.persistence.db import Database
from packages.shared_schemas.models import Position, TradeRecord
from services.execution_gateway.gateway import ExecutionGateway


def trade(broker_id="demo", **changes):
    values = dict(ticket="same", symbol="XAUUSD", direction="up", volume=0.1,
                  entry=2000, exit=2001, opened_at=1, closed_at=2, points=100,
                  gross_pnl=10, costs=0, pnl=10, broker_id=broker_id)
    return TradeRecord(**(values | changes))


@pytest.fixture
def journal(tmp_path):
    db = Database(tmp_path / "journal.db")
    gateway = ExecutionGateway(SimpleNamespace(execution={}), db)
    pos = Position(ticket="same", symbol="XAUUSD", direction="up", volume=0.1,
                   entry=2000, sl=1990, tp=2020, current_price=2001, open_time=1, broker_id="demo")
    gateway.open_position_snapshot([pos], broker_id="demo")
    yield gateway, db
    db.close()


def test_trade_delete_failure_rolls_back_insert(journal):
    gateway, db = journal
    before = [dict(row) for row in db.query("SELECT * FROM open_positions")]
    db.execute("CREATE TRIGGER fail_close BEFORE DELETE ON open_positions "
               "BEGIN SELECT RAISE(ABORT, 'injected close failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected close failure"):
        gateway.record_trade(trade())
    assert db.query("SELECT * FROM trades") == []
    assert [dict(row) for row in db.query("SELECT * FROM open_positions")] == before


def test_record_trade_never_deletes_foreign_snapshot(journal):
    gateway, db = journal
    with pytest.raises(BrokerError, match="collision"):
        gateway.record_trade(trade("other"))
    assert db.query("SELECT * FROM trades") == []
    assert json.loads(db.query_one("SELECT payload FROM open_positions")[0])["broker_id"] == "demo"


@pytest.mark.parametrize("changes", [{"broker_id": "other"}, {"pnl": 999}, {"closed_at": 3}])
def test_record_trade_never_overwrites_existing_evidence(journal, changes):
    gateway, db = journal
    gateway.record_trade(trade())
    before = dict(db.query_one("SELECT * FROM trades"))
    with pytest.raises(BrokerError, match="conflict|collision"):
        gateway.record_trade(trade(**changes))
    assert dict(db.query_one("SELECT * FROM trades")) == before


def test_other_connection_cannot_observe_half_completed_trade(journal):
    gateway, db = journal
    reader = Database(db.path)
    seen = []

    def trace(sql):
        if sql.startswith(("INSERT", "DELETE FROM open_positions")):
            seen.append((len(reader.query("SELECT * FROM trades")),
                         len(reader.query("SELECT * FROM open_positions"))))

    try:
        db._conn.set_trace_callback(trace)
        gateway.record_trade(trade())
        assert len(seen) == 2
        assert all(state == (0, 1) for state in seen)
        assert len(reader.query("SELECT * FROM trades")) == 1
        assert reader.query("SELECT * FROM open_positions") == []
    finally:
        db._conn.set_trace_callback(None)
        reader.close()


def test_identical_trade_replay_is_idempotent(journal):
    gateway, db = journal
    gateway.record_trade(trade())
    before = dict(db.query_one("SELECT * FROM trades"))
    gateway.record_trade(trade())
    assert dict(db.query_one("SELECT * FROM trades")) == before


def test_trade_never_removes_reused_ticket_from_newer_position(journal):
    gateway, db = journal
    with pytest.raises(BrokerError, match="conflict"):
        gateway.record_trade(trade(opened_at=0))
    assert db.query("SELECT * FROM trades") == []
    assert len(db.query("SELECT * FROM open_positions")) == 1