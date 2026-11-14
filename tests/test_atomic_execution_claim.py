"""Real SQLite contention; mocked broker never opens a terminal or connection."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from integrations.brokers.base import BrokerError
from packages.persistence.db import Database
from packages.shared_schemas.models import Health, OrderRequest, OrderResult, OrderState
from services.execution_gateway.gateway import ExecutionGateway


def adapter(broker_id="demo"):
    broker = Mock()
    broker.id = broker_id
    broker.account_info.return_value = SimpleNamespace(broker_id=broker_id, login="123", server="Demo", currency="USD")
    broker.health.return_value = Health.connected
    broker.positions.return_value = []
    broker.order_send.side_effect = BrokerError("unknown transport outcome")
    return broker


def request(key="key-1", broker_id="demo"):
    return OrderRequest(symbol="XAUUSD", side="buy", volume=0.1, sl=1990, tp=2020,
                        broker_id=broker_id, idempotency_key=key, signal_id=key)


def test_claim_rechecks_unresolved_after_acquiring_write_lock(tmp_path):
    path = tmp_path / "orders.sqlite3"
    writer, contender = Database(path), Database(path)
    broker = adapter()
    gateway = ExecutionGateway(SimpleNamespace(execution={}), contender)
    gateway._assert_account(broker)
    attempted = threading.Event()

    def trace(sql):
        if sql.startswith("BEGIN IMMEDIATE") or sql.startswith("INSERT INTO orders"):
            attempted.set()

    contender._conn.set_trace_callback(trace)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with writer.cursor() as cur:
                cur.execute("BEGIN IMMEDIATE")
                future = pool.submit(gateway.submit, broker, request("second"))
                assert attempted.wait(5), "contender never attempted the claim"
                first = request("first")
                cur.execute("INSERT INTO orders(id, created_at, idempotency_key, state, broker_id, symbol, payload) VALUES(?,?,?,?,?,?,?)",
                            ("first-order", 1, "first", "pending", "demo", "XAUUSD",
                             json.dumps({"request": first.model_dump()}, default=str)))
            with pytest.raises(BrokerError, match="unresolved"):
                future.result(timeout=10)
        broker.order_send.assert_not_called()
        assert len(writer.query("SELECT * FROM orders")) == 1
    finally:
        contender.close()
        writer.close()


def test_pending_claim_committed_before_adapter_and_restart_keeps_block(tmp_path):
    path = tmp_path / "orders.sqlite3"
    db, observer = Database(path), Database(path)
    broker = adapter()

    def send(*args, **kwargs):
        assert observer.query_one("SELECT state FROM orders")["state"] == "pending"
        # A second connection can write while broker I/O is in progress.
        observer.kv_set("during-send", True)
        raise BrokerError("unknown outcome")

    broker.order_send.side_effect = send
    settings = SimpleNamespace(execution={})
    try:
        first = ExecutionGateway(settings, db).submit(broker, request())
        assert first.status == OrderState.pending
        replay = ExecutionGateway(settings, observer).submit(broker, request())
        assert replay.order_id == first.order_id
        with pytest.raises(BrokerError, match="unresolved"):
            ExecutionGateway(settings, observer).submit(broker, request("new"))
        assert broker.order_send.call_count == 1
        other = adapter("other")
        ExecutionGateway(settings, observer).submit(other, request("other-key", "other"))
        assert other.order_send.call_count == 1
    finally:
        observer.close()
        db.close()


def test_different_keys_racing_on_two_connections_only_admit_one(tmp_path):
    path = tmp_path / "race.sqlite3"
    databases = [Database(path), Database(path)]
    broker = adapter()
    gateways = [ExecutionGateway(SimpleNamespace(execution={}), db) for db in databases]
    barrier = threading.Barrier(2)
    for gateway in gateways:
        original = gateway._existing

        def read(key, original=original):
            result = original(key)
            if result is None:
                barrier.wait(timeout=5)
            return result

        gateway._existing = read

    def submit(index):
        try:
            return gateways[index].submit(broker, request(f"key-{index}"))
        except BrokerError as exc:
            assert "unresolved" in str(exc)
            return None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, range(2)))
        assert sum(result is not None for result in results) == 1
        assert broker.order_send.call_count == 1
        assert len(databases[0].query("SELECT * FROM orders")) == 1
    finally:
        for db in databases:
            db.close()


def test_claim_lock_timeout_does_not_send_or_remove_another_claim(tmp_path):
    import sqlite3

    path = tmp_path / "locked.sqlite3"
    writer, contender = Database(path), Database(path)
    contender._conn.execute("PRAGMA busy_timeout=1")
    broker = adapter()
    try:
        with writer.cursor() as cur:
            cur.execute("BEGIN IMMEDIATE")
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                ExecutionGateway(SimpleNamespace(execution={}), contender).submit(broker, request())
        broker.order_send.assert_not_called()
        assert contender.query("SELECT * FROM orders") == []
        # Failed transaction must leave the connection usable.
        ExecutionGateway(SimpleNamespace(execution={}), contender).submit(broker, request())
        assert broker.order_send.call_count == 1
    finally:
        contender.close()
        writer.close()


def test_audit_failure_after_claim_does_not_reopen_admission(tmp_path, monkeypatch):
    db = Database(tmp_path / "audit.sqlite3")
    broker = adapter()
    gateway = ExecutionGateway(SimpleNamespace(execution={}), db)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(db, "audit", Mock(side_effect=RuntimeError("audit unavailable")))
            with pytest.raises(RuntimeError, match="audit unavailable"):
                gateway.submit(broker, request())
        assert db.query_one("SELECT state FROM orders")["state"] == "pending"
        with pytest.raises(BrokerError, match="unresolved"):
            gateway.submit(broker, request("new"))
        assert gateway.submit(broker, request()).status == OrderState.pending
        broker.order_send.assert_not_called()
    finally:
        db.close()


@pytest.mark.parametrize("damage", ["result-order", "result-key", "request-broker", "request-key", "request-symbol"])
def test_corrupt_resolved_identity_cannot_unblock_new_claim(tmp_path, damage):
    db = Database(tmp_path / "corrupt.sqlite3")
    broker = adapter()
    gateway = ExecutionGateway(SimpleNamespace(execution={}), db)
    try:
        first = gateway.submit(broker, request())
        result = OrderResult(order_id=first.order_id, idempotency_key="key-1", status=OrderState.rejected)
        payload = {"request": request().model_dump(), "result": result.model_dump()}
        if damage == "result-order":
            payload["result"]["order_id"] = "another-order"
        elif damage == "result-key":
            payload["result"]["idempotency_key"] = "another-key"
        elif damage == "request-broker":
            payload["request"]["broker_id"] = "other"
        elif damage == "request-key":
            payload["request"]["idempotency_key"] = "another-key"
        else:
            payload["request"]["symbol"] = "EURUSD"
        db.execute("UPDATE orders SET state='rejected', payload=?", (json.dumps(payload, default=str),))
        with pytest.raises(BrokerError, match="unresolved"):
            gateway.submit(broker, request("new"))
        assert broker.order_send.call_count == 1
    finally:
        db.close()