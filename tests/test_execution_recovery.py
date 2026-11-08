"""Repository-local crash/retry tests: no terminal or network connections."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from integrations.brokers.base import BrokerError
from packages.persistence.db import Database
from packages.shared_schemas.models import (
    Direction,
    Health,
    OrderRequest,
    OrderResult,
    OrderState,
)
from services.execution_gateway.gateway import ExecutionGateway


@pytest.fixture
def execution(tmp_path):
    path = str(tmp_path / "orders.sqlite3")
    db = Database(path)
    settings = SimpleNamespace(execution={"verify_after_send": True})
    adapter = Mock()
    adapter.id = "isolated-demo"
    adapter.health.return_value = Health.connected
    adapter.positions.return_value = []
    adapter.order_send.side_effect = BrokerError("transport timeout")
    request = OrderRequest(symbol="XAUUSD", side="buy", volume=0.1, sl=1990, tp=2020,
                           signal_id="signal-1", idempotency_key="key-1", broker_id=adapter.id)
    yield settings, db, adapter, request, path
    db.close()


@pytest.mark.parametrize("positions_fail", [False, True])
def test_restart_does_not_resend_unknown_outcome(execution, positions_fail):
    settings, db, adapter, request, path = execution
    if positions_fail:
        adapter.positions.side_effect = BrokerError("positions unavailable")
    first = ExecutionGateway(settings, db).submit(adapter, request)
    original = dict(db.query_one("SELECT * FROM orders"))
    reopened = Database(path)
    try:
        second = ExecutionGateway(settings, reopened).submit(adapter, request)
        assert adapter.order_send.call_count == 1
        assert second.order_id == first.order_id
        assert dict(db.query_one("SELECT * FROM orders")) == original
    finally:
        reopened.close()


def test_timeout_is_pending_not_confirmed_rejection(execution):
    settings, db, adapter, request, _ = execution
    result = ExecutionGateway(settings, db).submit(adapter, request)
    assert result.status == OrderState.pending
    assert "not resent" in result.message


@pytest.mark.parametrize("patch", [{"volume": 0.2}, {"symbol": "EURUSD"},
                                  {"side": "sell"}, {"sl": 1980}, {"broker_id": "other-demo"}])
def test_key_cannot_be_reused_for_different_intent(execution, patch):
    settings, db, adapter, request, _ = execution
    gateway = ExecutionGateway(settings, db)
    gateway.submit(adapter, request)
    if "broker_id" in patch:
        adapter.id = patch["broker_id"]
    with pytest.raises(BrokerError, match="idempotency"):
        gateway.submit(adapter, OrderRequest(**(request.model_dump() | patch)))
    assert adapter.order_send.call_count == 1


@pytest.mark.parametrize("payload", ["{bad", "[]", '{"request": {}}'])
def test_corrupt_existing_record_never_resends(execution, payload):
    settings, db, adapter, request, _ = execution
    db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?)",
               ("old", 1, request.idempotency_key, "pending", adapter.id, request.symbol, payload))
    with pytest.raises(BrokerError, match="idempotency"):
        ExecutionGateway(settings, db).submit(adapter, request)
    adapter.order_send.assert_not_called()
    assert db.query_one("SELECT payload FROM orders")["payload"] == payload


def recovered_position(adapter, **patch):
    return SimpleNamespace(**({"ticket": "ticket-1", "symbol": "XAUUSD", "direction": Direction.up,
                               "volume": 0.1, "entry": 2000, "signal_id": "signal-1",
                               "broker_id": adapter.id} | patch))


@pytest.mark.parametrize("patch", [{"symbol": "EURUSD"}, {"direction": Direction.down},
                                  {"volume": 0.2}, {"broker_id": "other-demo"}])
def test_same_signal_on_different_position_is_not_recovered(execution, patch):
    settings, db, adapter, request, _ = execution
    gateway = ExecutionGateway(settings, db)
    gateway.submit(adapter, request)
    adapter.positions.return_value = [recovered_position(adapter, **patch)]
    result = gateway.submit(adapter, request)
    assert result.status != OrderState.filled
    assert adapter.order_send.call_count == 1


def test_matching_position_recovers_without_resend(execution):
    settings, db, adapter, request, _ = execution
    gateway = ExecutionGateway(settings, db)
    first = gateway.submit(adapter, request)
    adapter.positions.return_value = [recovered_position(adapter)]
    result = ExecutionGateway(settings, db).submit(adapter, request)
    assert result.status == OrderState.filled
    assert result.verified
    assert result.order_id == first.order_id
    assert adapter.order_send.call_count == 1


def test_two_connections_claim_key_once(execution):
    settings, db, adapter, request, path = execution
    other = Database(path)
    barrier = threading.Barrier(2)
    first, second = ExecutionGateway(settings, db), ExecutionGateway(settings, other)
    # Force both workers to observe absence before either attempts the insert.
    for gateway in (first, second):
        original = gateway._existing

        def initial_read(key, read=original):
            result = read(key)
            if result is None:
                barrier.wait(timeout=5)
            return result

        gateway._existing = initial_read
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda gw: gw.submit(adapter, request), (first, second)))
        assert adapter.order_send.call_count == 1
        assert len({result.order_id for result in results}) == 1
        assert len(db.query("SELECT * FROM orders")) == 1
    finally:
        other.close()


def test_explicit_rejection_is_replayed_without_resend(execution):
    settings, db, adapter, request, _ = execution
    adapter.order_send.side_effect = None
    adapter.order_send.return_value = OrderResult(order_id="adapter-id", idempotency_key="key-1",
                                                 status=OrderState.rejected, message="invalid stops")
    gateway = ExecutionGateway(settings, db)
    first = gateway.submit(adapter, request)
    second = gateway.submit(adapter, request)
    assert first == second
    assert adapter.order_send.call_count == 1
    stored = json.loads(db.query_one("SELECT payload FROM orders")["payload"])
    assert stored["result"]["status"] == "rejected"


def test_crash_after_claim_before_send_stays_reserved(execution):
    settings, db, adapter, request, _ = execution
    db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?)",
               ("claimed", 1, request.idempotency_key, "pending", adapter.id, request.symbol,
                json.dumps({"request": request.model_dump(mode="json")})))
    result = ExecutionGateway(settings, db).submit(adapter, request)
    assert result.order_id == "claimed"
    assert result.status == OrderState.pending
    adapter.order_send.assert_not_called()


def test_ambiguous_matching_positions_stay_pending(execution):
    settings, db, adapter, request, _ = execution
    gateway = ExecutionGateway(settings, db)
    gateway.submit(adapter, request)
    adapter.positions.return_value = [recovered_position(adapter),
                                      recovered_position(adapter, ticket="ticket-2")]
    assert gateway.submit(adapter, request).status == OrderState.pending
    assert adapter.order_send.call_count == 1


def test_corrupt_result_cannot_be_replayed_or_resent(execution):
    settings, db, adapter, request, _ = execution
    gateway = ExecutionGateway(settings, db)
    gateway.submit(adapter, request)
    row = db.query_one("SELECT * FROM orders")
    payload = json.loads(row["payload"])
    payload["result"]["idempotency_key"] = "unrelated-key"
    db.execute("UPDATE orders SET payload=?", (json.dumps(payload),))
    with pytest.raises(BrokerError, match="idempotency"):
        gateway.submit(adapter, request)
    assert adapter.order_send.call_count == 1