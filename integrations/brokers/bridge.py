"""Broker adapter backed by an MQL5 Expert Advisor over the bridge relay.

Above this file nothing knows whether orders go to a simulated account, the MT5
Python package, or an EA polling the API — it is the same `BrokerAdapter`.

The adapter's one rule: **it will not serve old data.** Quotes, account state and
positions exist only as the last snapshot the EA pushed. Once that snapshot is older
than `stale_seconds` the adapter reports stale/disconnected and raises on price and
position reads, instead of handing the risk engine yesterday's equity or a minute-old
quote that looks live.
"""
from __future__ import annotations

import math
import time
from typing import Any

import pandas as pd

from integrations.brokers.base import BrokerAdapter, BrokerError
from packages.shared_schemas.models import (
    AccountInfo,
    Direction,
    Health,
    OrderRequest,
    OrderResult,
    OrderState,
    Position,
    SymbolSpec,
    Tick,
    TradeRecord,
)
from services.bridge.relay import BridgeError, BridgeRelay

STATE_MAP = {
    "filled": OrderState.filled,
    "partial": OrderState.partially_filled,
    "partially_filled": OrderState.partially_filled,
    "rejected": OrderState.rejected,
    "cancelled": OrderState.cancelled,
    "canceled": OrderState.cancelled,
    "submitted": OrderState.submitted,
    "pending": OrderState.pending,
}


class BridgeBroker(BrokerAdapter):
    adapter_type = "bridge"

    def __init__(self, profile: dict[str, Any], relay: BridgeRelay, *,
                 order_timeout: float | None = None) -> None:
        self.profile = profile
        self.relay = relay
        self.id = profile["id"]
        self.label = profile.get("label", profile["id"])
        self.server = profile.get("server", "")
        self.account_type = profile.get("account_type", "demo")
        self.live_allowed = bool(profile.get("live_allowed", False))
        self.regulated_note = (profile.get("regulated_note") or "").strip()
        self.declared = profile.get("symbols") or {}
        self.account_id = profile.get("bridge_account") or profile["id"]
        self.order_timeout = float(order_timeout if order_timeout is not None
                                   else relay.order_timeout_seconds)
        self.last_command: dict[str, Any] | None = None

    # ------------------------------------------------------------- health/data
    def health(self) -> Health:
        state = self.relay.session_health(self.account_id)
        return {"connected": Health.connected, "stale": Health.stale}.get(state,
                                                                          Health.disconnected)

    def _snapshot(self) -> dict[str, Any]:
        session = self.relay.get(self.account_id)
        if session is None:
            raise BrokerError(f"no EA session for {self.account_id!r}: start the bridge EA "
                              f"(it must call /api/bridge/register)")
        age = self.relay.snapshot_age(self.account_id) or 0.0
        if age > self.relay.stale_seconds:
            raise BrokerError(
                f"bridge snapshot is {age:.0f}s old (limit {self.relay.stale_seconds:.0f}s): "
                f"refusing to serve stale account/position data")
        return session.snapshot

    def _require_connected(self) -> None:
        state = self.relay.session_health(self.account_id)
        if state != "connected":
            age = self.relay.age(self.account_id)
            raise BrokerError(f"EA bridge for {self.account_id!r} is {state}"
                              + (f" (last poll {age:.1f}s ago)" if age is not None
                                 else " (never connected)"))

    def account_info(self) -> AccountInfo:
        snapshot = self._snapshot()
        account = snapshot.get("account") or {}
        if not account:
            raise BrokerError("bridge snapshot carries no account section yet")
        return AccountInfo(
            broker_id=self.id,
            label=self.label,
            server=str(account.get("server") or self.server),
            account_type=self.account_type,
            login=str(account.get("login") or "—"),
            currency=str(account.get("currency") or "USD"),
            balance=float(account.get("balance") or 0.0),
            equity=float(account.get("equity") or account.get("balance") or 0.0),
            margin=float(account.get("margin") or 0.0),
            free_margin=float(account.get("free_margin") or account.get("equity") or 0.0),
            leverage=int(account.get("leverage") or 100),
            health=self.health(),
            adapter=self.adapter_type,
            live_allowed=self.live_allowed,
        )

    def symbol_names(self) -> list[str]:
        reported = self.relay.symbols(self.account_id)
        return reported or list(self.declared)

    def symbol_spec(self, symbol: str) -> SymbolSpec:
        """Contract specs come from the EA when it reports them, else from the profile."""
        snapshot = self.relay.snapshot(self.account_id)
        reported = (snapshot.get("symbols") or {}).get(symbol) or {}
        declared = self.declared.get(symbol) or {}
        if not reported and not declared:
            raise BrokerError(f"symbol spec unavailable for {symbol}")
        merged = {**declared, **{k: v for k, v in reported.items() if v is not None}}
        merged.setdefault("symbol", symbol)
        required = {"digits", "point", "tick_size", "contract_size", "min_lot",
                    "max_lot", "lot_step", "profit_currency"}
        merged["spec_complete"] = required.issubset(merged)
        merged["source"] = "broker" if reported else "declared"
        account_currency = str((snapshot.get("account") or {}).get("currency") or "").strip().upper()
        rate_currency = str(merged.get("account_currency") or "USD").strip().upper()
        merged["account_currency"] = account_currency
        profit = str(merged.get("profit_currency") or "").strip().upper()
        if profit and account_currency and profit == account_currency:
            merged.update(quote_to_account_rate=1.0, rate_source="identity")
        elif not account_currency or rate_currency != account_currency:
            merged.update(quote_to_account_rate=1.0, rate_source="unknown")
        return SymbolSpec(**merged)

    def ticker(self, symbol: str) -> Tick:
        quotes = self._snapshot().get("quotes") or {}
        quote = quotes.get(symbol)
        if not quote:
            raise BrokerError(f"bridge snapshot has no quote for {symbol}")
        bid, ask = float(quote.get("bid") or 0.0), float(quote.get("ask") or 0.0)
        if bid <= 0 or ask <= 0 or ask < bid:
            raise BrokerError(f"bridge quote for {symbol} is unusable (bid={bid}, ask={ask})")
        spec = self.symbol_spec(symbol)
        return Tick(t=float(quote.get("t") or time.time()), bid=bid, ask=ask,
                    spread_points=round((ask - bid) / spec.point, 1),
                    last=float(quote.get("last") or (bid + ask) / 2))

    def candles(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        """Rates the EA forwarded. Nothing is synthesised here: absent means an error."""
        rates = (self._snapshot().get("rates") or {})
        bars = ((rates.get(symbol) or {}).get(timeframe)) or []
        if not bars:
            raise BrokerError(
                f"the bridge has no {timeframe} rates for {symbol}; run the EA with "
                f"'push_rates' enabled or keep feed_mode=simulate until it reports them")
        frame = pd.DataFrame(bars)
        required = {"t", "o", "h", "l", "c"}
        missing = required - set(frame.columns)
        if missing:
            raise BrokerError(f"bridge rates for {symbol} are missing {sorted(missing)}")
        if "v" not in frame.columns:
            frame["v"] = 0.0
        frame = frame.sort_values("t").tail(int(limit)).reset_index(drop=True)
        for column in ("o", "h", "l", "c", "v"):
            frame[column] = frame[column].astype(float)
        frame["t"] = frame["t"].astype("int64")
        return frame[["t", "o", "h", "l", "c", "v"]]

    # --------------------------------------------------------------- trading
    def _run_command(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Queue one command, wait for its single acknowledgement."""
        self._require_connected()
        try:
            command = self.relay.enqueue(self.account_id, kind, payload)
        except BridgeError as exc:
            raise BrokerError(str(exc)) from exc
        self.last_command = {"id": command.id, "kind": kind, "seq": command.seq,
                            "payload": payload}
        result = self.relay.wait_result(self.account_id, command.id, timeout=self.order_timeout)
        if result is None:
            raise BrokerError(
                f"EA did not acknowledge {kind} {command.id} within {self.order_timeout:.0f}s "
                f"(it may still execute; the command is not re-sent — check the terminal)")
        if result.get("ok") is False:
            raise BrokerError(f"EA rejected {kind}: {result.get('error') or result}")
        return result

    def order_send(self, request: OrderRequest, ticket_hint: str = "") -> OrderResult:
        payload = {
            "symbol": request.symbol,
            "side": request.side.value,
            "volume": request.volume,
            "price": request.price,
            "sl": request.sl,
            "tp": request.tp,
            "comment": (request.comment or "")[:31],
            "signal_id": request.signal_id,
            "idempotency_key": request.idempotency_key,
        }
        started = time.time()
        result = self._run_command("order", payload)
        state = STATE_MAP.get(str(result.get("status") or "").lower(), OrderState.rejected)
        if state == OrderState.rejected and result.get("ok"):
            state = OrderState.submitted
        return OrderResult(
            order_id=str(result.get("ticket") or ""),
            idempotency_key=request.idempotency_key or "",
            status=state,
            retcode=int(result.get("retcode") or 0),
            message=str(result.get("message") or "executed by the EA bridge"),
            ticket=str(result["ticket"]) if result.get("ticket") else None,
            filled_volume=float(result.get("volume") or 0.0),
            fill_price=float(result["price"]) if result.get("price") is not None else None,
            slippage_points=float(result.get("slippage_points") or 0.0),
            latency_ms=round((time.time() - started) * 1000, 1),
            verified=bool(result.get("ticket")),
            created_at=time.time(),
        )

    def modify_position(self, ticket: str, sl: float | None = None,
                        tp: float | None = None) -> bool:
        result = self._run_command("modify", {"ticket": str(ticket), "sl": sl, "tp": tp})
        return bool(result.get("ok", True))

    def close_position(self, ticket: str, volume: float | None = None,
                       comment: str = "") -> OrderResult:
        if volume is not None and (type(volume) not in (int, float)
                                   or not math.isfinite(volume) or volume <= 0):
            raise BrokerError("invalid close volume; no command queued")
        try:
            result = self._run_command("close", {"ticket": str(ticket), "volume": volume,
                                                "comment": (comment or "")[:31]})
        except Exception:
            # Transport exceptions and EA error payloads may contain account
            # details; neither is authoritative rejection evidence.
            raise BrokerError("close outcome unknown; reconcile before resending") from None
        # A command receipt is not a fresh exposure read. Never synthesize closure
        # or fill volume from missing fields or the requested amount.
        if not isinstance(result, dict) or type(result.get("status")) is not str:
            raise BrokerError("close acknowledgement malformed; outcome unknown, reconcile before resending")
        status = {"closed": OrderState.closed, "filled": OrderState.filled}.get(result.get("status"))
        reported_volume = result.get("volume")
        reported_price = result.get("price")
        retcode = result.get("retcode")
        if (result.get("ok") is not True or status is None
                or str(result.get("ticket", "")) != str(ticket)
                or type(reported_volume) not in (int, float)
                or not math.isfinite(reported_volume) or reported_volume <= 0
                or (volume is not None and reported_volume > volume + 1e-9)
                or type(reported_price) not in (int, float) or not math.isfinite(reported_price)
                or reported_price <= 0
                or (retcode is not None and (type(retcode) is not int or retcode != 10009))):
            raise BrokerError("close acknowledgement incomplete or inconsistent; outcome unknown, reconcile before resending")
        return OrderResult(
            order_id=str(result.get("ticket") or ticket),
            idempotency_key=str(result.get("idempotency_key") or ""),
            status=status,
            retcode=int(result.get("retcode") or 0),
            message="Close acknowledgement received; remaining exposure not verified",
            ticket=str(result.get("ticket") or ticket),
            filled_volume=float(reported_volume),
            fill_price=float(reported_price),
            verified=False,
            created_at=time.time(),
        )

    def positions(self) -> list[Position]:
        """The EA's snapshot *is* the position list — replaced, never merged."""
        rows = self._snapshot().get("positions")
        if not isinstance(rows, list):
            raise BrokerError("bridge snapshot has no valid positions list")
        out: list[Position] = []
        for row in rows:
            direction = Direction.up if str(row.get("direction", "buy")).lower() in (
                "buy", "up", "long") else Direction.down
            out.append(Position(
                ticket=str(row.get("ticket")),
                broker_id=self.id,
                symbol=str(row.get("symbol")),
                direction=direction,
                volume=float(row.get("volume") or 0.0),
                entry=float(row.get("price_open") or row.get("entry") or 0.0),
                sl=float(row.get("sl") or 0.0),
                tp=float(row.get("tp") or 0.0),
                open_time=int(row.get("time") or 0),
                current_price=float(row.get("price_current") or row.get("price_open") or 0.0),
                points=float(row.get("points") or 0.0),
                unrealized=float(row.get("profit") or 0.0),
                comment=str(row.get("comment") or ""),
                signal_id=row.get("signal_id"),
                strategy=str(row.get("strategy") or ""),
                partials_done=int(row.get("partials_done") or 0),
                max_favorable_points=float(row.get("max_favorable_points") or 0.0),
            ))
        return out

    # -------------------------------------------------------------- lifecycle
    def closed_trades(self) -> list[TradeRecord]:
        return []

    def describe(self) -> dict[str, Any]:
        base = {
            "id": self.id, "label": self.label, "adapter": self.adapter_type,
            "server": self.server, "account_type": self.account_type,
            "health": self.health().value, "live_allowed": self.live_allowed,
            "regulated_note": self.regulated_note, "symbols": self.symbol_names(),
            "bridge_account": self.account_id,
            "bridge_session": (session.session_id if (session := self.relay.get(self.account_id))
                               else None),
            "last_command": self.last_command,
        }
        try:
            base["account"] = self.account_info().model_dump()
        except BrokerError as exc:
            base["account"] = None
            base["error"] = str(exc)
        return base
