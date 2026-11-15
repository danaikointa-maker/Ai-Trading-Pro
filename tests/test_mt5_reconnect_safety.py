"""Offline disconnect/reconnect acceptance: no broker send on uncertainty.

These are simulated adapter tests, not proof of a real MT5 Demo terminal.
"""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from integrations.brokers.base import BrokerError
from packages.persistence.db import Database
from packages.shared_schemas.models import Health, OrderRequest, OrderState
from services.execution_gateway.gateway import ExecutionGateway


@pytest.fixture
def environment(tmp_path):
    db = Database(str(tmp_path / "reconnect.sqlite3"))
    adapter = Mock()
    adapter.id = "demo"
    adapter.account_info.return_value = SimpleNamespace(
        broker_id="demo", login="123", server="Demo", currency="USD")
    adapter.health.return_value = Health.connected
    adapter.positions.return_value = []
    adapter.order_send.side_effect = BrokerError("connection dropped after send")
    request = OrderRequest(symbol="XAUUSD", side="buy", volume=0.1,
                           sl=1990, tp=2020, signal_id="sig-1",
                           broker_id="demo", idempotency_key="intent-1")
    settings = SimpleNamespace(execution={"verify_after_send": True})
    yield db, adapter, request, settings
    db.close()


def test_disconnected_broker_refuses_claim_and_send(environment):
    db, adapter, request, settings = environment
    adapter.health.return_value = Health.disconnected
    with pytest.raises(BrokerError, match="refusing to send"):
        ExecutionGateway(settings, db).submit(adapter, request)
    adapter.order_send.assert_not_called()
    assert db.query("SELECT * FROM orders") == []


def test_unknown_send_blocks_new_key_after_reconnect_and_database_restart(environment):
    db, adapter, request, settings = environment
    first = ExecutionGateway(settings, db).submit(adapter, request)
    assert first.status == OrderState.pending
    adapter.health.return_value = Health.disconnected
    with pytest.raises(BrokerError, match="refusing to send"):
        ExecutionGateway(settings, db).submit(adapter, request)
    adapter.health.return_value = Health.connected
    reopened = Database(db.path)
    try:
        gateway = ExecutionGateway(settings, reopened)
        repeat = gateway.submit(adapter, request)
        assert repeat.order_id == first.order_id
        assert repeat.status == OrderState.pending
        with pytest.raises(BrokerError, match="unresolved"):
            gateway.submit(adapter, request.model_copy(
                update={"idempotency_key": "intent-2"}))
        assert adapter.order_send.call_count == 1
        stored = json.loads(reopened.query_one("SELECT payload FROM orders")["payload"])
        assert stored["result"]["status"] == "pending"
    finally:
        reopened.close()


def test_reconnect_with_unavailable_positions_does_not_infer_rejection(environment):
    db, adapter, request, settings = environment
    gateway = ExecutionGateway(settings, db)
    gateway.submit(adapter, request)
    adapter.positions.side_effect = BrokerError("history unavailable after reconnect")
    repeated = gateway.submit(adapter, request)
    assert repeated.status == OrderState.pending
    assert gateway.unresolved_orders(adapter.id)
    assert adapter.order_send.call_count == 1


def test_account_switch_on_reconnect_never_reuses_claim(environment):
    db, adapter, request, settings = environment
    gateway = ExecutionGateway(settings, db)
    gateway.submit(adapter, request)
    adapter.account_info.return_value.login = "456"
    with pytest.raises(BrokerError, match="account"):
        gateway.submit(adapter, request)
    assert gateway.unresolved_orders("demo")
    assert adapter.order_send.call_count == 1
