"""MT5 orders are checked before send; failed checks never submit."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from integrations.brokers import mt5_live
from integrations.brokers.base import BrokerError
from packages.shared_schemas.models import (
    OrderRequest,
    OrderSide,
    OrderState,
    SymbolSpec,
    Tick,
)


@pytest.fixture
def setup_mt5(monkeypatch):
    api = Mock()
    api.account_info.return_value = SimpleNamespace(login=123, server="Connext-Demo",
                                                    currency="USD")
    api.TRADE_ACTION_DEAL = 1
    api.ORDER_TYPE_BUY = 0
    api.ORDER_TYPE_SELL = 1
    api.ORDER_TIME_GTC = 0
    api.ORDER_FILLING_IOC = 1
    api.TRADE_RETCODE_DONE = 10009
    api.order_check.return_value = SimpleNamespace(retcode=0, comment="Done")
    api.order_send.return_value = SimpleNamespace(
        retcode=10009, order=456, volume=0.1, price=2000.1, comment="Request executed")
    monkeypatch.setattr(mt5_live, "mt5", api)
    monkeypatch.setattr(mt5_live, "MT5_AVAILABLE", True)
    broker = mt5_live.MT5Broker(
        {"id": "demo", "label": "Demo", "account_type": "demo",
         "symbols": {"XAUUSD": {}}}, login=123, server="Connext-Demo")
    broker._connected = True
    broker.symbol_spec = Mock(return_value=SymbolSpec(
        symbol="XAUUSD", digits=2, point=0.01, tick_size=0.01,
        contract_size=100, min_lot=0.01, max_lot=50, lot_step=0.01,
    ))
    broker.ticker = Mock(return_value=Tick(
        symbol="XAUUSD", bid=2000.0, ask=2000.1, last=2000.0,
        spread_points=10, t=1_700_000_000,
    ))
    broker._filling_mode = Mock(return_value=1)
    return broker, api


def request() -> OrderRequest:
    return OrderRequest(symbol="XAUUSD", side=OrderSide.buy, volume=0.1,
                        sl=1998.0, tp=2004.0, idempotency_key="test-demo-key",
                        broker_id="demo")


def test_valid_preflight_checks_same_request_then_sends_once(setup_mt5):
    broker, api = setup_mt5

    result = broker.order_send(request())

    assert result.status == OrderState.filled
    api.order_check.assert_called_once()
    api.order_send.assert_called_once_with(api.order_check.call_args.args[0])
    checked = api.order_check.call_args.args[0]
    assert checked["sl"] == 1998.0 and checked["tp"] == 2004.0


@pytest.mark.parametrize("check_result", [
    None,
    SimpleNamespace(retcode=10014, comment="private detail"),
    SimpleNamespace(retcode="0", comment="malformed"),
])
def test_failed_or_malformed_preflight_never_sends(setup_mt5, check_result):
    broker, api = setup_mt5
    api.order_check.return_value = check_result

    result = broker.order_send(request())

    assert result.status == OrderState.rejected
    assert "no order was sent" in result.message
    assert "private detail" not in result.message
    api.order_send.assert_not_called()


def test_preflight_exception_never_sends(setup_mt5):
    broker, api = setup_mt5
    api.order_check.side_effect = RuntimeError("terminal details")

    result = broker.order_send(request())

    assert result.status == OrderState.rejected
    assert "no order was sent" in result.message
    api.order_send.assert_not_called()


def test_account_switch_after_preflight_never_sends(setup_mt5):
    broker, api = setup_mt5

    def switch(_payload):
        api.account_info.return_value.login = 999
        return SimpleNamespace(retcode=0)

    api.order_check.side_effect = switch

    with pytest.raises(BrokerError, match="identity"):
        broker.order_send(request())

    api.order_send.assert_not_called()
