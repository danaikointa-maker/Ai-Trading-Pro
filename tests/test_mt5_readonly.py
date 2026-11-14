from types import SimpleNamespace

import pytest

from integrations.brokers import mt5_readonly


class Terminal:
    ACCOUNT_TRADE_MODE_DEMO = 0

    def __init__(self, mode=0, connected=True):
        self.info = SimpleNamespace(login=123, server="Broker-Demo", trade_mode=mode,
                                    currency="USD", balance=10000.0, equity=10000.0)
        self.connected = connected
        self.calls = []

    def initialize(self, path, **kwargs):
        self.calls.append("initialize")
        return True

    def shutdown(self):
        self.calls.append("shutdown")

    def account_info(self):
        self.calls.append("account_info")
        return self.info

    def terminal_info(self):
        return SimpleNamespace(connected=self.connected)

    def symbol_info_tick(self, symbol):
        self.calls.append("tick")
        return SimpleNamespace(bid=3000.0, ask=3000.5, time=100)


def test_readonly_probe_missing_implementation():
    assert callable(getattr(mt5_readonly, "probe_demo", None))


@pytest.mark.parametrize("mode", [1, 2, None])
def test_rejects_non_demo_before_reading_prices(mode):
    terminal = Terminal(mode=mode)
    with pytest.raises(mt5_readonly.ProbeError, match="demo"):
        mt5_readonly.probe_demo(terminal, "terminal64.exe", 123, "Broker-Demo", "XAUUSD")
    assert "tick" not in terminal.calls
    assert terminal.calls[-1] == "shutdown"


def test_reads_demo_without_exposing_account_number():
    terminal = Terminal()
    result = mt5_readonly.probe_demo(terminal, "terminal64.exe", 123, "Broker-Demo", "XAUUSD")
    assert result["account_type"] == "demo"
    assert result["read_only"] is True
    assert result["tick"]["bid"] == 3000.0
    assert "login" not in result
    assert terminal.calls[-1] == "shutdown"


@pytest.mark.parametrize("login,server", [(999, "Broker-Demo"), (123, "Other-Demo")])
def test_rejects_wrong_identity(login, server):
    terminal = Terminal()
    with pytest.raises(mt5_readonly.ProbeError, match="identity"):
        mt5_readonly.probe_demo(terminal, "terminal64.exe", login, server, "XAUUSD")
    assert "tick" not in terminal.calls


def test_rejects_disconnected_terminal():
    terminal = Terminal(connected=False)
    with pytest.raises(mt5_readonly.ProbeError, match="connected"):
        mt5_readonly.probe_demo(terminal, "terminal64.exe", 123, "Broker-Demo", "XAUUSD")
    assert "tick" not in terminal.calls


def test_rejects_account_switch_during_read():
    terminal = Terminal()

    def switched(symbol):
        terminal.info.login = 999
        return SimpleNamespace(bid=3000.0, ask=3000.5, time=100)

    terminal.symbol_info_tick = switched
    with pytest.raises(mt5_readonly.ProbeError, match="identity"):
        mt5_readonly.probe_demo(terminal, "terminal64.exe", 123, "Broker-Demo", "XAUUSD")
    assert terminal.calls[-1] == "shutdown"


def test_initialize_failure_still_shuts_down():
    terminal = Terminal()
    terminal.initialize = lambda *args, **kwargs: False
    with pytest.raises(mt5_readonly.ProbeError, match="initialize"):
        mt5_readonly.probe_demo(terminal, "terminal64.exe", 123, "Broker-Demo", "XAUUSD")
    assert terminal.calls == ["shutdown"]