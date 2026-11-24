"""MT5 order preflight tests use a fake terminal; no broker command is sent."""
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from integrations.brokers import mt5_live
from packages.shared_schemas.models import (
    OrderRequest,
    OrderSide,
    OrderState,
    SymbolSpec,
    Tick,
)


@pytest.fixture
def preflight_terminal(monkeypatch):
    api = Mock()
    api.account_info.return_value = SimpleNamespace(
        login=123, server="Demo", currency="USD", margin_free=1000.0)
    api.symbol_info_tick.return_value = SimpleNamespace(bid=1999.9, ask=2000.0)
    api.order_calc_profit.return_value = -10.0
    api.order_calc_margin.return_value = 100.0
    api.order_check.return_value = SimpleNamespace(retcode=0, margin_free=900.0, comment="Done")
    api.order_send.return_value = SimpleNamespace(
        retcode=10009, order=99, volume=0.1, price=2000.0, comment="Done")
    for name, value in {
        "TRADE_ACTION_DEAL": 1,
        "ORDER_TYPE_BUY": 0,
        "ORDER_TYPE_SELL": 1,
        "ORDER_TIME_GTC": 0,
        "ORDER_FILLING_IOC": 1,
        "TRADE_RETCODE_DONE": 10009,
    }.items():
        setattr(api, name, value)

    monkeypatch.setattr(mt5_live, "mt5", api)
    monkeypatch.setattr(mt5_live, "MT5_AVAILABLE", True)
    broker = mt5_live.MT5Broker({"id": "demo", "symbols": {}}, login=123, server="Demo")
    broker._connected = True
    broker.symbol_spec = Mock(return_value=SymbolSpec(
        symbol="XAUUSD", digits=2, point=0.01, tick_size=0.01,
        contract_size=100, min_lot=0.01, max_lot=50, lot_step=0.01,
        stops_level_points=50, freeze_level_points=80,
        profit_currency="USD", account_currency="USD", source="broker"))
    broker.ticker = Mock(return_value=Tick(
        t=1000, bid=1999.9, ask=2000.0, spread_points=10, last=1999.9))
    broker._filling_mode = Mock(return_value=1)
    request = OrderRequest(
        symbol="XAUUSD", side=OrderSide.buy, volume=0.1,
        sl=1999.0, tp=2002.0, signal_id="sig-1",
        idempotency_key="intent-1", broker_id="demo")
    return broker, api, request


def test_order_check_and_account_currency_margin_pass_before_single_send(preflight_terminal):
    broker, api, request = preflight_terminal

    result = broker.order_send(request)

    assert result.status == OrderState.filled
    api.order_calc_profit.assert_called_once_with(0, "XAUUSD", 0.1, 2000.0, 1999.0)
    api.order_calc_margin.assert_called_once_with(0, "XAUUSD", 0.1, 2000.0)
    api.order_check.assert_called_once()
    api.order_send.assert_called_once()
    method_names = [call[0] for call in api.method_calls]
    assert method_names.index("order_check") < method_names.index("order_send")


def test_read_only_margin_estimate_uses_broker_calculation_without_order_actions(preflight_terminal):
    broker, api, _ = preflight_terminal
    api.account_info.return_value.leverage = 100
    api.symbol_info.return_value = SimpleNamespace(visible=True)
    api.symbol_info_tick.return_value = SimpleNamespace(
        bid=1999.9, ask=2000.0, time=time.time())

    result = broker.calculate_margin("BUY", "XAUUSD", 0.1)

    assert result["status"] == "sufficient"
    assert result["required_margin"] == 100
    assert result["projected_free_margin"] == 900
    assert result["leverage"] == 100
    api.order_calc_margin.assert_called_once_with(0, "XAUUSD", 0.1, 2000.0)
    api.order_check.assert_not_called()
    api.order_send.assert_not_called()


def test_read_only_margin_estimate_rejects_stale_quote_and_illegal_volume(preflight_terminal):
    broker, api, _ = preflight_terminal
    api.account_info.return_value.leverage = 100
    api.symbol_info.return_value = SimpleNamespace(visible=True)
    api.symbol_info_tick.return_value = SimpleNamespace(
        bid=1999.9, ask=2000.0, time=time.time() - 60)

    with pytest.raises(mt5_live.BrokerError, match="stale"):
        broker.calculate_margin("BUY", "XAUUSD", 0.1, max_quote_age_seconds=30)
    api.order_calc_margin.assert_not_called()
    with pytest.raises(mt5_live.BrokerError, match="legal volume"):
        broker.calculate_margin("BUY", "XAUUSD", 0.105)
    api.order_calc_margin.assert_not_called()
    api.order_send.assert_not_called()


@pytest.mark.parametrize("check", [
    None,
    SimpleNamespace(retcode=10019, margin_free=900.0, comment="No money"),
    SimpleNamespace(retcode=0, margin_free=-1.0, comment="Done"),
    SimpleNamespace(retcode=0, margin_free=float("nan"), comment="Done"),
])
def test_invalid_order_check_result_never_reaches_order_send(preflight_terminal, check):
    broker, api, request = preflight_terminal
    api.order_check.return_value = check

    result = broker.order_send(request)

    assert result.status == OrderState.rejected
    assert "preflight rejected" in result.message
    assert "no order sent" in result.message
    api.order_send.assert_not_called()


def test_order_check_exception_fails_closed_without_send(preflight_terminal):
    broker, api, request = preflight_terminal
    api.order_check.side_effect = RuntimeError("terminal preflight unavailable")

    result = broker.order_send(request)

    assert result.status == OrderState.rejected
    api.order_send.assert_not_called()


@pytest.mark.parametrize("method", ["order_calc_profit", "order_calc_margin"])
def test_calculation_exception_fails_closed_without_send(preflight_terminal, method):
    broker, api, request = preflight_terminal
    getattr(api, method).side_effect = RuntimeError("terminal calculation unavailable")

    result = broker.order_send(request)

    assert result.status == OrderState.rejected
    api.order_send.assert_not_called()


def test_margin_estimate_above_free_margin_blocks_before_order_check(preflight_terminal):
    broker, api, request = preflight_terminal
    api.order_calc_margin.return_value = 1000.02

    result = broker.order_send(request)

    assert result.status == OrderState.rejected
    assert "exceeds current free margin" in result.message
    api.order_check.assert_not_called()
    api.order_send.assert_not_called()


@pytest.mark.parametrize("stop_pnl", [None, 0.0, 10.0, float("nan")])
def test_invalid_broker_stop_loss_estimate_blocks_send(preflight_terminal, stop_pnl):
    broker, api, request = preflight_terminal
    api.order_calc_profit.return_value = stop_pnl

    result = broker.order_send(request)

    assert result.status == OrderState.rejected
    assert "stop-loss P/L estimate" in result.message
    api.order_calc_margin.assert_not_called()
    api.order_check.assert_not_called()
    api.order_send.assert_not_called()


@pytest.mark.parametrize("sl,tp", [
    (None, 2002.0),
    (1999.0, None),
    (2000.1, 2002.0),
    (1999.0, 1999.9),
    (1999.5, 2002.0),  # 50 points is inside the configured 80-point freeze distance
])
def test_invalid_or_too_close_protection_blocks_send(preflight_terminal, sl, tp):
    broker, api, request = preflight_terminal
    request = request.model_copy(update={"sl": sl, "tp": tp})

    result = broker.order_send(request)

    assert result.status == OrderState.rejected
    assert "preflight rejected" in result.message
    api.order_calc_profit.assert_not_called()
    api.order_check.assert_not_called()
    api.order_send.assert_not_called()


def test_sell_order_uses_side_aware_protective_distances(preflight_terminal):
    broker, api, _ = preflight_terminal
    api.ORDER_TYPE_SELL = 1
    api.order_calc_profit.return_value = -10.0
    request = OrderRequest(
        symbol="XAUUSD", side=OrderSide.sell, volume=0.1,
        sl=2001.0, tp=1998.0, signal_id="sell-1",
        idempotency_key="sell-intent-1", broker_id="demo")

    result = broker.order_send(request)

    assert result.status == OrderState.filled
    api.order_calc_profit.assert_called_once_with(1, "XAUUSD", 0.1, 1999.9, 2001.0)
    api.order_check.assert_called_once()
    api.order_send.assert_called_once()
