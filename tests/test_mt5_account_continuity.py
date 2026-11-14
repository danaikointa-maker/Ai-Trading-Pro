"""Account continuity tests use a fake terminal only; never initialize real MT5."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from integrations.brokers import mt5_live
from integrations.brokers.base import BrokerError
from packages.shared_schemas.models import Health, OrderRequest, OrderSide


@pytest.fixture
def terminal(monkeypatch):
    api = Mock()
    api.account_info.return_value = SimpleNamespace(login=123, server="Demo", currency="USD")
    api.initialize.return_value = True
    api.positions_get.return_value = ()
    api.terminal_info.return_value = SimpleNamespace(connected=True)
    monkeypatch.setattr(mt5_live, "mt5", api)
    monkeypatch.setattr(mt5_live, "MT5_AVAILABLE", True)
    broker = mt5_live.MT5Broker({"id": "fake", "symbols": {}}, login=123, server="Demo")
    broker._connected = True
    return broker, api


@pytest.mark.parametrize("login,server", [(None, "Demo"), (123, ""), (0, "Demo")])
def test_connect_requires_explicit_identity_before_initialize(terminal, login, server):
    broker, api = terminal
    broker.login, broker.server = login, server
    assert broker.connect() is False
    api.initialize.assert_not_called()


def test_connect_refuses_wrong_terminal_account(terminal):
    broker, api = terminal
    api.account_info.return_value.login = 456
    assert broker.connect() is False
    assert broker._connected is False


@pytest.mark.parametrize("method", ["positions", "order", "modify", "close", "account"])
def test_wrong_account_is_blocked_before_sensitive_io(terminal, method):
    broker, api = terminal
    api.account_info.return_value.login = 456
    with pytest.raises(BrokerError, match="identity"):
        if method == "order":
            broker.order_send(OrderRequest(symbol="XAUUSD", side=OrderSide.buy, volume=0.1))
        elif method == "modify":
            broker.modify_position("1", sl=1900)
        elif method == "close":
            broker.close_position("1")
        elif method == "account":
            broker.account_info()
        else:
            broker.positions()
    api.positions_get.assert_not_called()
    api.order_send.assert_not_called()
    api.symbol_info_tick.assert_not_called()


def test_empty_positions_from_switched_account_is_not_authoritative_empty(terminal):
    broker, api = terminal

    def switch():
        api.account_info.return_value.login = 456
        return ()

    api.positions_get.side_effect = switch
    with pytest.raises(BrokerError, match="identity"):
        broker.positions()


def test_health_does_not_advertise_foreign_account_as_connected(terminal):
    broker, api = terminal
    api.account_info.return_value.server = "Other"
    assert broker.health() not in (Health.connected, Health.degraded)


def test_matching_empty_positions_remains_valid(terminal):
    broker, _ = terminal
    assert broker.positions() == []


@pytest.fixture
def closing_terminal(terminal):
    broker, api = terminal
    for name, value in {"TRADE_RETCODE_DONE": 10009, "TRADE_RETCODE_DONE_PARTIAL": 10010,
                        "TRADE_RETCODE_REJECT": 10006, "TRADE_RETCODE_CANCEL": 10007,
                        "TRADE_ACTION_DEAL": 1, "ORDER_TYPE_SELL": 1, "ORDER_TYPE_BUY": 0,
                        "ORDER_TIME_GTC": 0, "ORDER_FILLING_IOC": 1}.items():
        setattr(api, name, value)
    api.positions_get.return_value = [SimpleNamespace(symbol="XAUUSD", type=0, volume=0.1)]
    api.symbol_info_tick.return_value = SimpleNamespace(bid=2000., ask=2001.)
    broker.symbol_spec = Mock(return_value=SimpleNamespace(normalize_lot=lambda value: value))
    broker._filling_mode = Mock(return_value=1)
    api.order_send.return_value = SimpleNamespace(retcode=10009, volume=0.04, price=1999.5,
                                                 comment="private terminal details")
    return broker, api


@pytest.mark.parametrize("retcode", [None, 10008, 10011, 10012, 10031, 99999, "10009"])
def test_close_ambiguous_receipt_is_unknown_without_retry(closing_terminal, retcode):
    broker, api = closing_terminal
    if retcode is None:
        api.order_send.return_value = None
    else:
        api.order_send.return_value.retcode = retcode
    with pytest.raises(BrokerError, match="unknown"):
        broker.close_position("123", volume=0.05)
    api.order_send.assert_called_once()


@pytest.mark.parametrize("volume", [None, float("nan"), float("inf"), -1, 0, 0.2, True, "0.04"])
def test_close_invalid_reported_volume_does_not_become_requested_fill(closing_terminal, volume):
    broker, api = closing_terminal
    api.order_send.return_value.volume = volume
    with pytest.raises(BrokerError, match="unknown"):
        broker.close_position("123", volume=0.05)
    api.order_send.assert_called_once()


@pytest.mark.parametrize("retcode,status", [(10009, "closed"), (10010, "partially_filled"),
                                          (10006, "rejected"), (10007, "cancelled")])
def test_close_preserves_acknowledgement_not_exposure(closing_terminal, retcode, status):
    broker, api = closing_terminal
    api.order_send.return_value.retcode = retcode
    if retcode in (10006, 10007):
        api.order_send.return_value.volume = 0
        api.order_send.return_value.price = 0
    result = broker.close_position("123", volume=0.05)
    assert result.status.value == status
    assert result.verified is False
    assert result.filled_volume == (0.04 if retcode in (10009, 10010) else 0)
    assert result.fill_price == (1999.5 if retcode in (10009, 10010) else None)
    assert "private" not in result.message
    api.order_send.assert_called_once()


def test_close_post_send_account_switch_discards_receipt(closing_terminal):
    broker, api = closing_terminal
    receipt = api.order_send.return_value

    def switch(payload):
        api.account_info.return_value.login = 456
        return receipt

    api.order_send.side_effect = switch
    with pytest.raises(BrokerError, match="identity"):
        broker.close_position("123", volume=0.05)
    api.order_send.assert_called_once()


@pytest.mark.parametrize("volume", [0, -1, float("nan"), float("inf"), True, "0.05", 0.2])
def test_close_invalid_requested_volume_never_sends(closing_terminal, volume):
    broker, api = closing_terminal
    with pytest.raises(BrokerError, match="volume"):
        broker.close_position("123", volume=volume)
    api.order_send.assert_not_called()


@pytest.mark.parametrize("normalized", [0, -1, float("nan"), float("inf"), 0.2, True])
def test_close_normalized_volume_must_not_expand_request(closing_terminal, normalized):
    broker, api = closing_terminal
    broker.symbol_spec.return_value.normalize_lot = lambda value: normalized
    with pytest.raises(BrokerError, match="volume"):
        broker.close_position("123", volume=0.05)
    api.order_send.assert_not_called()