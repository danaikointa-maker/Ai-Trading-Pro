from __future__ import annotations

import pytest
from types import SimpleNamespace
from unittest.mock import Mock
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from packages.shared_schemas.models import Direction, Health, Position, SymbolSpec, Tick
from packages.persistence.db import Database
from packages.persistence.position_events import PositionEventLog
from services.execution_gateway.gateway import ExecutionGateway


def _owner(db: Database, login: str = "123") -> dict[str, str]:
    return {"broker_id": "demo", "login": login, "server": "Connext-Demo",
            "currency": "USD", "workspace_id": db.workspace_id}


def _gateway_case(db: Database, *, account_type="demo", stops_level_points=0):
    adapter = Mock()
    adapter.id = "demo"
    adapter.adapter_type = "mt5"
    adapter.account_info.return_value = SimpleNamespace(
        broker_id="demo", login="123", server="Connext-Demo", currency="USD",
        account_type=account_type)
    adapter.health.return_value = Health.connected
    position = Position(ticket="T-1", broker_id="demo", symbol="XAUUSD",
                        direction=Direction.up, volume=0.1, entry=2000,
                        sl=1990, tp=2020, open_time=1, current_price=2000,
                        points=0)
    adapter.positions.return_value = [position]
    adapter.symbol_spec.return_value = SymbolSpec(
        symbol="XAUUSD", source="broker", spec_complete=True,
        stops_level_points=stops_level_points, freeze_level_points=0)
    adapter.ticker.return_value = Tick(t=time.time(), bid=2000, ask=2000.1,
                                       spread_points=10, last=2000)
    return adapter, ExecutionGateway(SimpleNamespace(execution={}), db)


def test_modify_intent_is_durable_idempotent_and_append_only(tmp_path):
    db = Database(tmp_path / "modify-intents.db")
    log = PositionEventLog(db)
    owner = _owner(db)
    detail = {"sl": 1995.0, "tp": None, "reason": "trailing"}
    try:
        first = log.reserve_modify(broker_id="demo", ticket="T-1",
                                   idempotency_key="intent-1",
                                   account_identity=owner, detail=detail)
        duplicate = log.reserve_modify(broker_id="demo", ticket="T-1",
                                       idempotency_key="intent-1",
                                       account_identity=owner, detail=detail)

        assert first["created"] is True and first["state"] == "reserved"
        assert duplicate["created"] is False and duplicate["state"] == "reserved"
        assert len(log.for_ticket(broker_id="demo", ticket="T-1",
                                  account_identity=owner)) == 1
        with pytest.raises(ValueError, match="another request"):
            log.reserve_modify(broker_id="demo", ticket="T-1",
                               idempotency_key="intent-1", account_identity=owner,
                               detail={**detail, "sl": 1994.0})
    finally:
        db.close()


def test_unresolved_modify_intent_survives_database_reopen(tmp_path):
    path = tmp_path / "modify-restart.db"
    db = Database(path)
    owner = _owner(db)
    log = PositionEventLog(db)
    log.reserve_modify(broker_id="demo", ticket="T-1", idempotency_key="persisted",
                       account_identity=owner, detail={"sl": 1995.0})
    db.close()

    reopened = Database(path)
    try:
        replay = PositionEventLog(reopened).reserve_modify(
            broker_id="demo", ticket="T-1", idempotency_key="persisted",
            account_identity=owner, detail={"sl": 1995.0})
        blocked = PositionEventLog(reopened).reserve_modify(
            broker_id="demo", ticket="T-1", idempotency_key="new-attempt",
            account_identity=owner, detail={"sl": 1996.0})

        assert replay["created"] is False and replay["state"] == "reserved"
        assert blocked["blocked"] is True
    finally:
        reopened.close()


def test_unresolved_intent_fences_other_modifications_for_same_account_ticket(tmp_path):
    db = Database(tmp_path / "modify-fence.db")
    log = PositionEventLog(db)
    owner = _owner(db)
    try:
        log.reserve_modify(broker_id="demo", ticket="T-1", idempotency_key="first",
                           account_identity=owner, detail={"sl": 1995.0})
        blocked = log.reserve_modify(broker_id="demo", ticket="T-1", idempotency_key="second",
                                     account_identity=owner, detail={"sl": 1996.0})

        assert blocked["blocked"] is True
        assert blocked["state"] == "reserved"
        assert blocked["idempotency_key"] == "first"
    finally:
        db.close()


def test_concurrent_connections_reserve_only_one_modify_for_ticket(tmp_path):
    path = tmp_path / "modify-concurrent.db"
    first_db = Database(path)
    second_db = Database(path)
    owner = _owner(first_db)
    barrier = Barrier(2)

    def reserve(db: Database, key: str, stop: float):
        barrier.wait(timeout=3)
        return PositionEventLog(db).reserve_modify(
            broker_id="demo", ticket="T-1", idempotency_key=key,
            account_identity=owner, detail={"sl": stop})

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda args: reserve(*args), [
                (first_db, "worker-a", 1995.0),
                (second_db, "worker-b", 1996.0),
            ]))

        assert sum(result["created"] for result in results) == 1
        assert sum(bool(result.get("blocked")) for result in results) == 1
        assert len(first_db.query("SELECT * FROM position_modify_intents")) == 1
    finally:
        first_db.close()
        second_db.close()


def test_modify_intents_are_isolated_by_account_identity(tmp_path):
    db = Database(tmp_path / "modify-accounts.db")
    log = PositionEventLog(db)
    try:
        first = log.reserve_modify(broker_id="demo", ticket="T-1", idempotency_key="first",
                                   account_identity=_owner(db, "123"), detail={"sl": 1995.0})
        second = log.reserve_modify(broker_id="demo", ticket="T-1", idempotency_key="first",
                                    account_identity=_owner(db, "456"), detail={"sl": 1995.0})

        assert first["created"] is True
        assert second["created"] is True
        assert first["account_fingerprint"] != second["account_fingerprint"]
    finally:
        db.close()


def test_modify_intent_transitions_are_ordered_and_terminal(tmp_path):
    db = Database(tmp_path / "modify-states.db")
    log = PositionEventLog(db)
    owner = _owner(db)
    try:
        log.reserve_modify(broker_id="demo", ticket="T-1", idempotency_key="intent-1",
                           account_identity=owner, detail={"sl": 1995.0})
        assert log.transition_modify(broker_id="demo", ticket="T-1", idempotency_key="intent-1",
                                     account_identity=owner, state="sending")
        assert log.transition_modify(broker_id="demo", ticket="T-1", idempotency_key="intent-1",
                                     account_identity=owner, state="accepted_unverified")
        assert log.transition_modify(broker_id="demo", ticket="T-1", idempotency_key="intent-1",
                                     account_identity=owner, state="confirmed",
                                     detail={"broker_sl": 1995.0})
        assert not log.transition_modify(broker_id="demo", ticket="T-1", idempotency_key="intent-1",
                                         account_identity=owner, state="sending")
        events = log.for_ticket(broker_id="demo", ticket="T-1", account_identity=owner)
        assert [event["status"] for event in events] == [
            "reserved", "sending", "accepted_unverified", "confirmed"]
    finally:
        db.close()


def test_unknown_modify_intent_cannot_be_cleared_without_reconciliation(tmp_path):
    db = Database(tmp_path / "modify-unknown.db")
    log = PositionEventLog(db)
    owner = _owner(db)
    try:
        log.reserve_modify(broker_id="demo", ticket="T-1", idempotency_key="intent-1",
                           account_identity=owner, detail={"sl": 1995.0})
        log.transition_modify(broker_id="demo", ticket="T-1", idempotency_key="intent-1",
                              account_identity=owner, state="sending")
        log.transition_modify(broker_id="demo", ticket="T-1", idempotency_key="intent-1",
                              account_identity=owner, state="unknown")
        blocked = log.reserve_modify(broker_id="demo", ticket="T-1", idempotency_key="intent-2",
                                     account_identity=owner, detail={"sl": 1996.0})

        assert blocked["blocked"] is True and blocked["state"] == "unknown"
    finally:
        db.close()


def test_gateway_does_not_retry_unknown_modify_intent(tmp_path):
    db = Database(tmp_path / "gateway-unknown.db")
    adapter, gateway = _gateway_case(db)
    try:
        assert gateway.modify(adapter, "T-1", sl=1995.0, reason="trailing") is False
        assert gateway.modify(adapter, "T-1", sl=1995.0, reason="trailing") is False

        adapter.modify_position.assert_called_once()
        intent = db.query_one("SELECT state FROM position_modify_intents")
        assert intent["state"] == "unknown"
    finally:
        db.close()


def test_gateway_rejects_live_account_before_modify_or_intent(tmp_path):
    db = Database(tmp_path / "gateway-live.db")
    adapter, gateway = _gateway_case(db, account_type="live")
    try:
        assert gateway.modify(adapter, "T-1", sl=1995.0, reason="trailing") is False

        adapter.modify_position.assert_not_called()
        assert db.query("SELECT * FROM position_modify_intents") == []
    finally:
        db.close()


def test_gateway_rejects_stop_inside_broker_stops_level(tmp_path):
    db = Database(tmp_path / "gateway-stops.db")
    adapter, gateway = _gateway_case(db, stops_level_points=10)
    try:
        assert gateway.modify(adapter, "T-1", sl=1999.95, reason="trailing") is False

        adapter.modify_position.assert_not_called()
        assert db.query("SELECT * FROM position_modify_intents") == []
    finally:
        db.close()


def test_unknown_intent_is_confirmed_by_exact_later_broker_reconciliation(tmp_path):
    import json

    db = Database(tmp_path / "gateway-reconcile.db")
    adapter, gateway = _gateway_case(db)
    before = adapter.positions.return_value[0]
    after = before.model_copy(update={"sl": 1995.0})
    try:
        gateway._assert_account(adapter)
        db.execute("INSERT INTO open_positions(ticket,payload,updated_at) VALUES(?,?,?)",
                   (before.ticket, json.dumps(before.model_dump()), time.time()))
        adapter.modify_position.return_value = False
        assert gateway.modify(adapter, "T-1", sl=1995.0, reason="trailing") is False
        assert db.query_one("SELECT state FROM position_modify_intents")["state"] == "unknown"

        adapter.positions.return_value = [after]
        assert gateway.modify(adapter, "T-1", sl=1995.0, reason="trailing") is True
        assert db.query_one("SELECT state FROM position_modify_intents")["state"] == "confirmed"
        result = gateway.reconcile(adapter)

        assert result["ok"] is True
        assert result["changed_at_broker"] == []
        assert db.query_one("SELECT state FROM position_modify_intents")["state"] == "confirmed"
        saved = json.loads(db.query_one("SELECT payload FROM open_positions WHERE ticket='T-1'")["payload"])
        assert saved["sl"] == 1995.0
    finally:
        db.close()


def test_confirmed_modify_updates_account_snapshot_without_false_external_change(tmp_path):
    import json

    db = Database(tmp_path / "gateway-snapshot.db")
    adapter, gateway = _gateway_case(db)
    before = adapter.positions.return_value[0]
    after = before.model_copy(update={"sl": 1995.0})
    try:
        owner = gateway._assert_account(adapter)
        db.execute("INSERT INTO open_positions(ticket,payload,updated_at) VALUES(?,?,?)",
                   (before.ticket, json.dumps(before.model_dump()), time.time()))
        adapter.positions.side_effect = [[before], [after]]
        adapter.modify_position.return_value = True

        assert gateway.modify(adapter, "T-1", sl=1995.0, reason="trailing") is True
        observations = gateway.open_position_snapshot(
            [after], broker_id="demo", account_identity=owner, retain_unverified=True)

        assert observations == []
        saved = json.loads(db.query_one("SELECT payload FROM open_positions WHERE ticket='T-1'")["payload"])
        assert saved["sl"] == 1995.0
        assert db.query("SELECT * FROM position_events WHERE kind='broker_observation'") == []
    finally:
        db.close()
