"""Broker position polls report changes without certifying fills or attribution."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from packages.persistence.db import Database
from packages.persistence.position_events import PositionEventLog
from packages.shared_schemas.models import Position
from services.api_gateway.state import TradingRuntime
from services.execution_gateway.gateway import ExecutionGateway


def _position(ticket: str = "P-1") -> Position:
    return Position(ticket=ticket, symbol="XAUUSD", direction="up", volume=0.1,
                    entry=2000, sl=1990, tp=2020, open_time=100, current_price=2001,
                    broker_id="demo")


@pytest.fixture
def broker_poll(tmp_path):
    db = Database(tmp_path / "observations.sqlite")
    broker = Mock()
    broker.id = "demo"
    broker.account_info.return_value = SimpleNamespace(
        broker_id="demo", login="123", server="Demo", currency="USD")
    broker.positions.return_value = []
    gateway = ExecutionGateway(SimpleNamespace(execution={}), db)
    identity = gateway._assert_account(broker)
    yield gateway, db, broker, identity
    db.close()


def _observations(db: Database, identity: dict, ticket: str = "P-1") -> list[dict]:
    return [event for event in PositionEventLog(db).for_ticket(
        broker_id="demo", ticket=ticket, account_identity=identity)
        if event["kind"] == "broker_observation"]


def test_sl_tp_and_volume_divergence_are_append_only_and_deduplicated(broker_poll):
    gateway, db, broker, identity = broker_poll
    first = _position()
    gateway.open_position_snapshot([first], broker_id="demo")
    altered = first.model_copy(update={"sl": 1994, "tp": 2030, "volume": 0.05})
    broker.positions.return_value = [altered]
    assert gateway.reconcile(broker)["changed_at_broker"] == [first.ticket]
    assert gateway.reconcile(broker)["observations_added"] == 0
    assert gateway.reconcile(broker)["changed_at_broker"] == [first.ticket]
    recorded = _observations(db, identity)
    assert [e["status"] for e in recorded] == ["changed_unverified"]
    assert recorded[0]["detail"]["changed_fields"] == ["volume", "sl", "tp"]
    assert recorded[0]["detail"]["attribution"] == "unverified_source"
    assert json.loads(db.query_one("SELECT payload FROM open_positions WHERE ticket='P-1'")["payload"])["sl"] == 1990
    broker.positions.return_value = [first]
    assert gateway.reconcile(broker)["ok"] is True
    assert [e["status"] for e in _observations(db, identity)] == [
        "changed_unverified", "baseline_restored"]
    broker.positions.return_value = [altered]
    assert gateway.reconcile(broker)["reconciliation_required"] is True
    assert [e["status"] for e in _observations(db, identity)] == [
        "changed_unverified", "baseline_restored", "changed_unverified"]
    broker.order_send.assert_not_called()
    broker.close_position.assert_not_called()


def test_missing_position_keeps_evidence_until_manual_reconciliation(broker_poll):
    gateway, db, broker, identity = broker_poll
    gateway.open_position_snapshot([_position()], broker_id="demo")
    assert gateway.reconcile(broker)["missing_at_broker"] == ["P-1"]
    assert gateway.reconcile(broker)["missing_at_broker"] == ["P-1"]
    assert db.query_one("SELECT * FROM open_positions WHERE ticket='P-1'") is not None
    events = _observations(db, identity)
    assert len(events) == 1 and events[0]["status"] == "missing_unverified"
    assert events[0]["detail"]["broker"] is None
    broker.close_position.assert_not_called()


def test_unexpected_broker_position_is_not_assumed_to_be_our_order(broker_poll):
    gateway, db, broker, identity = broker_poll
    broker.positions.return_value = [_position("MANUAL-1")]
    assert gateway.reconcile(broker)["unknown_locally"] == ["MANUAL-1"]
    events = _observations(db, identity, "MANUAL-1")
    assert [e["status"] for e in events] == ["unexpected_unverified"]
    assert events[0]["order_id"] is None
    assert events[0]["order_attribution"] == "unresolved"
    assert gateway.reconcile(broker)["ok"] is True
    assert [e["status"] for e in _observations(db, identity, "MANUAL-1")] == [
        "unexpected_unverified", "baseline_restored"]


def test_account_switch_rejects_observation_without_mutating_evidence(broker_poll):
    gateway, db, broker, identity = broker_poll
    gateway.open_position_snapshot([_position()], broker_id="demo")

    def switched():
        broker.account_info.return_value.login = "other-account"
        return []

    broker.positions.side_effect = switched
    assert gateway.reconcile(broker)["ok"] is False
    assert db.query_one("SELECT * FROM open_positions WHERE ticket='P-1'") is not None
    assert _observations(db, identity) == []


def test_two_reconcilers_append_only_one_observation_across_connections(tmp_path):
    db = Database(tmp_path / "shared.sqlite")
    second = Database(db.path)
    try:
        identity = {"broker_id": "demo", "login": "123", "server": "Demo",
                    "currency": "USD", "workspace_id": db.workspace_id}
        detail = {"before": {"sl": 1990}, "broker": {"sl": 1994},
                  "changed_fields": ["sl"], "attribution": "unverified_source"}

        def record(database):
            return PositionEventLog(database).observe_broker(
                broker_id="demo", ticket="P-1", account_identity=identity,
                status="changed_unverified", detail=detail)

        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(record, [db, second]))
        assert sum(event_id is not None for event_id in ids) == 1
        assert len(_observations(db, identity)) == 1
    finally:
        second.close()
        db.close()


def test_foreign_events_block_reconciliation_evidence(broker_poll):
    gateway, db, broker, identity = broker_poll
    gateway.open_position_snapshot([_position()], broker_id="demo")
    PositionEventLog(db).append(broker_id="demo", ticket="P-1", actor="external",
                                kind="modify", status="requested",
                                account_identity={**identity, "login": "other-account"}, detail={})
    status = gateway.reconcile(broker)
    assert status["ok"] is False and "collision" in status["error"]
    assert db.query_one("SELECT * FROM open_positions WHERE ticket='P-1'") is not None


def test_alert_only_when_new_broker_observation_is_persisted(broker_poll):
    gateway, db, broker, _ = broker_poll
    gateway.open_position_snapshot([_position()], broker_id="demo")
    runtime = SimpleNamespace(gateway=gateway, adapter=broker, notifier=Mock())
    TradingRuntime._reconcile_cycle(runtime)
    runtime.notifier.emit.assert_called_once()
    assert runtime.last_reconcile["observations_added"] == 1
    TradingRuntime._reconcile_cycle(runtime)
    runtime.notifier.emit.assert_called_once()
    assert runtime.last_reconcile["observations_added"] == 0
    broker.positions.return_value = [_position()]
    TradingRuntime._reconcile_cycle(runtime)
    assert runtime.notifier.emit.call_count == 2
    assert runtime.notifier.emit.call_args.args[0] == "info"
    assert "restored" in runtime.notifier.emit.call_args.args[1].lower()

