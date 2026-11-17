"""Offline contract tests for the Windows PC MT5 demo-only probe.

No MetaTrader5 package, terminal, broker account, or order permission is needed.
"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from integrations.brokers.mt5_readonly import ProbeError, probe_demo


@pytest.fixture
def terminal():
    api = Mock()
    api.ACCOUNT_TRADE_MODE_DEMO = 0
    api.initialize.return_value = True
    api.account_info.return_value = SimpleNamespace(
        trade_mode=0, login=12345, server="Demo-Server",
        currency="USD", balance=10000.0, equity=9990.0,
    )
    api.terminal_info.return_value = SimpleNamespace(connected=True)
    api.symbol_info_tick.return_value = SimpleNamespace(
        bid=2500.0, ask=2500.5, time=1700000000,
    )
    return api


def run_probe(api):
    return probe_demo(api, "C:/MT5/terminal64.exe", 12345, "Demo-Server", "XAUUSD")


def assert_never_traded(api):
    api.order_send.assert_not_called()
    api.order_check.assert_not_called()
    api.login.assert_not_called()
    api.shutdown.assert_called_once()


def test_demo_quote_is_read_only_and_does_not_claim_freshness(terminal):
    result = run_probe(terminal)
    assert result["read_only"] is True
    assert result["account_type"] == "demo"
    assert result["tick"]["time"] == 1700000000
    assert "does not guarantee" in result["note"]
    assert_never_traded(terminal)


@pytest.mark.parametrize("change", [
    lambda t: setattr(t.account_info.return_value, "trade_mode", 1),
    lambda t: setattr(t.account_info.return_value, "login", 99999),
    lambda t: setattr(t.account_info.return_value, "server", "Other-Server"),
    lambda t: setattr(t.terminal_info.return_value, "connected", False),
    lambda t: setattr(t.symbol_info_tick.return_value, "ask", float("nan")),
    lambda t: setattr(t.symbol_info_tick.return_value, "ask", 2499.0),
])
def test_rejects_non_demo_identity_disconnected_and_invalid_quotes(terminal, change):
    change(terminal)
    with pytest.raises(ProbeError):
        run_probe(terminal)
    assert_never_traded(terminal)


def test_account_switch_between_initial_and_final_check_blocks_result(terminal):
    expected = terminal.account_info.return_value
    switched = SimpleNamespace(**{**vars(expected), "login": 54321})
    terminal.account_info.side_effect = [expected, switched]
    with pytest.raises(ProbeError, match="identity"):
        run_probe(terminal)
    assert_never_traded(terminal)


def test_initialize_failure_still_shuts_down_and_never_trades(terminal):
    terminal.initialize.return_value = False
    with pytest.raises(ProbeError, match="initialize"):
        run_probe(terminal)
    assert_never_traded(terminal)
