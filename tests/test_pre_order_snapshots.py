"""Original strategy levels must be committed before broker I/O and never revised."""
from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from integrations.brokers.base import BrokerError
from packages.persistence.db import Database
from packages.shared_schemas.models import Health, OrderRequest
from services.execution_gateway.gateway import ExecutionGateway


def broker():
    adapter = Mock()
    adapter.id = "demo"
    adapter.account_info.return_value = SimpleNamespace(
        broker_id="demo", login="101", server="Sandbox", currency="USD")
    adapter.health.return_value = Health.connected
    adapter.positions.return_value = []
    adapter.order_send.side_effect = BrokerError("unknown outcome")
    return adapter


def order():
    return OrderRequest(
        symbol="XAUUSD", side="buy", volume=0.1, sl=1990.0, tp=2030.0,
        broker_id="demo", signal_id="sig-snapshot", idempotency_key="sig-snapshot")


def evidence():
    return {
        "signal": {"id": "sig-snapshot", "broker_id": "demo", "symbol": "XAUUSD",
                   "timeframe": "M5", "action": "BUY", "plan": {
                       "direction": "up", "entry": 2000.0, "sl": 1990.0,
                       "tp3": 2030.0, "lot": 0.1}},
        "analysis": {"broker_id": "demo", "symbol": "XAUUSD", "timeframe": "M5",
                     "server_time": 100, "zones": [{"id": "fixed-zone", "low": 1994, "high": 1998}],
                     "sr_flips": [{"level": 1996}],
                     "fibonacci_band": {"level_50": 1997, "level_618": 1995}},
        "analysis_provenance": "decision_time",
    }


def test_original_evidence_is_committed_before_broker_io_and_survives_replay(tmp_path):
    path = tmp_path / "snapshots.sqlite3"
    db, observer = Database(path), Database(path)
    adapter = broker()
    gateway = ExecutionGateway(SimpleNamespace(execution={}), db)
    source = evidence()

    def send(*_args, **_kwargs):
        claim = observer.query_one("SELECT id FROM orders WHERE idempotency_key=?", ("sig-snapshot",))
        assert claim is not None
        row = observer.query_one("SELECT payload FROM pre_order_snapshots WHERE order_id=?", (claim["id"],))
        assert row is not None, "original evidence must be committed before broker I/O"
        assert json.loads(row["payload"])["analysis"]["zones"][0]["id"] == "fixed-zone"
        raise BrokerError("unknown outcome")

    adapter.order_send.side_effect = send
    try:
        first = gateway.submit(adapter, order(), original_plan_snapshot=source)
        persisted = db.query_one("SELECT payload FROM pre_order_snapshots")["payload"]
        source["signal"]["plan"]["sl"] = 1980.0
        source["analysis"]["zones"][0]["low"] = 1000.0
        assert json.loads(persisted)["original_signal"]["plan"]["sl"] == 1990.0
        assert json.loads(persisted)["analysis"]["zones"][0]["low"] == 1994
        reopened = ExecutionGateway(SimpleNamespace(execution={}), observer)
        again = reopened.submit(adapter, order(), original_plan_snapshot=evidence())
        assert again.order_id == first.order_id
        assert db.query_one("SELECT payload FROM pre_order_snapshots")["payload"] == persisted
        adapter.order_send.assert_called_once()
    finally:
        observer.close()
        db.close()


@pytest.mark.parametrize("change", [
    ("signal", "broker_id", "other"),
    ("signal", "symbol", "EURUSD"),
    ("signal", "action", "SELL"),
    ("plan", "sl", 1991),
    ("analysis", "broker_id", "other"),
])
def test_misattributed_snapshot_refuses_order_before_claim(tmp_path, change):
    db = Database(tmp_path / "refuse.sqlite3")
    adapter = broker()
    source = evidence()
    scope, field, value = change
    if scope == "plan":
        source["signal"]["plan"][field] = value
    else:
        source[scope][field] = value
    try:
        with pytest.raises(BrokerError, match="original plan|original analysis"):
            ExecutionGateway(SimpleNamespace(execution={}), db).submit(
                adapter, order(), original_plan_snapshot=source)
        assert db.query("SELECT * FROM orders") == []
        assert db.query("SELECT * FROM pre_order_snapshots") == []
        adapter.order_send.assert_not_called()
    finally:
        db.close()


def test_snapshot_insert_error_rolls_back_order_claim(tmp_path):
    db = Database(tmp_path / "atomic.sqlite3")
    adapter = broker()
    db.execute("CREATE TRIGGER deny_snapshot BEFORE INSERT ON pre_order_snapshots "
               "BEGIN SELECT RAISE(ABORT,'evidence write failed'); END")
    try:
        with pytest.raises(sqlite3.IntegrityError, match="evidence write failed"):
            ExecutionGateway(SimpleNamespace(execution={}), db).submit(
                adapter, order(), original_plan_snapshot=evidence())
        assert db.query("SELECT * FROM orders") == []
        assert db.query("SELECT * FROM pre_order_snapshots") == []
        adapter.order_send.assert_not_called()
    finally:
        db.close()


def test_direct_gateway_orders_record_request_only_without_invented_zones(tmp_path):
    db = Database(tmp_path / "request.sqlite3")
    try:
        ExecutionGateway(SimpleNamespace(execution={}), db).submit(broker(), order())
        payload = json.loads(db.query_one("SELECT payload FROM pre_order_snapshots")["payload"])
        assert payload["evidence_level"] == "request_only"
        assert payload["original_signal"] is None
        assert payload["analysis"] is None
        assert payload["request"]["sl"] == 1990.0
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE pre_order_snapshots SET payload='{}'")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM pre_order_snapshots")
        assert db.query_one("SELECT payload FROM pre_order_snapshots")["payload"] == json.dumps(
            payload, sort_keys=True, allow_nan=False)
    finally:
        db.close()
