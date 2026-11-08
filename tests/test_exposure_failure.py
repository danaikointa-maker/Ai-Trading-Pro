"""Unknown exposure is not zero exposure. All adapters here are isolated fakes."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from integrations.brokers.base import BrokerError
from integrations.brokers.mt5_live import MT5Broker
from packages.persistence.db import Database
from packages.shared_schemas.models import SymbolSpec
from services.risk_engine.engine import RiskEngine


def position(**patch):
    return SimpleNamespace(**({"symbol": "XAUUSD", "volume": 0.1, "entry": 2000.0,
                               "current_price": 2000.0, "unrealized": 0.0} | patch))


@pytest.mark.parametrize("failure", ["raises", "rate", "contract", "price", "volume", "overflow"])
def test_incomplete_notional_is_rejected(failure):
    spec = SymbolSpec(symbol="XAUUSD")
    adapter = Mock()
    adapter.symbol_spec.return_value = spec
    pos = position()
    if failure == "raises":
        adapter.symbol_spec.side_effect = RuntimeError("spec unavailable")
    elif failure == "rate":
        spec.profit_currency, spec.rate_source = "JPY", "unknown"
    elif failure == "contract":
        spec.contract_size = 0.0
    elif failure == "price":
        pos.current_price = float("nan")
    elif failure == "volume":
        pos.volume = -1.0
    else:
        spec.contract_size = 1e308
    with pytest.raises(BrokerError, match="exposure"):
        RiskEngine._notional(adapter, [pos])


def test_state_reads_positions_once(settings, tmp_path):
    db = Database(str(tmp_path / "risk.sqlite3"))
    adapter = Mock()
    adapter.account_info.return_value = SimpleNamespace(balance=10000.0, equity=10000.0)
    adapter.positions.side_effect = [[position()], RuntimeError("second read is inconsistent")]
    adapter.symbol_spec.return_value = SymbolSpec(symbol="XAUUSD")
    try:
        state = RiskEngine(settings, db).state(adapter)
        assert state.open_lots == 0.1
        adapter.positions.assert_called_once()
    finally:
        db.close()


def test_invalid_persisted_peak_cannot_be_written_back(settings, tmp_path):
    db = Database(str(tmp_path / "risk.sqlite3"))
    db.kv_set("peak_equity", "Infinity")
    adapter = Mock()
    adapter.account_info.return_value = SimpleNamespace(balance=10000.0, equity=10000.0)
    adapter.positions.return_value = []
    try:
        with pytest.raises(BrokerError, match="exposure"):
            RiskEngine(settings, db).state(adapter, now=0)
        assert db.kv_get("peak_equity") == "Infinity"
    finally:
        db.close()


def test_failed_positions_read_never_updates_peak(settings, tmp_path):
    db = Database(str(tmp_path / "risk.sqlite3"))
    adapter = Mock()
    adapter.account_info.return_value = SimpleNamespace(balance=10000.0, equity=10000.0)
    adapter.positions.side_effect = RuntimeError("positions unavailable")
    try:
        with pytest.raises(RuntimeError, match="positions unavailable"):
            RiskEngine(settings, db).state(adapter)
        assert db.kv_get("peak_equity", None) is None
    finally:
        db.close()


def test_mt5_positions_none_is_failure_not_empty(monkeypatch):
    import integrations.brokers.mt5_live as module

    monkeypatch.setattr(module, "mt5", SimpleNamespace(positions_get=lambda: None,
                                                      last_error=lambda: (-1, "unavailable")))
    broker = MT5Broker({"id": "fake"})
    broker._connected = True
    with pytest.raises(BrokerError, match="positions_get"):
        broker.positions()


def test_bridge_missing_positions_is_failure(monkeypatch):
    from integrations.brokers.bridge import BridgeBroker

    broker = BridgeBroker({"id": "fake"}, Mock(), order_timeout=1)
    monkeypatch.setattr(broker, "_snapshot", lambda: {"account": {}})
    with pytest.raises(BrokerError, match="positions"):
        broker.positions()


def test_bridge_unknown_symbol_never_inherits_gold_defaults():
    from integrations.brokers.bridge import BridgeBroker

    relay = Mock()
    relay.snapshot.return_value = {"symbols": {}}
    broker = BridgeBroker({"id": "fake"}, relay, order_timeout=1)
    with pytest.raises(BrokerError, match="spec"):
        broker.symbol_spec("UNKNOWN")


def test_empty_positions_are_valid_for_both_adapters(monkeypatch):
    import integrations.brokers.mt5_live as module
    from integrations.brokers.bridge import BridgeBroker

    monkeypatch.setattr(module, "mt5", SimpleNamespace(positions_get=lambda: ()))
    mt5 = MT5Broker({"id": "fake"})
    mt5._connected = True
    assert mt5.positions() == []
    bridge = BridgeBroker({"id": "fake"}, Mock(), order_timeout=1)
    monkeypatch.setattr(bridge, "_snapshot", lambda: {"positions": []})
    assert bridge.positions() == []


@pytest.mark.parametrize("field", ["balance", "equity", "unrealized"])
def test_nonfinite_account_or_floating_cannot_mutate_peak(settings, tmp_path, field):
    db = Database(str(tmp_path / "risk.sqlite3"))
    adapter = Mock()
    account = SimpleNamespace(balance=10000.0, equity=10000.0)
    pos = position()
    setattr(pos if field == "unrealized" else account, field, float("nan"))
    adapter.account_info.return_value = account
    adapter.positions.return_value = [pos]
    adapter.symbol_spec.return_value = SymbolSpec(symbol="XAUUSD")
    try:
        with pytest.raises(BrokerError, match="exposure"):
            RiskEngine(settings, db).state(adapter)
        assert db.kv_get("peak_equity", None) is None
    finally:
        db.close()