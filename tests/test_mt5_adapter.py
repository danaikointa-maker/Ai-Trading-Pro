"""Tests for the real MT5 adapter using a fake ``MetaTrader5`` module.

Nobody can run a real terminal in CI, and shipping an adapter that has never
been executed even once is how silent P&L bugs get into a trading system. These
tests exercise the parts that are pure logic — symbol mapping, spec translation,
volume snapping, order payload, retcode handling, FX conversion of the profit
currency — against a stub that behaves like the documented MT5 API.
"""

from __future__ import annotations

import types

import pytest

from integrations.brokers import mt5_live
from integrations.brokers.base import BrokerError
from packages.shared_schemas.models import OrderRequest, OrderSide, OrderState

class FakeStruct:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def build_fake_mt5(*, retcode: int = 10009, price: float = 2000.5, volume: float = 0.1,
                   filling_mode: int = 2):
    module = types.SimpleNamespace(
        TRADE_ACTION_DEAL=1,
        TRADE_ACTION_SLTP=2,
        ORDER_TYPE_BUY=0,
        ORDER_TYPE_SELL=1,
        ORDER_TIME_GTC=0,
        ORDER_FILLING_IOC=1,
        ORDER_FILLING_FOK=0,
        ORDER_FILLING_RETURN=2,
        TRADE_RETCODE_DONE=10009,
        TRADE_RETCODE_INVALID_STOPS=10016,
        TRADE_RETCODE_INVALID_VOLUME=10014,
    )
    info = FakeStruct(
        description="Gold vs US Dollar", digits=2, point=0.01, trade_tick_size=0.01,
        trade_contract_size=100.0, volume_min=0.01, volume_max=50.0, volume_step=0.01,
        trade_stops_level=30, trade_freeze_level=0, spread=25, currency_profit="USD",
        visible=True, filling_mode=filling_mode, name="GOLD",
    )
    module.symbol_info = lambda name: info if name == "GOLD" else None
    module.symbol_select = lambda name, on: True
    module.symbol_info_tick = lambda name: FakeStruct(bid=1999.5, ask=2000.0, last=1999.8, time=1_800_000_000)
    module.account_info = lambda: FakeStruct(currency="USD", login=123, balance=10000.0,
                                             equity=10000.0, margin_free=10000.0,
                                             leverage=500, server="Demo")
    module.last_error = lambda: (1, "stub error")
    module.order_send = lambda payload: FakeStruct(
        retcode=retcode, order=555, volume=volume, price=price,
        comment="done" if retcode == 10009 else "invalid stops")
    module.sent = []
    original_send = module.order_send

    def record(payload):
        module.sent.append(payload)
        return original_send(payload)

    module.order_send = record
    return module


@pytest.fixture()
def broker(monkeypatch):
    fake = build_fake_mt5()
    monkeypatch.setattr(mt5_live, "mt5", fake)
    monkeypatch.setattr(mt5_live, "MT5_AVAILABLE", True)
    profile = {
        "id": "connext-live",
        "label": "Connext Live",
        "symbols": {"XAUUSD": {"description": "Gold"}},
        "symbol_mapping": {"XAUUSD": "GOLD"},
        "max_slippage_points": 15,
    }
    adapter = mt5_live.MT5Broker(profile)
    adapter._connected = True
    return adapter, fake


def test_symbol_spec_is_translated_from_the_terminal(broker):
    adapter, _ = broker
    spec = adapter.symbol_spec("XAUUSD")
    assert spec.symbol == "XAUUSD"
    assert spec.digits == 2
    assert spec.point == pytest.approx(0.01)
    assert spec.contract_size == 100.0
    assert spec.stops_level_points == 30
    assert spec.value_per_point_per_lot == pytest.approx(1.0)
    assert spec.rate_source == "identity"  # profit currency == account currency


def test_order_send_uses_the_broker_symbol_and_snaps_the_volume(broker):
    adapter, fake = broker
    result = adapter.order_send(OrderRequest(
        symbol="XAUUSD", side=OrderSide.buy, volume=0.014, sl=1990.0, tp=2010.0,
        idempotency_key="key-1"))
    assert fake.sent, "no order payload was sent"
    payload = fake.sent[-1]
    assert payload["symbol"] == "GOLD", "the broker's own symbol name must be used"
    assert payload["volume"] == pytest.approx(0.01), "volume must snap down to the lot step"
    assert payload["sl"] == pytest.approx(1990.0)
    assert payload["tp"] == pytest.approx(2010.0)
    assert payload["type"] == fake.ORDER_TYPE_BUY
    assert result.status is OrderState.filled
    assert result.ticket == "555"
    assert result.idempotency_key == "key-1"


def test_rejected_retcode_is_reported_not_raised(monkeypatch):
    fake = build_fake_mt5(retcode=10016)
    monkeypatch.setattr(mt5_live, "mt5", fake)
    monkeypatch.setattr(mt5_live, "MT5_AVAILABLE", True)
    adapter = mt5_live.MT5Broker({"id": "x", "symbols": {"XAUUSD": {}},
                                  "symbol_mapping": {"XAUUSD": "GOLD"}})
    adapter._connected = True
    result = adapter.order_send(OrderRequest(symbol="XAUUSD", side=OrderSide.sell, volume=0.1))
    assert result.status is OrderState.rejected
    assert result.retcode == 10016
    assert "invalid stops" in result.message


def test_unknown_symbol_is_an_error_not_an_empty_order(broker):
    adapter, _ = broker
    with pytest.raises(BrokerError):
        adapter.symbol_spec("EURUSD")


def test_disconnected_terminal_fails_loudly(monkeypatch):
    monkeypatch.setattr(mt5_live, "mt5", build_fake_mt5())
    monkeypatch.setattr(mt5_live, "MT5_AVAILABLE", True)
    adapter = mt5_live.MT5Broker({"id": "x", "symbols": {"XAUUSD": {}}})
    with pytest.raises(BrokerError, match="not connected"):
        adapter.order_send(OrderRequest(symbol="XAUUSD", side=OrderSide.buy, volume=0.1))
