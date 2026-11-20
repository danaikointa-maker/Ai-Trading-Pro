from types import SimpleNamespace

import pytest

from integrations.brokers import mt5_readonly


class Terminal:
    ACCOUNT_TRADE_MODE_DEMO = 0
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1

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

    def positions_get(self):
        self.calls.append("positions")
        return [SimpleNamespace(ticket=88, symbol="XAUUSD.s", type=0, volume=0.1,
                                price_open=2990.0, sl=2980.0, tp=3020.0,
                                price_current=3000.0, profit=100.0, time=99)]


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


def test_reads_positions_sl_tp_from_the_verified_demo_terminal():
    terminal = Terminal()
    result = mt5_readonly.probe_demo(terminal, "terminal64.exe", 123, "Broker-Demo", "XAUUSD",
                                     include_positions=True)
    assert result["read_only"] is True
    assert result["execution_enabled"] is False
    assert result["positions"] == [{
        "ticket": "88", "symbol": "XAUUSD.s", "direction": "up", "volume": 0.1,
        "entry": 2990.0, "sl": 2980.0, "tp": 3020.0, "current_price": 3000.0,
        "unrealized": 100.0, "open_time": 99, "broker_id": "mt5-read-only",
    }]
    assert terminal.calls.count("positions") == 1
    assert terminal.calls[-1] == "shutdown"


def test_unavailable_position_list_is_not_misreported_as_empty():
    terminal = Terminal()
    terminal.positions_get = lambda: None
    with pytest.raises(mt5_readonly.ProbeError, match="could not read open positions"):
        mt5_readonly.probe_demo(terminal, "terminal64.exe", 123, "Broker-Demo", "XAUUSD",
                                include_positions=True)
    assert terminal.calls[-1] == "shutdown"


def test_account_switch_during_positions_read_blocks_snapshot():
    terminal = Terminal()

    def switched():
        terminal.info.login = 999
        return [SimpleNamespace(ticket=99, symbol="XAUUSD", type=0, volume=0.1,
                                price_open=2990.0, sl=2980.0, tp=3020.0,
                                price_current=3000.0, profit=100.0, time=99)]

    terminal.positions_get = switched
    with pytest.raises(mt5_readonly.ProbeError, match="identity"):
        mt5_readonly.probe_demo(terminal, "terminal64.exe", 123, "Broker-Demo", "XAUUSD",
                                include_positions=True)
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
