"""Close acknowledgements are not authoritative exposure reads; no real broker I/O."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from integrations.brokers.base import BrokerError
from integrations.brokers.bridge import BridgeBroker
from packages.persistence.db import Database
from packages.shared_schemas.models import OrderResult, OrderState
from services.execution_gateway.gateway import ExecutionGateway


@pytest.mark.parametrize("damage", ["missing_ok", "string_ok", "missing_status", "unknown_status",
                                   "partial", "pending", "foreign_ticket", "missing_ticket",
                                   "missing_volume", "nan_volume", "negative_volume", "too_much_volume"])
def test_bridge_close_requires_explicit_consistent_acknowledgement(damage):
    broker = BridgeBroker.__new__(BridgeBroker)
    reply = {"ok": True, "status": "closed", "ticket": "123", "volume": 0.04, "price": 2000}
    if damage == "missing_ok":
        del reply["ok"]
    elif damage == "string_ok":
        reply["ok"] = "true"
    elif damage == "missing_status":
        del reply["status"]
    elif damage == "unknown_status":
        reply["status"] = "unrecognized"
    elif damage in ("partial", "pending"):
        reply["status"] = damage
    elif damage == "foreign_ticket":
        reply["ticket"] = "456"
    elif damage == "missing_ticket":
        del reply["ticket"]
    elif damage == "missing_volume":
        del reply["volume"]
    else:
        reply["volume"] = {"nan_volume": float("nan"), "negative_volume": -1,
                           "too_much_volume": 0.2}[damage]
    broker._run_command = Mock(return_value=reply)
    with pytest.raises(BrokerError, match="acknowledgement"):
        broker.close_position("123", volume=0.05)
    broker._run_command.assert_called_once()


@pytest.mark.parametrize("status", ["closed", "filled"])
def test_bridge_close_reports_only_receipt_volume_without_verifying_exposure(status):
    broker = BridgeBroker.__new__(BridgeBroker)
    broker._run_command = Mock(return_value={"ok": True, "status": status, "ticket": "123",
                                           "volume": 0.04, "price": 2000, "retcode": 10009})
    result = broker.close_position("123", volume=0.05)
    assert result.status.value == status
    assert result.filled_volume == 0.04
    assert result.verified is False
    assert "closed by" not in result.message
    broker._run_command.assert_called_once()


@pytest.mark.parametrize("volume", [0, -1, float("nan"), float("inf"), True, "0.05"])
def test_bridge_invalid_requested_volume_never_queues(volume):
    broker = BridgeBroker.__new__(BridgeBroker)
    broker._run_command = Mock()
    with pytest.raises(BrokerError, match="volume"):
        broker.close_position("123", volume=volume)
    broker._run_command.assert_not_called()


@pytest.mark.parametrize("reply", [None, [], {"ok": True, "status": []},
                                  {"ok": True, "status": "closed", "ticket": "123", "volume": 0.04,
                                   "price": float("nan")},
                                  {"ok": True, "status": "closed", "ticket": "123", "volume": 0.04,
                                   "price": -1},
                                  {"ok": True, "status": "closed", "ticket": "123", "volume": 0.04,
                                   "price": 2000, "retcode": 10010}])
def test_bridge_malformed_or_conflicting_receipt_is_generic_unknown(reply):
    broker = BridgeBroker.__new__(BridgeBroker)
    broker._run_command = Mock(return_value=reply)
    with pytest.raises(BrokerError, match="unknown"):
        broker.close_position("123", volume=0.05)
    broker._run_command.assert_called_once()


def test_bridge_close_transport_error_does_not_expose_raw_receipt():
    broker = BridgeBroker.__new__(BridgeBroker)
    broker._require_connected = Mock()
    broker.account_id = "fake"
    broker.order_timeout = 1
    broker.relay = Mock()
    broker.relay.enqueue.return_value = SimpleNamespace(id="one", seq=1)
    broker.relay.wait_result.return_value = {"ok": False, "error": "private-account-secret"}
    with pytest.raises(BrokerError) as error:
        broker.close_position("123", volume=0.05)
    assert "private-account-secret" not in str(error.value)
    assert "unknown" in str(error.value)
    broker.relay.enqueue.assert_called_once()


@pytest.mark.parametrize("status", [OrderState.pending, OrderState.submitted, OrderState.partially_filled])
def test_gateway_does_not_turn_unresolved_close_status_into_rejection(tmp_path, status):
    db = Database(tmp_path / "ack.db")
    gateway = ExecutionGateway(SimpleNamespace(execution={}), db)
    broker = Mock(id="demo")
    broker.account_info.return_value = SimpleNamespace(
        broker_id="demo", login="123", server="Demo", currency="USD")
    broker.close_position.return_value = OrderResult(order_id="close", idempotency_key="", status=status)
    try:
        with pytest.raises(BrokerError, match="unknown"):
            gateway.close(broker, "123")
        broker.close_position.assert_called_once()
        assert db.query("SELECT * FROM trades") == []
    finally:
        db.close()


@pytest.mark.parametrize("status,ok", [(OrderState.closed, True), (OrderState.filled, True),
                                     (OrderState.rejected, False), (OrderState.cancelled, False)])
def test_gateway_retains_explicit_terminal_acknowledgements(tmp_path, status, ok):
    db = Database(tmp_path / "ack.db")
    gateway = ExecutionGateway(SimpleNamespace(execution={}), db)
    broker = Mock(id="demo")
    broker.account_info.return_value = SimpleNamespace(
        broker_id="demo", login="123", server="Demo", currency="USD")
    broker.close_position.return_value = OrderResult(order_id="close", idempotency_key="", status=status)
    try:
        result = gateway.close(broker, "123")
        assert result["ok"] is ok
        broker.close_position.assert_called_once()
    finally:
        db.close()