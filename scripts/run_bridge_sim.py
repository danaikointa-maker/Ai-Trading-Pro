"""A simulated MT5 Expert Advisor: the bridge's counterpart, so the protocol is testable now.

It speaks exactly the same wire protocol as `bridge/No7BridgeEA.mq5`:

    register -> loop { execute last commands -> push snapshot + results -> poll }

The difference is only what sits behind the loop: this one fills orders from a seeded
random walk in memory, while the MQL5 EA calls the real terminal. That means the server
side (queue, single delivery, expiry, freshness, staleness refusal) is exercised for
real, and when a Windows terminal is available only the client changes.

    .venv/bin/python scripts/run_bridge_sim.py --server http://127.0.0.1:8000 \
        --account mt5-bridge-demo --token "$NO7_BRIDGE_TOKEN" --duration 120

This is a test instrument, not a trading system: it has no slippage model, one price
per symbol and no persistence.
"""
from __future__ import annotations

import argparse
import json
import random
import signal
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class SimPosition:
    ticket: str
    symbol: str
    direction: str          # buy | sell
    volume: float
    price_open: float
    sl: float
    tp: float
    time: int
    comment: str = ""

    def unrealized(self, spec_point: float, contract: float, last: float) -> tuple[float, float]:
        sign = 1.0 if self.direction == "buy" else -1.0
        points = (last - self.price_open) * sign / spec_point
        return points, points * spec_point * contract * self.volume


@dataclass
class SimAccount:
    login: str = "51234567"
    currency: str = "USD"
    balance: float = 10_000.0
    leverage: int = 500
    server: str = "Connext-Demo"


class SimTerminal:
    """Minimal stand-in for a terminal: quotes, positions, fills, SL/TP."""

    def __init__(self, symbols: dict[str, dict[str, Any]], seed: int = 7,
                 spread_points: int = 25) -> None:
        self.symbols = symbols
        self.spread_points = spread_points
        self.rng = random.Random(seed)
        self.prices = {s: float(spec.get("start_price", 2000.0)) for s, spec in symbols.items()}
        self.positions: dict[str, SimPosition] = {}
        self.closed: list[dict[str, Any]] = []
        self.account = SimAccount()
        self.next_ticket = 55000

    def _quote(self, symbol: str) -> dict[str, float]:
        spec = self.symbols[symbol]
        point = float(spec.get("point", 0.01))
        # calm random walk; the demo is about the protocol, not about realism
        self.prices[symbol] = max(point, self.prices[symbol] + self.rng.gauss(0, 0.35))
        mid = self.prices[symbol]
        half = self.spread_points * point / 2
        return {"t": time.time(), "bid": round(mid - half, 5), "ask": round(mid + half, 5),
                "last": round(mid, 5)}

    def _close(self, position: SimPosition, price: float, reason: str) -> None:
        spec = self.symbols[position.symbol]
        sign = 1.0 if position.direction == "buy" else -1.0
        profit = (price - position.price_open) * sign * float(spec.get("contract_size", 100)) \
            * position.volume
        self.account.balance += profit
        self.closed.append({"ticket": position.ticket, "symbol": position.symbol,
                            "profit": round(profit, 2), "reason": reason,
                            "price": price, "time": int(time.time())})
        print(f"  [ea] closed {position.ticket} {position.symbol} at {price} "
              f"({reason}) pnl {profit:+.2f}", flush=True)
        self.positions.pop(position.ticket, None)

    def step(self) -> dict[str, dict[str, float]]:
        quotes = {symbol: self._quote(symbol) for symbol in self.symbols}
        for position in list(self.positions.values()):
            quote = quotes[position.symbol]
            exit_price = quote["bid"] if position.direction == "buy" else quote["ask"]
            if position.sl and ((position.direction == "buy" and exit_price <= position.sl)
                                or (position.direction == "sell" and exit_price >= position.sl)):
                self._close(position, position.sl, "sl")
            elif position.tp and ((position.direction == "buy" and exit_price >= position.tp)
                                  or (position.direction == "sell" and exit_price <= position.tp)):
                self._close(position, position.tp, "tp")
        return quotes

    def snapshot(self, quotes: dict[str, dict[str, float]], rates: bool) -> dict[str, Any]:
        equity = self.account.balance + sum(
            p.unrealized(float(self.symbols[p.symbol]["point"]),
                         float(self.symbols[p.symbol].get("contract_size", 100)),
                         quotes[p.symbol]["bid"] if p.direction == "buy" else quotes[p.symbol]["ask"])[1]
            for p in self.positions.values())
        now = int(time.time())
        payload: dict[str, Any] = {
            "server_time": time.time(),
            "account": {"login": self.account.login, "balance": round(self.account.balance, 2),
                        "equity": round(equity, 2), "margin": 0.0,
                        "free_margin": round(equity, 2), "currency": self.account.currency,
                        "leverage": self.account.leverage, "server": self.account.server},
            "quotes": quotes,
            "symbols": {s: {"digits": spec.get("digits", 2), "point": spec.get("point", 0.01),
                            "contract_size": spec.get("contract_size", 100),
                            "min_lot": spec.get("min_lot", 0.01)}
                        for s, spec in self.symbols.items()},
            "positions": [{
                "ticket": p.ticket, "symbol": p.symbol, "direction": p.direction,
                "volume": p.volume, "price_open": p.price_open, "sl": p.sl, "tp": p.tp,
                "time": p.time, "price_current": quotes[p.symbol]["bid"],
                "profit": round(p.unrealized(float(self.symbols[p.symbol]["point"]),
                                             float(self.symbols[p.symbol].get("contract_size", 100)),
                                             quotes[p.symbol]["bid"])[1], 2),
                "comment": p.comment,
            } for p in self.positions.values()],
        }
        if rates:
            base = next(iter(self.symbols))
            price = self.prices[base]
            payload["rates"] = {base: {"M1": [
                {"t": now - 60 * (20 - i), "o": round(price - 0.4, 5), "h": round(price + 0.6, 5),
                 "l": round(price - 0.7, 5), "c": round(price + 0.2, 5), "v": 120}
                for i in range(20)]}}
        return payload

    def execute(self, command: dict[str, Any]) -> dict[str, Any]:
        kind, payload = command.get("kind"), command.get("payload") or {}
        try:
            if kind == "ping":
                return {"ok": True, "status": "pong", "message": "alive"}
            if kind == "order":
                symbol = str(payload.get("symbol"))
                spec = self.symbols[symbol]
                quote = self._quote(symbol)
                side = str(payload.get("side") or "buy").lower()
                direction = "buy" if side in ("buy", "up", "long") else "sell"
                # buying lifts the ask, selling hits the bid — the spread is paid once
                price = quote["ask"] if direction == "buy" else quote["bid"]
                self.next_ticket += 1
                ticket = str(self.next_ticket)
                position = SimPosition(
                    ticket=ticket, symbol=symbol, direction=direction,
                    volume=float(payload.get("volume") or 0.01), price_open=price,
                    sl=float(payload.get("sl") or 0.0), tp=float(payload.get("tp") or 0.0),
                    time=int(time.time()), comment=str(payload.get("comment") or "")[:31])
                self.positions[ticket] = position
                print(f"  [ea] filled {ticket} {direction} {position.volume} {symbol} @ {price}",
                      flush=True)
                return {"ok": True, "status": "filled", "ticket": ticket, "price": price,
                        "volume": position.volume,
                        "retcode": 10009, "message": "sim fill", "price_point": spec.get("point")}
            if kind == "modify":
                position = self.positions.get(str(payload.get("ticket")))
                if position is None:
                    return {"ok": False, "error": f"no such position {payload.get('ticket')}"}
                if payload.get("sl") is not None:
                    position.sl = float(payload["sl"])
                if payload.get("tp") is not None:
                    position.tp = float(payload["tp"])
                print(f"  [ea] modified {position.ticket} sl={position.sl} tp={position.tp}",
                      flush=True)
                return {"ok": True, "status": "modified", "ticket": position.ticket}
            if kind == "close":
                position = self.positions.get(str(payload.get("ticket")))
                if position is None:
                    return {"ok": False, "error": f"no such position {payload.get('ticket')}"}
                quote = self._quote(position.symbol)
                price = quote["bid"] if position.direction == "buy" else quote["ask"]
                self._close(position, price, "ea close")
                return {"ok": True, "status": "closed", "ticket": position.ticket,
                        "price": price, "volume": position.volume, "retcode": 10009}
            return {"ok": False, "error": f"unknown command kind {kind!r}"}
        except Exception as exc:  # noqa: BLE001 - the EA must always answer
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


class BridgeClient:
    def __init__(self, server: str, account: str, token: str, session_id: str) -> None:
        self.server = server.rstrip("/")
        self.account = account
        self.token = token
        self.session_id = session_id

    def _post(self, path: str, body: dict[str, Any], *, token: bool = False,
              timeout: float = 10.0) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(self.server + path, method="POST",
                                         data=json.dumps(body).encode())
        request.add_header("Content-Type", "application/json")
        if token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read() or b"{}")
            except json.JSONDecodeError:
                return exc.code, {"detail": "non-json error"}

    def register(self, symbols: list[str]) -> dict[str, Any]:
        status, body = self._post("/api/bridge/register", {
            "account_id": self.account, "session_id": self.session_id,
            "symbols": symbols,
            "terminal": {"build": 4020, "company": "No7 bridge simulator",
                         "name": "run_bridge_sim.py"}}, token=True)
        if status != 200:
            raise SystemExit(f"register failed ({status}): {body}")
        return body

    def poll(self, snapshot: dict[str, Any] | None,
             results: list[dict[str, Any]]) -> tuple[int, dict[str, Any]]:
        return self._post("/api/bridge/poll",
                          {"session_id": self.session_id, "snapshot": snapshot,
                           "results": results}, token=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulated MT5 Expert Advisor for the bridge")
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--account", default="mt5-bridge-demo")
    parser.add_argument("--token", default="")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--symbols", default="XAUUSD")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--duration", type=float, default=60.0, help="seconds to run (0 = forever)")
    parser.add_argument("--rates", action="store_true", help="also push M1 rates")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    if not args.token:
        print("error: --token is required (the bridge token configured on the server)",
              file=sys.stderr)
        return 2

    symbols = {name.strip().upper(): {"digits": 2, "point": 0.01, "contract_size": 100,
                                      "min_lot": 0.01, "start_price": 2000.0}
               for name in args.symbols.split(",") if name.strip()}
    terminal = SimTerminal(symbols, seed=args.seed)
    session_id = args.session_id or f"EA-SIM-{int(time.time()) % 100000}"
    client = BridgeClient(args.server, args.account, args.token, session_id)

    info = client.register(list(symbols))
    print(f"[ea] registered {args.account} session={info['session_id']} "
          f"generation={info['generation']} poll={info['poll_interval_ms']}ms "
          f"fresh={info['fresh_seconds']}s stale={info['stale_seconds']}s", flush=True)

    stopping = {"flag": False}

    def _stop(*_: Any) -> None:
        stopping["flag"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    started = time.time()
    results: list[dict[str, Any]] = []
    polls = 0
    while not stopping["flag"]:
        if args.duration and time.time() - started >= args.duration:
            break
        quotes = terminal.step()
        status, body = client.poll(terminal.snapshot(quotes, rates=args.rates), results)
        if status == 409:
            print(f"[ea] session lost ({body.get('detail')}); re-registering", flush=True)
            info = client.register(list(symbols))
            results = []
            continue
        if status != 200:
            print(f"[ea] poll failed {status}: {body}", flush=True)
            time.sleep(args.interval)
            continue
        polls += 1
        results = []
        for command in body.get("commands") or []:
            if not args.quiet:
                print(f"[ea] <- {command['id']} {command['kind']} {command['payload']}", flush=True)
            outcome = terminal.execute(command)
            results.append({"id": command["id"], **outcome})
        # Results travel with the *next* poll, exactly like the MQL5 EA: the server is
        # the only place that decides whether a fill happened, and it hears about it once.
        if body.get("expired_unacked") and not args.quiet:
            for dead in body["expired_unacked"]:
                print(f"[ea] ! command {dead['id']} expired before ack — "
                      f"it may have executed; check the terminal", flush=True)
        time.sleep(max(0.05, args.interval))

    print(f"[ea] stopped after {polls} polls; open positions "
          f"{len(terminal.positions)}, closed {len(terminal.closed)}, "
          f"balance {terminal.account.balance:.2f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
