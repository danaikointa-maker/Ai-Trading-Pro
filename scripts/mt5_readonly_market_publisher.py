"""Publish read-only MT5 quotes and candles to the No7 bridge.

This Windows-side process only reads an already-running, authenticated Demo
terminal. It has no order, close, modify, or account-login path. Any commands in
the bridge response are deliberately ignored.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from integrations.brokers.terminal_locator import (
    TerminalDiscoveryError,
    resolve_running_terminal,
)

TIMEFRAMES = {
    "M1": "TIMEFRAME_M1",
    "M3": "TIMEFRAME_M3",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}


class PublisherError(RuntimeError):
    """A safe failure message that never includes account credentials or tokens."""


class BridgeHTTPError(PublisherError):
    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"bridge HTTP status {status}")


def read_bridge_token(path: str | None) -> str:
    token = (os.environ.get("NO7_BRIDGE_TOKEN") or "").strip()
    if token:
        return token
    if not path:
        raise PublisherError("bridge token is unavailable")
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "NO7_BRIDGE_TOKEN":
                return value.strip().strip('"').strip("'")
    except OSError as exc:
        raise PublisherError("bridge token file is unavailable") from exc
    raise PublisherError("bridge token is unavailable")


def require_running_terminal() -> None:
    """Do not let MetaTrader5.initialize launch a terminal with a saved account."""
    if sys.platform != "win32":
        raise PublisherError("the MT5 publisher must run on the Windows terminal host")
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq terminal64.exe", "/NH"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PublisherError("could not verify that the MT5 terminal is already open") from exc
    if result.returncode != 0 or "terminal64.exe" not in result.stdout.lower():
        raise PublisherError("open and authenticate the Demo MT5 terminal manually first")


class BridgeClient:
    def __init__(self, base_url: str, account_id: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.account_id = account_id
        self.token = token
        self.session_id = ""

    def post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
        request = Request(
            f"{self.base_url}/api/bridge/{endpoint}", data=body, method="POST",
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=8) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if endpoint == "poll" and exc.code == 409:
                return {"_http_status": 409}
            raise BridgeHTTPError(exc.code) from None
        except (URLError, TimeoutError, OSError) as exc:
            raise PublisherError("bridge endpoint is unreachable through the SSH tunnel") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PublisherError("bridge returned an invalid response") from exc
        if not isinstance(result, dict):
            raise PublisherError("bridge returned an invalid response")
        return result

    def register(self, identity: dict[str, Any], symbols: list[str]) -> None:
        result = self.post("register", {
            "account_id": self.account_id,
            "session_id": self.session_id,
            "terminal": identity,
            "symbols": symbols,
        })
        if result.get("read_only") is not True:
            raise PublisherError("VM100 bridge is not configured read-only; publisher stopped")
        self.session_id = str(result.get("session_id") or "")
        if not self.session_id:
            raise PublisherError("bridge did not return a session id")


def account_identity(terminal: Any, expected_login: int, expected_server: str) -> tuple[Any, Any, dict[str, Any]]:
    account = terminal.account_info()
    status = terminal.terminal_info()
    demo = getattr(terminal, "ACCOUNT_TRADE_MODE_DEMO", None)
    if (account is None or status is None or not status.connected or demo is None
            or getattr(account, "trade_mode", None) != demo
            or int(account.login) != expected_login
            or str(account.server) != expected_server):
        raise PublisherError("current terminal is not the expected authenticated Demo account")
    identity = {
        "login": str(account.login),
        "server": str(account.server),
        "trade_mode": "demo",
        "connected": True,
        "build": int(getattr(status, "build", 0) or 0),
    }
    return account, status, identity


def symbol_snapshot(terminal: Any, symbol: str) -> tuple[dict[str, Any], dict[str, Any]]:
    info = terminal.symbol_info(symbol)
    tick = terminal.symbol_info_tick(symbol)
    if info is None or tick is None or not bool(getattr(info, "visible", False)):
        raise PublisherError(f"symbol {symbol} is not visible with a current quote in Market Watch")
    bid, ask = float(tick.bid), float(tick.ask)
    point = float(info.point)
    if bid <= 0 or ask < bid or point <= 0:
        raise PublisherError(f"symbol {symbol} returned an invalid quote")
    spread = (ask - bid) / point
    quote = {"t": int(tick.time), "bid": bid, "ask": ask,
             "last": float(tick.last or (bid + ask) / 2)}
    spec = {
        "digits": int(info.digits), "point": point,
        "tick_size": float(getattr(info, "trade_tick_size", 0.0) or point),
        "contract_size": float(getattr(info, "trade_contract_size", 0.0) or 0.0),
        "min_lot": float(getattr(info, "volume_min", 0.0) or 0.0),
        "max_lot": float(getattr(info, "volume_max", 0.0) or 0.0),
        "lot_step": float(getattr(info, "volume_step", 0.0) or 0.0),
        "stops_level_points": float(getattr(info, "trade_stops_level", 0) or 0),
        "freeze_level_points": float(getattr(info, "trade_freeze_level", 0) or 0),
        "spread_typical_points": float(spread),
        "profit_currency": str(getattr(info, "currency_profit", "") or "USD"),
    }
    return quote, spec


def build_snapshot(terminal: Any, account: Any, status: Any, symbols: list[str],
                   *, include_rates: bool, rates_bars: int, include_positions: bool = False) -> dict[str, Any]:
    quotes: dict[str, Any] = {}
    specs: dict[str, Any] = {}
    rates: dict[str, Any] = {}
    for symbol in symbols:
        quote, spec = symbol_snapshot(terminal, symbol)
        quotes[symbol] = quote
        specs[symbol] = spec
        if include_rates:
            period_rates: dict[str, list[dict[str, Any]]] = {}
            for label, constant_name in TIMEFRAMES.items():
                period = getattr(terminal, constant_name)
                raw = terminal.copy_rates_from_pos(symbol, period, 0, rates_bars)
                if raw is None or len(raw) == 0:
                    continue
                period_rates[label] = [
                    {"t": int(bar["time"]), "o": float(bar["open"]),
                     "h": float(bar["high"]), "l": float(bar["low"]),
                     "c": float(bar["close"]), "v": int(bar["tick_volume"])}
                    for bar in raw
                ]
            if period_rates:
                rates[symbol] = period_rates

    positions = []
    positions_status = {"available": False, "captured_at": 0}
    if include_positions:
        raw_positions = terminal.positions_get()
        # Stop if the user switches terminal accounts during this read.
        account_identity(terminal, int(account.login), str(account.server))
        if raw_positions is not None:
            for position in raw_positions:
                if str(position.symbol) not in symbols:
                    continue
                if int(position.type) not in (terminal.POSITION_TYPE_BUY, terminal.POSITION_TYPE_SELL):
                    raise PublisherError("unsupported position type; publisher stopped")
                positions.append({"ticket": str(position.ticket), "symbol": str(position.symbol),
                                  "direction": "up" if position.type == terminal.POSITION_TYPE_BUY else "down",
                                  "entry": float(position.price_open), "sl": float(position.sl),
                                  "tp": float(position.tp), "volume": float(position.volume)})
            positions_status = {"available": True, "captured_at": time.time()}
    trade_mode = int(account.trade_mode)
    return {
        "server_time": int(time.time()),
        "account": {
            "login": str(account.login), "server": str(account.server),
            "trade_mode": "demo" if trade_mode == terminal.ACCOUNT_TRADE_MODE_DEMO else "other",
            "connected": bool(status.connected),
        },
        "quotes": quotes,
        "symbols": specs,
        "positions": positions,
        "positions_scope": "private" if include_positions else "unavailable",
        "positions_status": positions_status,
        "rates": rates,
        "rates_updated_at": int(time.time()) if include_rates else 0,
        "rates_unchanged": not include_rates,
        "terminal": {"build": int(getattr(status, "build", 0) or 0)},
    }


def run(args: argparse.Namespace) -> int:
    code_path = None
    if args.link_code_file:
        private_dir = (Path(os.environ.get("LOCALAPPDATA", "")) / "No7AITrading").resolve()
        code_path = Path(args.link_code_file).resolve()
        if code_path.parent != private_dir or not private_dir.is_dir() or not args.include_positions:
            raise PublisherError("link code must use the protected No7AITrading directory with --include-positions")
    if args.expected_login <= 0 or not args.expected_server.strip():
        raise PublisherError("an exact expected Demo login and server are required")
    if not args.symbols or any(not symbol.strip() for symbol in args.symbols):
        raise PublisherError("at least one exact Market Watch symbol is required")
    token = read_bridge_token(args.token_file)
    try:
        terminal_path = resolve_running_terminal(args.terminal)
    except TerminalDiscoveryError as exc:
        raise PublisherError(str(exc)) from exc
    try:
        import MetaTrader5 as terminal
    except ImportError as exc:
        raise PublisherError("MetaTrader5 package is not installed in this Python environment") from exc

    if not terminal.initialize(str(terminal_path), timeout=5000):
        raise PublisherError("could not attach to the already-running MT5 terminal")
    try:
        account, status, identity = account_identity(
            terminal, args.expected_login, args.expected_server)
        symbols = [symbol.strip() for symbol in args.symbols]
        # Check every requested symbol before authenticating this publisher session.
        for symbol in symbols:
            symbol_snapshot(terminal, symbol)
        client = BridgeClient(args.base_url, args.account_id, token)
        client.register(identity, symbols)
        print(f"MT5 read-only bridge connected to {identity['server']} for {len(symbols)} symbol(s)")

        last_rates_at = 0.0
        link_code_saved = False
        poll_seconds = max(0.25, args.poll_ms / 1000.0)
        rates_interval = max(5.0, args.rates_interval)
        while True:
            account, status, identity = account_identity(
                terminal, args.expected_login, args.expected_server)
            now = time.monotonic()
            include_rates = last_rates_at == 0.0 or now - last_rates_at >= rates_interval
            snapshot = build_snapshot(terminal, account, status, symbols,
                                      include_rates=include_rates, rates_bars=args.rates_bars,
                                      include_positions=args.include_positions)
            try:
                response = client.post("poll", {
                    "session_id": client.session_id,
                    "snapshot": snapshot,
                    "results": [],
                })
            except BridgeHTTPError as exc:
                if exc.status in (401, 403) or 400 <= exc.status < 500:
                    raise
                print(f"Bridge returned HTTP {exc.status}; retrying in 5 seconds")
                time.sleep(5)
                continue
            except PublisherError as exc:
                print(f"{exc}; retrying in 5 seconds")
                time.sleep(5)
                continue
            if response.get("_http_status") == 409:
                client.session_id = ""
                client.register(identity, symbols)
                last_rates_at = 0.0
                time.sleep(poll_seconds)
                continue
            if response.get("session_id") != client.session_id:
                client.session_id = ""
                client.register(identity, symbols)
                last_rates_at = 0.0
                continue
            commands = response.get("commands") or []
            if commands:
                # A market publisher never interprets or executes bridge commands.
                print(f"Read-only publisher ignored {len(commands)} command(s)")
            if include_rates:
                last_rates_at = now
            if code_path is not None and not link_code_saved:
                link = client.post("link-code", {"account_id": args.account_id, "session_id": client.session_id})
                code_path.write_text(str(link["code"]) + "\n", encoding="utf-8")
                link_code_saved = True
                print("One-use read-only terminal link code saved to the protected local file (10 minute expiry)")
            time.sleep(max(0.05, poll_seconds - (time.monotonic() - now)))
    except KeyboardInterrupt:
        return 0
    finally:
        terminal.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only MT5 market data bridge; no order support")
    parser.add_argument("--terminal", default="", help="optional administrator override; otherwise detect the running MT5 automatically")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080",
                        help="API URL through the local SSH tunnel")
    parser.add_argument("--account-id", default="mt5-bridge-demo")
    parser.add_argument("--expected-login", type=int, required=True)
    parser.add_argument("--expected-server", required=True)
    parser.add_argument("--symbols", default="XAUUSD.s",
                        help="comma-separated exact symbols already visible in Market Watch")
    parser.add_argument("--token-file", default="")
    parser.add_argument("--include-positions", action="store_true", help="read positions without sending any trade requests")
    parser.add_argument("--link-code-file", default="", help="protected local file for the one-use read-only account link code")
    parser.add_argument("--poll-ms", type=int, default=250)
    parser.add_argument("--rates-interval", type=float, default=5.0,
                        help="history refresh seconds (minimum 5; quotes poll independently)")
    parser.add_argument("--rates-bars", type=int, default=600)
    args = parser.parse_args()
    args.symbols = args.symbols.split(",")
    try:
        return run(args)
    except PublisherError as exc:
        print(f"BLOCKED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
