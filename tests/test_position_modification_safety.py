import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from packages.persistence.db import Database
from packages.persistence.position_events import PositionEventLog
from packages.shared_schemas.models import Direction, Health, Position, SymbolSpec, Tick
from services.execution_gateway.gateway import ExecutionGateway


@pytest.fixture
def execution(tmp_path):
    db = Database(tmp_path / "position-modification.db")
    adapter = Mock()
    adapter.id = "paper-a"
    adapter.adapter_type = "simulated_mt5"
    adapter.health.return_value = Health.connected
    adapter.account_info.return_value = SimpleNamespace(
        broker_id="paper-a", login="1001", server="Paper", currency="USD")
    current = Position(ticket="T-1", symbol="XAUUSD", direction=Direction.up,
                       volume=0.1, entry=2000, sl=1990, tp=2020,
                       current_price=2000, open_time=1, broker_id="paper-a")
    adapter.positions.side_effect = lambda: [current]
    adapter.symbol_spec.return_value = SymbolSpec(symbol="XAUUSD", point=0.01,
        tick_size=0.01, contract_size=100, stops_level_points=5, freeze_level_points=5)
    adapter.ticker.return_value = Tick(t=time.time(), bid=2000, ask=2000.1,
                                       spread_points=10, last=2000)
    gateway = ExecutionGateway(SimpleNamespace(execution={}), db)
    yield db, adapter, current, gateway
    db.close()


def test_stop_update_is_monotonic_and_broker_snapshot_confirmed(execution):
    db, adapter, current, gateway = execution
    adapter.modify_position.side_effect = lambda ticket, sl, tp: (
        setattr(current, "sl", sl) or setattr(current, "tp", tp) or True)
    assert gateway.modify(adapter, "T-1", sl=1995, reason="paper-test",
                          idempotency_key="paper-modification-key-001") is True
    adapter.modify_position.assert_called_once_with("T-1", sl=1995.0, tp=2020.0)
    intent = db.query_one("SELECT status,requested_sl FROM position_modification_intents")
    assert intent["status"] == "broker_confirmed" and intent["requested_sl"] == 1995
    owner = gateway._assert_account(adapter)
    events = PositionEventLog(db).for_ticket(broker_id="paper-a", ticket="T-1",
                                              account_identity=owner)
    assert [event["status"] for event in events] == ["requested", "broker_confirmed"]


@pytest.mark.parametrize("candidate", [1989.99, 0, float("nan")])
def test_widening_or_removing_sl_is_refused_before_broker_io(execution, candidate):
    _, adapter, _, gateway = execution
    assert gateway.modify(adapter, "T-1", sl=candidate, reason="unsafe-test") is False
    adapter.modify_position.assert_not_called()
    assert gateway.db.query("SELECT * FROM position_modification_intents") == []


def test_unknown_modify_is_not_resent_and_fresh_snapshot_reconciles_it(execution):
    db, adapter, current, gateway = execution
    adapter.modify_position.return_value = True  # adapter ack without broker-state proof
    assert gateway.modify(adapter, "T-1", sl=1995, reason="paper-test",
                          idempotency_key="paper-modification-key-002") is True
    assert db.query_one("SELECT status FROM position_modification_intents")["status"] == "accepted_unverified"

    # A different target cannot create a second command while the first is unresolved.
    assert gateway.modify(adapter, "T-1", sl=1996, reason="second-attempt",
                          idempotency_key="paper-modification-key-003") is False
    adapter.modify_position.assert_called_once()

    # The subsequent broker snapshot is the authority. Reconcile without sending again.
    current.sl = 1995
    assert gateway.modify(adapter, "T-1", sl=1995, reason="paper-test",
                          idempotency_key="paper-modification-key-002") is True
    assert adapter.modify_position.call_count == 1
    assert db.query_one("SELECT status FROM position_modification_intents")["status"] == "broker_confirmed"
