"""History gateway evidence is account-bound, including authoritative empty batches."""
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from integrations.brokers.base import BrokerError
from packages.persistence.db import Database
from services.execution_gateway.gateway import ExecutionGateway


@pytest.fixture
def history(tmp_path):
    db = Database(tmp_path / "history.db")
    broker = Mock()
    broker.id = "demo"
    identity = {"broker_id": "demo", "login": "123", "server": "Demo", "currency": "USD"}
    broker.account_info.return_value = SimpleNamespace(**identity)
    deal = {"deal_id": "1", "order_id": "10", "position_id": "100", "broker_id": "demo",
            "account_key": "Demo:123", "currency": "USD", "symbol": "XAUUSD", "side": "buy",
            "entry": "in", "volume": 0.1, "price": 2000, "time_msc": 1000}
    batch = {"broker_id": "demo", "account_key": "Demo:123", "account_identity": identity,
             "date_from": 0, "date_to": 10, "deals": [deal]}
    broker.deal_history.return_value = batch
    gateway = ExecutionGateway(SimpleNamespace(execution={}), db)
    yield db, broker, gateway, batch
    broker.order_send.assert_not_called()
    assert db.query("SELECT * FROM orders") == []
    db.close()


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("damage", ["identity", "key", "currency", "missing"])
def test_history_rejects_foreign_or_missing_account_evidence_before_ingest(history, damage, empty):
    db, broker, gateway, batch = history
    if empty:
        batch["deals"] = []
    if damage == "identity":
        batch["account_identity"] = {**batch["account_identity"], "login": "456"}
    elif damage == "key":
        batch["account_key"] = "Other:456"
        for deal in batch["deals"]:
            deal["account_key"] = batch["account_key"]
    elif damage == "currency":
        batch["account_identity"] = {**batch["account_identity"], "currency": "JPY"}
    else:
        del batch["account_identity"]
    with pytest.raises(BrokerError, match="history.*(account|identity)"):
        gateway.refresh_history(broker, 0, 10)
    assert db.query("SELECT * FROM broker_deals") == []


def test_history_mixed_currency_discards_whole_batch(history):
    db, broker, gateway, batch = history
    batch["deals"].append({**batch["deals"][0], "deal_id": "2", "currency": "JPY"})
    with pytest.raises(BrokerError, match="history.*(account|currency)"):
        gateway.refresh_history(broker, 0, 10)
    assert db.query("SELECT * FROM broker_deals") == []


def test_history_account_switch_during_read_preserves_ledger(history):
    db, broker, gateway, batch = history
    gateway.refresh_history(broker, 0, 10)
    before = [dict(row) for row in db.query("SELECT * FROM broker_deals")]

    def switched(*args):
        broker.account_info.return_value.login = "456"
        return {**deepcopy(batch), "deals": []}

    broker.deal_history.side_effect = switched
    with pytest.raises(BrokerError, match="account"):
        gateway.refresh_history(broker, 0, 10)
    assert [dict(row) for row in db.query("SELECT * FROM broker_deals")] == before


def test_history_bound_alias_switch_blocks_reader(history):
    _, broker, gateway, _ = history
    gateway.refresh_history(broker, 0, 10)
    broker.account_info.return_value.login = "456"
    broker.deal_history.reset_mock()
    with pytest.raises(BrokerError, match="account"):
        gateway.refresh_history(broker, 0, 10)
    broker.deal_history.assert_not_called()


@pytest.mark.parametrize("empty", [False, True])
def test_history_matching_identity_is_idempotent_and_does_not_create_claims(history, empty):
    db, broker, gateway, batch = history
    if empty:
        batch["deals"] = []
    first = gateway.refresh_history(broker, 0, 10)
    assert first["inserted"] == (0 if empty else 1)
    assert first["auto_resolved"] is False
    assert gateway.refresh_history(broker, 0, 10)["inserted"] == 0
    assert db.kv_get("account-owner:demo")["login"] == "123"


def test_history_ingestion_does_not_resolve_existing_pending_claim(history):
    db, broker, gateway, _batch = history
    gateway._assert_account(broker)
    payload = json.dumps({"request": {"symbol": "XAUUSD"}, "account_identity":
                          db.kv_get("account-owner:demo")})
    db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?)",
               ("pending", 1, "retained", "pending", broker.id, "XAUUSD", payload))
    before = dict(db.query_one("SELECT * FROM orders"))
    try:
        assert gateway.refresh_history(broker, 0, 10)["inserted"] == 1
        assert dict(db.query_one("SELECT * FROM orders")) == before
    finally:
        # The fixture separately asserts that no new claims were created.
        db.execute("DELETE FROM orders WHERE id='pending'")