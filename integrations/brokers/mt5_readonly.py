"""Standalone demo-only diagnostics, never imported by the trading runtime."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys


class ProbeError(RuntimeError):
    """A safe diagnostic failure without terminal credentials or raw errors."""


def probe_demo(terminal, path: str, expected_login: int, expected_server: str,
               symbol: str, include_positions: bool = False) -> dict:
    """Attach to an already authenticated terminal; never login or send orders.

    Read-only describes this code path, not a terminal-wide permission sandbox.
    Other EAs or clients must be disabled/managed separately by the operator.
    """
    if expected_login <= 0 or not expected_server.strip() or not symbol.strip():
        raise ProbeError("Explicit account identity and symbol are required")

    def checked_account():
        info = terminal.account_info()
        demo = getattr(terminal, "ACCOUNT_TRADE_MODE_DEMO", None)
        if info is None or demo is None or getattr(info, "trade_mode", None) != demo:
            raise ProbeError("Only a verified demo account is allowed")
        if info.login != expected_login or info.server != expected_server:
            raise ProbeError("Account identity does not match the expected login/server")
        status = terminal.terminal_info()
        if status is None or not status.connected:
            raise ProbeError("Terminal is not connected to the broker")
        return info

    try:
        if not terminal.initialize(path, timeout=5000):
            raise ProbeError("MT5 initialize failed; open and authenticate the demo terminal manually")
        checked_account()
        tick = terminal.symbol_info_tick(symbol)
        info = checked_account()
        if tick is None:
            raise ProbeError("No quote available; check the exact symbol in Market Watch")
        bid, ask = float(tick.bid), float(tick.ask)
        if not all(math.isfinite(v) and v > 0 for v in (bid, ask)) or ask < bid:
            raise ProbeError("Quote is invalid")
        result = {"read_only": True, "execution_enabled": False,
                  "account_type": "demo", "server": info.server, "currency": info.currency,
                  "balance": float(info.balance), "equity": float(info.equity), "symbol": symbol,
                  "tick": {"bid": bid, "ask": ask, "time": int(tick.time)},
                  "note": "Last available quote only; timestamp does not guarantee a fresh/open market"}
        if include_positions:
            # None means MT5 could not read the position list; an empty tuple is
            # a valid, authoritative response meaning there are no open positions.
            raw_positions = terminal.positions_get()
            if raw_positions is None:
                raise ProbeError("MT5 could not read open positions; check terminal connection")
            buy = getattr(terminal, "POSITION_TYPE_BUY", 0)
            sell = getattr(terminal, "POSITION_TYPE_SELL", 1)
            rows = []
            for pos in raw_positions:
                kind = getattr(pos, "type", None)
                if kind not in (buy, sell):
                    raise ProbeError("MT5 returned an unsupported position type")
                direction = "up" if kind == buy else "down"
                raw_sl, raw_tp = float(pos.sl), float(pos.tp)
                values = {
                    "volume": float(pos.volume), "entry": float(pos.price_open),
                    # MT5 uses zero to mean no broker stop/target.
                    "sl": raw_sl if raw_sl > 0 else None,
                    "tp": raw_tp if raw_tp > 0 else None,
                    "current_price": float(pos.price_current), "unrealized": float(pos.profit),
                }
                numeric_values = [v for v in values.values() if v is not None]
                if (not all(math.isfinite(v) for v in numeric_values)
                        or values["volume"] <= 0 or values["entry"] <= 0
                        or values["current_price"] <= 0):
                    raise ProbeError("MT5 returned invalid position values")
                rows.append({
                    "ticket": str(int(pos.ticket)), "symbol": str(pos.symbol),
                    "direction": direction, **values, "open_time": int(pos.time),
                    "broker_id": "mt5-read-only",
                })
            checked_account()  # Re-check identity after the broker read.
            result["positions"] = rows
            result["count"] = len(rows)
        return result
    finally:
        terminal.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description="Demo-only MT5 status/quote probe; no orders")
    parser.add_argument("--terminal", required=True)
    parser.add_argument("--expected-login", required=True, type=int)
    parser.add_argument("--expected-server", required=True)
    parser.add_argument("--symbol", default="XAUUSD")
    args = parser.parse_args()
    if sys.platform != "win32" or not Path(args.terminal).is_file():
        print("BLOCKED: Windows and an explicit installed terminal path are required")
        return 1
    try:
        import MetaTrader5 as terminal
    except ImportError:
        print("BLOCKED: install requirements-mt5.txt in the project virtual environment")
        return 1
    try:
        result = probe_demo(terminal, args.terminal, args.expected_login,
                            args.expected_server, args.symbol)
    except ProbeError as exc:
        print(f"BLOCKED: {exc}")
        return 1
    except Exception:
        print("BLOCKED: MT5 diagnostic failed; terminal details were withheld for privacy")
        return 1
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
