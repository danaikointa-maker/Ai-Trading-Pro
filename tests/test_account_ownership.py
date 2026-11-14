"""Persisted broker alias must never silently move to another account."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from integrations.brokers.base import BrokerError
from packages.persistence.db import Database
from packages.shared_schemas.models import Health, OrderRequest
from services.execution_gateway.gateway import ExecutionGateway


@pytest.fixture
def owned(tmp_path):
    db = Database(tmp_path / "owned.db")
    broker = Mock()
    broker.id = "demo"
    broker.adapter_type = "mt5"
    broker.account_info.return_value = SimpleNamespace(broker_id="demo", login="123", server="Demo", currency="USD")
    broker.health.return_value = Health.connected
    broker.order_send.side_effect = BrokerError("unknown outcome")
    broker.positions.return_value = []
    gateway = ExecutionGateway(SimpleNamespace(execution={}), db)
    request = OrderRequest(symbol="XAUUSD", side="buy", volume=0.1, broker_id="demo", idempotency_key="first")
    yield db, broker, gateway, request
    db.close()


def test_new_claim_persists_account_identity_through_result_write(owned):
    db, broker, gateway, request = owned
    gateway.submit(broker, request)
    payload = json.loads(db.query_one("SELECT payload FROM orders")["payload"])
    assert payload["account_identity"]["login"] == "123"
    assert payload["account_identity"]["server"] == "Demo"
    assert payload["account_identity"]["workspace_id"] == "local"


@pytest.mark.parametrize("field,value", [("login", "456"), ("server", "Other"), ("currency", "JPY")])
def test_same_alias_cannot_replay_or_send_from_changed_account(owned, field, value):
    db, broker, gateway, request = owned
    gateway.submit(broker, request)
    before = dict(db.query_one("SELECT * FROM orders"))
    setattr(broker.account_info.return_value, field, value)
    with pytest.raises(BrokerError, match="account"):
        gateway.submit(broker, request)
    assert dict(db.query_one("SELECT * FROM orders")) == before
    assert broker.order_send.call_count == 1


def test_unknown_account_identity_is_blocked_before_claim(owned):
    db, broker, gateway, request = owned
    broker.account_info.return_value.login = "—"
    with pytest.raises(BrokerError, match="account"):
        gateway.submit(broker, request)
    assert db.query("SELECT * FROM orders") == []
    broker.order_send.assert_not_called()


def test_legacy_unowned_orders_block_first_account_adoption(owned):
    db, broker, gateway, request = owned
    db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?)", ("old", 1, "old", "rejected", "demo", "XAUUSD",
        json.dumps({"request": request.model_dump(mode="json")})))
    before = dict(db.query_one("SELECT * FROM orders"))
    with pytest.raises(BrokerError, match="legacy.*account|account.*legacy"):
        gateway.submit(broker, request)
    assert dict(db.query_one("SELECT * FROM orders")) == before
    broker.order_send.assert_not_called()


@pytest.mark.parametrize("operation", ["modify", "close", "reconcile"])
def test_account_switch_blocks_management_and_snapshot_mutation(owned, operation):
    db, broker, gateway, request = owned
    gateway.submit(broker, request)
    broker.account_info.return_value.login = "456"
    if operation == "reconcile":
        assert gateway.reconcile(broker)["ok"] is False
    elif operation == "modify":
        assert gateway.modify(broker, "1", sl=1900) is False
    else:
        with pytest.raises(BrokerError, match="account"):
            gateway.close(broker, "1")
    broker.modify_position.assert_not_called()
    broker.close_position.assert_not_called()


def test_account_binding_survives_connection_reopen(owned):
    db, broker, gateway, request = owned
    gateway.submit(broker, request)
    other = Database(db.path)
    try:
        broker.account_info.return_value.login = "456"
        with pytest.raises(BrokerError, match="account"):
            ExecutionGateway(SimpleNamespace(execution={}), other).submit(broker, request)
    finally:
        other.close()


def test_corrupt_account_binding_blocks_without_repair(owned):
    db, broker, gateway, request = owned
    gateway.submit(broker, request)
    db.execute("UPDATE kv SET value='broken' WHERE key='account-owner:demo'")
    with pytest.raises(BrokerError, match="account"):
        gateway.submit(broker, request)
    assert db.query_one("SELECT value FROM kv WHERE key='account-owner:demo'")["value"] == "broken"
    assert broker.order_send.call_count == 1


def test_tampered_claim_account_cannot_be_replayed(owned):
    db, broker, gateway, request = owned
    gateway.submit(broker, request)
    payload = json.loads(db.query_one("SELECT payload FROM orders")["payload"])
    payload["account_identity"]["login"] = "456"
    db.execute("UPDATE orders SET payload=?", (json.dumps(payload),))
    with pytest.raises(BrokerError, match="account"):
        gateway.submit(broker, request)
    assert broker.order_send.call_count == 1


def test_account_switch_during_reconcile_cannot_delete_or_accept_snapshot(owned):
    from packages.shared_schemas.models import Position

    db, broker, gateway, request = owned
    gateway.submit(broker, request)
    position = Position(ticket="kept", symbol="XAUUSD", direction="up", volume=0.1,
                        entry=2000, sl=1990, tp=2020, current_price=2000,
                        open_time=1, broker_id=broker.id)
    gateway.open_position_snapshot([position], broker_id=broker.id)
    before = dict(db.query_one("SELECT * FROM open_positions"))

    def switched():
        broker.account_info.return_value.login = "456"
        return []

    broker.positions.side_effect = switched
    result = gateway.reconcile(broker)
    assert result["ok"] is False
    assert "account" in result["error"]
    assert dict(db.query_one("SELECT * FROM open_positions")) == before


def test_tampered_account_claim_remains_unresolved_even_with_verified_result(owned):
    from packages.shared_schemas.models import OrderResult, OrderState

    db, broker, gateway, request = owned
    result = gateway.submit(broker, request)
    gateway._persist_result(result.order_id, OrderResult(order_id=result.order_id, idempotency_key="first",
        status=OrderState.filled, verified=True), request)
    payload = json.loads(db.query_one("SELECT payload FROM orders")["payload"])
    payload["account_identity"]["login"] = "456"
    db.execute("UPDATE orders SET payload=?", (json.dumps(payload),))
    assert gateway.unresolved_orders("demo")


def test_competing_first_account_bindings_have_one_owner_and_release_transaction(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    first = Database(tmp_path / "race.db")
    second = Database(first.path)
    barrier = Barrier(2)

    def bind(db, login):
        broker = Mock()
        broker.id = "demo"
        broker.account_info.return_value = SimpleNamespace(
            broker_id="demo", login=login, server="Demo", currency="USD")
        gateway = ExecutionGateway(SimpleNamespace(execution={}), db)
        barrier.wait(timeout=5)
        try:
            gateway._assert_account(broker)
            return login
        except BrokerError:
            return None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(bind, db, login) for db, login in ((first, "123"), (second, "456"))]
            outcomes = [future.result(timeout=10) for future in futures]
        winners = [login for login in outcomes if login is not None]
        assert len(winners) == 1
        for db in (first, second):
            owner = json.loads(db.query_one("SELECT value FROM kv WHERE key='account-owner:demo'")["value"])
            assert owner["login"] == winners[0]
            # Both the committed winner and rolled-back loser must permit a new transaction.
            with db.cursor() as cur:
                cur.execute("BEGIN IMMEDIATE")
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("operation", ["modify", "close", "send", "fill", "recovery"])
def test_account_switch_during_broker_io_cannot_certify_success(owned, operation):
    from packages.shared_schemas.models import Direction, OrderResult, OrderState

    db, broker, gateway, request = owned
    request = request.model_copy(update={"signal_id": "signal-1"})
    gateway._assert_account(broker)
    position = SimpleNamespace(ticket="ticket-1", symbol=request.symbol, direction=Direction.up,
                               volume=request.volume, entry=2000, signal_id=request.signal_id,
                               broker_id=broker.id)

    def switched(value):
        def read(*args, **kwargs):
            broker.account_info.return_value.login = "456"
            return value
        return read

    if operation == "modify":
        broker.modify_position.side_effect = switched(True)
        assert gateway.modify(broker, "ticket-1", sl=1900) is False
        broker.modify_position.assert_called_once()
    elif operation == "close":
        broker.close_position.side_effect = switched(OrderResult(
            order_id="close", idempotency_key="close", status=OrderState.closed))
        with pytest.raises(BrokerError, match="account"):
            gateway.close(broker, "ticket-1")
        assert db.query("SELECT * FROM trades") == []
        broker.close_position.assert_called_once()
    else:
        if operation == "recovery":
            gateway.submit(broker, request)
            before = dict(db.query_one("SELECT * FROM orders"))
            broker.positions.side_effect = switched([position])
        else:
            ack = OrderResult(order_id="ack", idempotency_key="first", status=OrderState.filled,
                              ticket="ticket-1", filled_volume=0.1, fill_price=2000, verified=True)
            broker.order_send.side_effect = switched(ack) if operation == "send" else None
            broker.order_send.return_value = ack
            broker.positions.side_effect = switched([position]) if operation == "fill" else None
            broker.positions.return_value = [position]
            if operation == "send":
                gateway.verify_after_send = False
        result = gateway.submit(broker, request)
        assert result.status == OrderState.pending
        assert not result.verified
        assert gateway.unresolved_orders(broker.id)
        assert broker.order_send.call_count == 1
        if operation == "recovery":
            assert dict(db.query_one("SELECT * FROM orders")) == before


def test_account_switch_during_close_positions_keeps_trade_and_snapshot_unwritten(owned):
    from packages.shared_schemas.models import Position, TradeRecord

    db, broker, gateway, _ = owned
    gateway._assert_account(broker)
    position = Position(ticket="kept", symbol="XAUUSD", direction="up", volume=0.1,
                        entry=2000, sl=1990, tp=2020, current_price=2001,
                        open_time=1, broker_id=broker.id)
    gateway.open_position_snapshot([position], broker_id=broker.id)
    before = dict(db.query_one("SELECT * FROM open_positions"))
    broker.close_position.return_value = TradeRecord(
        ticket="kept", symbol="XAUUSD", direction="up", volume=0.1, entry=2000,
        exit=2001, opened_at=1, closed_at=2, points=100, gross_pnl=10, costs=0,
        pnl=10, broker_id=broker.id)

    def switched():
        broker.account_info.return_value.login = "456"
        return []

    broker.positions.side_effect = switched
    with pytest.raises(BrokerError, match="account"):
        gateway.close(broker, position.ticket)
    assert db.query("SELECT * FROM trades") == []
    assert dict(db.query_one("SELECT * FROM open_positions")) == before
    broker.close_position.assert_called_once()