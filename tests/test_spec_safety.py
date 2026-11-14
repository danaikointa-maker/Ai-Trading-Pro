"""No account-currency valuation from invented specs or unresolved currencies."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from integrations.brokers.bridge import BridgeBroker
from integrations.brokers.fx import resolve_quote_rate
from integrations.brokers.mt5_live import MT5Broker
from integrations.brokers.base import BrokerError
from packages.persistence.db import Database
from packages.shared_schemas.models import SymbolSpec
from services.risk_engine.engine import RiskEngine
from services.risk_engine.planner import PlanInputs, TradePlanner


@pytest.mark.parametrize("patch", [
    {"contract_size": 0}, {"point": float("nan")}, {"tick_size": 0},
    {"min_lot": -1}, {"max_lot": 0.001}, {"lot_step": float("inf")},
    {"quote_to_account_rate": 0}, {"rate_source": "unknown"},
    {"profit_currency": "JPY"}, {"profit_currency": ""},
    {"account_currency": ""}, {"quote_to_account_rate": 2, "rate_source": "identity"},
])
def test_invalid_spec_blocks_sizing(patch):
    assert SymbolSpec(symbol="TEST", **patch).sizing_blocked


def test_non_usd_identity_currency_is_supported():
    spec = SymbolSpec(symbol="EURJPY", profit_currency="JPY", account_currency="JPY")
    assert spec.quote_in_account_currency
    assert not spec.sizing_blocked


@pytest.mark.parametrize("price", [float("inf"), float("nan"), -1, 0])
def test_fx_never_accepts_nonfinite_rate(price):
    rate, source = resolve_quote_rate("JPY", "EUR", lambda _: price)
    assert (rate, source) == (1.0, "unknown")


def test_fx_inverse_overflow_is_unknown():
    assert resolve_quote_rate("JPY", "EUR", lambda name: 1e-320 if name == "EURJPY" else None) == (1.0, "unknown")


@pytest.mark.parametrize("account", [None, SimpleNamespace(currency=""), RuntimeError("offline")])
def test_mt5_does_not_assume_usd_when_account_is_unavailable(monkeypatch, account):
    import integrations.brokers.mt5_live as module

    api = Mock()
    if isinstance(account, Exception):
        api.account_info.side_effect = account
    else:
        api.account_info.return_value = account
    monkeypatch.setattr(module, "mt5", api)
    assert MT5Broker({"id": "fake"})._quote_rate("USD") == (1.0, "unknown")
    api.symbol_info_tick.assert_not_called()


def test_bridge_partial_spec_is_visible_but_not_sizable():
    relay = Mock()
    relay.snapshot.return_value = {"symbols": {"XAUUSD": {"point": 0.01}},
                                  "account": {"currency": "USD"}}
    spec = BridgeBroker({"id": "fake"}, relay, order_timeout=1).symbol_spec("XAUUSD")
    assert spec.sizing_blocked
    assert not spec.spec_complete


def test_bridge_does_not_reuse_usd_rate_for_eur_account():
    relay = Mock()
    relay.snapshot.return_value = {"symbols": {}, "account": {"currency": "EUR"}}
    declared = {"digits": 2, "point": 0.01, "tick_size": 0.01, "contract_size": 100,
                "min_lot": 0.01, "max_lot": 50, "lot_step": 0.01, "profit_currency": "USD"}
    spec = BridgeBroker({"id": "fake", "symbols": {"XAUUSD": declared}}, relay,
                        order_timeout=1).symbol_spec("XAUUSD")
    assert spec.account_currency == "EUR"
    assert spec.sizing_blocked


def test_mt5_broker_spec_keeps_actual_account_currency(monkeypatch):
    import integrations.brokers.mt5_live as module

    api = Mock()
    api.account_info.return_value = SimpleNamespace(currency="JPY")
    api.symbol_info.return_value = SimpleNamespace(
        visible=True, currency_profit="JPY", currency_base="JPY", description="test",
        digits=3, point=0.001, trade_tick_size=0.001, trade_contract_size=100000,
        volume_min=0.01, volume_max=50, volume_step=0.01, trade_stops_level=0,
        trade_freeze_level=0, spread=10, swap_mode=0, swap_long=0, swap_short=0)
    monkeypatch.setattr(module, "mt5", api)
    monkeypatch.setattr(module, "MT5_AVAILABLE", True)
    broker = MT5Broker({"id": "fake"})
    broker._connected = True
    spec = broker.symbol_spec("EURJPY")
    assert spec.account_currency == "JPY"
    assert not spec.sizing_blocked


def test_mt5_partial_offline_metadata_is_not_sizable():
    spec = MT5Broker({"id": "fake", "symbols": {"XAUUSD": {"point": 0.01}}}).symbol_spec("XAUUSD")
    assert not spec.spec_complete
    assert spec.sizing_blocked


def test_risk_rejects_spec_in_another_account_currency(settings, tmp_path):
    db = Database(tmp_path / "risk.sqlite3")
    adapter = Mock()
    adapter.account_info.return_value = SimpleNamespace(balance=10000.0, equity=10000.0, currency="EUR")
    adapter.positions.return_value = [SimpleNamespace(symbol="XAUUSD", current_price=2000,
                                                     volume=0.1, unrealized=0)]
    adapter.symbol_spec.return_value = SymbolSpec(symbol="XAUUSD", account_currency="USD")
    try:
        with pytest.raises(BrokerError, match="exposure"):
            RiskEngine(settings, db).state(adapter)
        assert db.kv_get("peak_equity") is None
    finally:
        db.close()


def test_planner_refuses_invalid_spec_before_division(settings):
    from packages.shared_schemas.models import Direction

    planner = TradePlanner(settings.risk_cfg())
    result = planner.build(PlanInputs(direction=Direction.up, entry=2000,
        spec=SymbolSpec(symbol="XAUUSD", point=0), atr_points=200, equity=10000,
        risk_pct=0.5, spread_points=25, supports=[], resistances=[]))
    assert result.plan is None
    assert result.blockers


def test_complete_bridge_spec_uses_declared_cross_rate_only_for_its_currency():
    relay = Mock()
    relay.snapshot.return_value = {"symbols": {}, "account": {"currency": "EUR"}}
    raw = {"digits": 3, "point": 0.001, "tick_size": 0.001, "contract_size": 100000,
           "min_lot": 0.01, "max_lot": 50, "lot_step": 0.01, "profit_currency": "JPY",
           "account_currency": "EUR", "quote_to_account_rate": 0.006, "rate_source": "ticker"}
    spec = BridgeBroker({"id": "fake", "symbols": {"EURJPY": raw}}, relay,
                        order_timeout=1).symbol_spec("EURJPY")
    assert spec.spec_complete
    assert spec.source == "declared"
    assert not spec.sizing_blocked
    assert spec.pnl_in_account_currency(1, 1) == 600


def test_risk_missing_account_currency_is_blocked(settings, tmp_path):
    db = Database(tmp_path / "risk.sqlite3")
    adapter = Mock()
    adapter.account_info.return_value = SimpleNamespace(balance=10000, equity=10000)
    try:
        with pytest.raises(BrokerError, match="account currency missing"):
            RiskEngine(settings, db).state(adapter)
        adapter.positions.assert_not_called()
        assert db.kv_get("peak_equity") is None
    finally:
        db.close()