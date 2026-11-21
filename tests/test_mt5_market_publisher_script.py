from __future__ import annotations

import sys
import time
from types import ModuleType, SimpleNamespace

import pytest

import scripts.mt5_market_publisher as publisher
from scripts.mt5_market_publisher import (
    TIMEFRAMES, _quote_freshness, _rates, _symbol_map, _validate_endpoint,
)


def test_symbol_map_supports_canonical_broker_suffix_mapping():
    assert _symbol_map("XAUUSD=XAUUSD.s,EURUSD") == {
        "XAUUSD": "XAUUSD.s", "EURUSD": "EURUSD",
    }


@pytest.mark.parametrize("raw", ["", "=XAUUSD", "XAUUSD=", "XAUUSD,XAUUSD=XAUUSD.s"])
def test_symbol_map_rejects_empty_or_duplicate_entries(raw):
    with pytest.raises(RuntimeError):
        _symbol_map(raw)


@pytest.mark.parametrize("url", [
    "http://192.168.1.10:8000/api/market/publish/mt5",
    "http://user:password@localhost/api/market/publish/mt5",
    "ftp://localhost/upload",
    "https://example.test/path#fragment",
])
def test_market_endpoint_rejects_plaintext_remote_or_malformed_urls(url):
    with pytest.raises(RuntimeError):
        _validate_endpoint(url)


@pytest.mark.parametrize("url", [
    "https://api.example.test/api/market/publish/mt5",
    "http://127.0.0.1:18080/api/market/publish/mt5",
    "http://localhost:18080/api/market/publish/mt5",
])
def test_market_endpoint_allows_tls_or_loopback_tunnel(url):
    assert _validate_endpoint(url) == url


def test_rates_reads_only_requested_frames_and_normalizes_mt5_fields():
    calls = []

    class FakeMT5:
        TIMEFRAME_M1 = 1
        TIMEFRAME_M5 = 5

        @staticmethod
        def copy_rates_from_pos(symbol, timeframe, start, count):
            calls.append((symbol, timeframe, start, count))
            return [{"time": 100, "open": 1, "high": 3, "low": 0.5,
                     "close": 2, "tick_volume": 9}]

    assert _rates(FakeMT5, "XAUUSD.s", 600, ["M1"]) == {
        "M1": [{"t": 100, "o": 1.0, "h": 3.0, "l": 0.5, "c": 2.0, "v": 9.0}],
    }
    assert calls == [("XAUUSD.s", FakeMT5.TIMEFRAME_M1, 0, 600)]
    assert set(TIMEFRAMES) >= {"M1", "M5"}


@pytest.mark.parametrize(("info", "tick", "now", "max_age", "reason"), [
    (None, None, 100.0, 10.0, "symbol info unavailable"),
    (object(), None, 100.0, 10.0, "no tick"),
    (object(), SimpleNamespace(bid=0, ask=1, time=100), 100.0, 10.0,
     "invalid bid/ask"),
    (object(), SimpleNamespace(bid=1, ask=1.1, time=100), 101.0, 10.0, None),
    (object(), SimpleNamespace(bid=1, ask=1.1, time=40), 100.0, 10.0,
     "stale tick (60.0s old; limit 10s)"),
    (object(), SimpleNamespace(bid=1, ask=1.1, time=102), 100.0, 10.0,
     "future tick (-2.0s)"),
    (object(), SimpleNamespace(bid=1, ask=1.1, time=float("nan")), 100.0, 10.0,
     "invalid tick timestamp"),
])
def test_quote_freshness_explains_withheld_quotes(info, tick, now, max_age, reason):
    tick_time, skip_reason = _quote_freshness(info, tick, now, max_age)
    assert skip_reason == reason
    if reason is None:
        assert tick_time == 100.0
    else:
        assert tick_time is None


@pytest.mark.parametrize(("tick_age_seconds", "expect_publish"), [(0, True), (60, False)])
def test_readonly_publisher_only_emits_fresh_utc_demo_quotes(
        monkeypatch, capsys, tick_age_seconds, expect_publish):
    now = time.time()
    calls = []
    mt5 = ModuleType("MetaTrader5")
    mt5.ACCOUNT_TRADE_MODE_DEMO = 0
    for index, name in enumerate(TIMEFRAMES):
        setattr(mt5, f"TIMEFRAME_{name}", index + 1)
    mt5.initialize = lambda **_kwargs: True
    mt5.last_error = lambda: (0, "ok")
    mt5.account_info = lambda: SimpleNamespace(login=123456, server="Connext-Demo",
                                                trade_mode=0, currency="USD")
    mt5.terminal_info = lambda: SimpleNamespace(connected=True)
    mt5.symbol_select = lambda _symbol, _enable: True
    mt5.symbol_info = lambda _symbol: SimpleNamespace(
        description="Gold", digits=2, point=0.01, trade_tick_size=0.01,
        trade_contract_size=100, volume_min=0.01, volume_max=50, volume_step=0.01,
        trade_stops_level=0, trade_freeze_level=0, currency_profit="USD")
    mt5.symbol_info_tick = lambda _symbol: SimpleNamespace(
        bid=2300.0, ask=2300.2, last=2300.1, time=int(now - tick_age_seconds),
        time_msc=int((now - tick_age_seconds) * 1000))
    mt5.copy_rates_from_pos = lambda symbol, timeframe, start, count: [{
        "time": int(now) - 60, "open": 2299.0, "high": 2301.0, "low": 2298.0,
        "close": 2300.0, "tick_volume": 12,
    }]
    mt5.shutdown = lambda: calls.append("shutdown")
    monkeypatch.setitem(sys.modules, "MetaTrader5", mt5)
    monkeypatch.setenv("NO7_MT5_MARKET_API_URL", "http://127.0.0.1:18080/api/market/publish/mt5")
    monkeypatch.setenv("NO7_MT5_MARKET_PUBLISHER_TOKEN", "separate-data-token")
    monkeypatch.setenv("NO7_MT5_MARKET_EXPECTED_LOGIN", "123456")
    monkeypatch.setenv("NO7_MT5_MARKET_EXPECTED_SERVER", "Connext-Demo")
    monkeypatch.setenv("NO7_MT5_MARKET_SYMBOL_MAP", "XAUUSD=XAUUSD.s")
    monkeypatch.setenv("NO7_MT5_MARKET_TIMEFRAMES", "M1")
    monkeypatch.setenv("NO7_MT5_MARKET_BARS", "20")
    monkeypatch.setenv("NO7_MT5_MARKET_POLL_SECONDS", "0.25")
    monkeypatch.setenv("NO7_MT5_MARKET_RATES_SECONDS", "5")

    class Response:
        status_code = 200

    class Client:
        def __init__(self, timeout):
            assert timeout == 5

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, endpoint, *, json, headers):
            calls.append((endpoint, json, headers))
            return Response()

    monkeypatch.setattr(publisher.httpx, "Client", Client)

    def stop_after_first_publish(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(publisher.time, "sleep", stop_after_first_publish)
    with pytest.raises(KeyboardInterrupt):
        publisher.run()

    if not expect_publish:
        assert calls == ["shutdown"]
        output = capsys.readouterr().out
        assert "No fresh MT5 quote" in output
        assert "XAUUSD: stale tick (60.0s old; limit 10s)" in output
        return

    endpoint, body, headers = calls[0]
    assert endpoint.endswith("/api/market/publish/mt5")
    assert headers == {"Authorization": "Bearer separate-data-token"}
    assert body["identity"] == {"login": "123456", "server": "Connext-Demo",
                                "trade_mode": "demo", "connected": True}
    assert body["time_basis"] == "utc"
    assert body["server_time"] == body["utc_time"]
    assert abs(body["utc_time"] - body["quotes"]["XAUUSD"]["t"]) <= 10
    assert body["captured_at"] == body["utc_time"]
    assert body["rates"]["XAUUSD"]["M1"][0]["t"] == int(now) - 60
    assert body["quotes"]["XAUUSD"]["bid"] == 2300.0
    assert body["rates"]["XAUUSD"]["M1"][0]["c"] == 2300.0
    assert body["specs"]["XAUUSD"]["symbol"] == "XAUUSD"
    assert "positions" not in body and "orders" not in body and "commands" not in body
    assert calls[-1] == "shutdown"
