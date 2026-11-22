"""Read-only Windows MT5 market publisher for the isolated market-data endpoint.

This process never calls MT5 order/position methods and has a separate API token
from the EA command bridge. It attaches to the already selected terminal session;
it will not log in, switch accounts, or enable Algo Trading.
"""
from __future__ import annotations

import math
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx


TIMEFRAMES = {
    "M1": "TIMEFRAME_M1", "M3": "TIMEFRAME_M3", "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15", "M30": "TIMEFRAME_M30", "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4", "D1": "TIMEFRAME_D1", "W1": "TIMEFRAME_W1",
    "MN1": "TIMEFRAME_MN1",
}
REQUIRED_SETTINGS = (
    "NO7_MT5_MARKET_API_URL",
    "NO7_MT5_MARKET_PUBLISHER_TOKEN",
    "NO7_MT5_MARKET_EXPECTED_LOGIN",
    "NO7_MT5_MARKET_EXPECTED_SERVER",
    "NO7_MT5_MARKET_SYMBOL_MAP",
)


def _required_settings() -> dict[str, str]:
    settings = {name: os.environ.get(name, "").strip() for name in REQUIRED_SETTINGS}
    missing = [name for name, value in settings.items() if not value]
    if missing:
        raise RuntimeError("required environment settings are missing: " + ", ".join(missing))
    return settings


def _expected_login(value: str) -> int:
    try:
        login = int(value)
    except (TypeError, ValueError):
        raise RuntimeError("NO7_MT5_MARKET_EXPECTED_LOGIN must be an integer") from None
    if login <= 0:
        raise RuntimeError("NO7_MT5_MARKET_EXPECTED_LOGIN must be positive")
    return login


def _symbol_map(raw: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for entry in raw.split(","):
        if not entry.strip():
            continue
        canonical, sep, broker = entry.partition("=")
        canonical, broker = canonical.strip(), (broker.strip() if sep else canonical.strip())
        if not canonical or not broker or canonical in mapping:
            raise RuntimeError("invalid or duplicate NO7_MT5_MARKET_SYMBOL_MAP entry")
        mapping[canonical] = broker
    if not mapping:
        raise RuntimeError("set NO7_MT5_MARKET_SYMBOL_MAP, e.g. XAUUSD=XAUUSD.s")
    return mapping


def _validate_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.fragment):
        raise RuntimeError("market API URL must be an absolute HTTP(S) URL without embedded credentials")
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and parsed.hostname.lower() not in local_hosts:
        raise RuntimeError("market publisher bearer token requires HTTPS or a loopback SSH tunnel")
    return value


def _rates(mt5: Any, symbol: str, count: int,
           frames: list[str]) -> dict[str, list[dict[str, float]]]:
    result = {}
    for name in frames:
        raw = mt5.copy_rates_from_pos(symbol, getattr(mt5, TIMEFRAMES[name]), 0, count)
        if raw is None or len(raw) == 0:
            continue
        result[name] = [{"t": int(row["time"]), "o": float(row["open"]),
                         "h": float(row["high"]), "l": float(row["low"]),
                         "c": float(row["close"]), "v": float(row["tick_volume"])}
                        for row in raw]
    return result


def _quote_freshness(info: Any, tick: Any, now: float,
                     max_age: float) -> tuple[float | None, str | None]:
    """Return UTC tick time, or a safe reason why the quote must be withheld."""
    if info is None:
        return None, "symbol info unavailable"
    if tick is None:
        return None, "no tick"
    try:
        bid, ask = float(tick.bid), float(tick.ask)
    except (AttributeError, TypeError, ValueError):
        return None, "invalid bid/ask"
    if not math.isfinite(bid) or not math.isfinite(ask) or bid <= 0 or ask < bid:
        return None, "invalid bid/ask"

    try:
        tick_time_msc = float(getattr(tick, "time_msc", 0) or 0)
        tick_time = (tick_time_msc / 1000.0 if tick_time_msc > 0
                     else float(tick.time))
    except (AttributeError, TypeError, ValueError):
        return None, "invalid tick timestamp"
    if not math.isfinite(tick_time) or tick_time <= 0:
        return None, "invalid tick timestamp"

    age = now - tick_time
    if age < 0:
        return None, f"future tick ({age:.1f}s)"
    if age > max_age:
        return None, f"stale tick ({age:.1f}s old; limit {max_age:g}s)"
    return tick_time, None


def run() -> int:
    settings = _required_settings()
    endpoint = _validate_endpoint(settings["NO7_MT5_MARKET_API_URL"])
    token = settings["NO7_MT5_MARKET_PUBLISHER_TOKEN"]
    expected_login = _expected_login(settings["NO7_MT5_MARKET_EXPECTED_LOGIN"])
    expected_server = settings["NO7_MT5_MARKET_EXPECTED_SERVER"]
    symbols = _symbol_map(settings["NO7_MT5_MARKET_SYMBOL_MAP"])
    frames = [name.strip().upper() for name in os.environ.get(
        "NO7_MT5_MARKET_TIMEFRAMES", "M1,M3,M5,M15,H1,H4").split(",") if name.strip()]
    if set(frames) - set(TIMEFRAMES):
        raise RuntimeError("NO7_MT5_MARKET_TIMEFRAMES contains an unsupported timeframe")
    bars = min(max(int(os.environ.get("NO7_MT5_MARKET_BARS", "600")), 20), 2000)
    poll_seconds = max(0.25, float(os.environ.get("NO7_MT5_MARKET_POLL_SECONDS", "0.5")))
    rates_seconds = max(poll_seconds, float(os.environ.get("NO7_MT5_MARKET_RATES_SECONDS", "5")))
    max_tick_age = float(os.environ.get("NO7_MT5_MARKET_MAX_TICK_AGE_SECONDS", "10"))
    if not 1 <= max_tick_age <= 15:
        raise RuntimeError("NO7_MT5_MARKET_MAX_TICK_AGE_SECONDS must be between 1 and 15")
    terminal_path = os.environ.get("NO7_MT5_TERMINAL_PATH", "").strip()
    import MetaTrader5 as mt5  # optional Windows-only dependency

    initialized = mt5.initialize(path=terminal_path) if terminal_path else mt5.initialize()
    if not initialized:
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        account = mt5.account_info()
        terminal = mt5.terminal_info()
        demo_mode = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)
        if (account is None or terminal is None or not terminal.connected
                or int(account.login) != expected_login or account.server != expected_server
                or int(account.trade_mode) != demo_mode):
            raise RuntimeError("connected terminal is not the configured Connext Demo identity")
        for broker_symbol in symbols.values():
            if not mt5.symbol_select(broker_symbol, True):
                raise RuntimeError(f"MT5 symbol is unavailable in Market Watch: {broker_symbol}")
        cached_rates: dict[str, dict[str, list[dict[str, float]]]] = {}
        cached_specs: dict[str, dict[str, Any]] = {}
        last_rates = 0.0
        next_status = 0.0
        with httpx.Client(timeout=5) as client:
            while True:
                now = time.time()
                quotes = {}
                skipped: dict[str, str] = {}
                refresh_rates = now - last_rates >= rates_seconds
                for canonical, broker_symbol in symbols.items():
                    info, tick = mt5.symbol_info(broker_symbol), mt5.symbol_info_tick(broker_symbol)
                    # MetaTrader's Python integration returns tick/bar timestamps in UTC.
                    # Do not infer a timezone offset from a tick: that would turn a stale
                    # tick into an apparently current quote when the market is quiet/closed.
                    tick_time, skip_reason = _quote_freshness(info, tick, now, max_tick_age)
                    if skip_reason:
                        skipped[canonical] = skip_reason
                        continue
                    quotes[canonical] = {"bid": float(tick.bid), "ask": float(tick.ask),
                                         "last": float(tick.last or 0), "t": tick_time}
                    cached_specs[canonical] = {
                        "symbol": canonical, "description": str(info.description or broker_symbol),
                        "digits": int(info.digits), "point": float(info.point),
                        "tick_size": float(info.trade_tick_size or info.point),
                        "contract_size": float(info.trade_contract_size),
                        "min_lot": float(info.volume_min), "max_lot": float(info.volume_max),
                        "lot_step": float(info.volume_step),
                        "stops_level_points": float(info.trade_stops_level),
                        "freeze_level_points": float(info.trade_freeze_level),
                        "profit_currency": str(info.currency_profit or account.currency),
                        "account_currency": str(account.currency), "source": "broker",
                        "spec_complete": True,
                    }
                    if refresh_rates:
                        canonical_rates = _rates(mt5, broker_symbol, bars, frames)
                        for timeframe in frames:
                            if timeframe in canonical_rates:
                                cached_rates.setdefault(canonical, {})[timeframe] = canonical_rates[timeframe]
                if refresh_rates:
                    last_rates = now
                if quotes:
                    utc_now = time.time()
                    payload = {
                        "identity": {"login": str(account.login), "server": account.server,
                                     "trade_mode": "demo", "connected": True},
                        "captured_at": utc_now, "time_basis": "utc",
                        "server_time": utc_now, "utc_time": utc_now,
                        "quotes": quotes,
                        "rates": cached_rates if refresh_rates else {},
                        "specs": cached_specs if refresh_rates else {},
                    }
                    response = client.post(endpoint, json=payload,
                                           headers={"Authorization": f"Bearer {token}"})
                    if response.status_code >= 400:
                        raise RuntimeError(f"market publisher rejected: HTTP {response.status_code} "
                                           f"{response.text[:240]}")
                    if now >= next_status:
                        print(f"Published {len(quotes)} Demo quote(s); rates refreshed every "
                              f"{rates_seconds:g}s at {datetime.now(timezone.utc).isoformat()}",
                              flush=True)
                        next_status = now + 30
                elif now >= next_status:
                    details = "; ".join(f"{symbol}: {reason}"
                                        for symbol, reason in skipped.items())
                    suffix = f" Reasons: {details}." if details else ""
                    print("No fresh MT5 quote; publisher is withholding the snapshot "
                          f"(max age {max_tick_age:g}s).{suffix}", flush=True)
                    next_status = now + 30
                time.sleep(poll_seconds)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except KeyboardInterrupt:
        raise SystemExit(0)
    except Exception as exc:
        print(f"MT5 market publisher stopped: {exc}", file=sys.stderr)
        raise SystemExit(1)
