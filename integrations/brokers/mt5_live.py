"""Real MetaTrader 5 adapter (Windows host with the MT5 terminal installed).

Requires the official ``MetaTrader5`` Python package and a running terminal.
Every call is wrapped so the API keeps serving (health = disconnected) when the
terminal is missing — the dashboard degrades instead of crashing.

Safety notes
------------
* ``order_send`` never retries on its own; the execution gateway owns retries
  and always re-reads positions before re-sending (idempotency).
* Filling mode is negotiated from ``symbol_info.filling_mode`` because brokers
  differ (IOC / FOK / RETURN).
* Volume is snapped to the broker's ``volume_step`` before it is sent.
"""
from __future__ import annotations

import time
from typing import Any

import pandas as pd

from integrations.brokers.base import BrokerAdapter, BrokerError
from integrations.brokers.fx import resolve_quote_rate
from packages.shared_schemas.models import (
    AccountInfo,
    Direction,
    Health,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderState,
    Position,
    SymbolSpec,
    Tick,
    TradeRecord,
)

try:  # pragma: no cover - only importable on a Windows host with MT5 installed
    import MetaTrader5 as mt5  # type: ignore
    MT5_AVAILABLE = True
except Exception:  # noqa: BLE001
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False

TIMEFRAME_MAP = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 16385, "H4": 16388, "D1": 16408,
}


class MT5Broker(BrokerAdapter):
    adapter_type = "mt5"

    def __init__(self, profile: dict[str, Any], terminal_path: str = "", login: int | None = None,
                 password: str = "", server: str = "", timeout_ms: int = 5000) -> None:
        self.profile = profile
        self.id = profile["id"]
        self.label = profile.get("label", profile["id"])
        self.server = server or profile.get("server", "")
        self.account_type = profile.get("account_type", "demo")
        self.live_allowed = bool(profile.get("live_allowed", False))
        self.regulated_note = (profile.get("regulated_note") or "").strip()
        self.terminal_path = terminal_path
        self.login = login
        self.password = password
        self.timeout_ms = timeout_ms
        self.declared = profile.get("symbols") or {}
        self.symbol_mapping = profile.get("symbol_mapping") or {}
        self._connected = False
        self._last_error = ""
        self._magic = 70707

    # ------------------------------------------------------------- connection
    def connect(self) -> bool:
        if not MT5_AVAILABLE:
            self._last_error = ("MetaTrader5 package is not installed on this host "
                                "(expected on Linux/CI). Use a demo simulated profile.")
            return False
        try:
            kwargs: dict[str, Any] = {"timeout": self.timeout_ms}
            if self.terminal_path:
                kwargs["path"] = self.terminal_path
            if self.login:
                kwargs.update(login=int(self.login), password=self.password, server=self.server)
            if not mt5.initialize(**kwargs):
                self._last_error = f"initialize failed: {mt5.last_error()}"
                self._connected = False
                return False
            info = mt5.account_info()
            if info is None:
                self._last_error = "account_info() returned None (terminal not logged in)"
                self._connected = False
                return False
            self._connected = True
            self._last_error = ""
            return True
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            self._connected = False
            return False

    def health(self) -> Health:
        if not self._connected:
            return Health.disconnected
        if not MT5_AVAILABLE:
            return Health.disconnected
        info = mt5.terminal_info() if MT5_AVAILABLE else None
        if info is None:
            return Health.stale
        return Health.connected if info.connected else Health.degraded

    def _require(self) -> None:
        if not self._connected:
            raise BrokerError(self._last_error or "MT5 terminal is not connected", retcode=-1)

    def _broker_symbol(self, symbol: str) -> str:
        return self.symbol_mapping.get(symbol, symbol)

    def symbol_names(self) -> list[str]:
        return list(self.declared)

    # -------------------------------------------------------------- metadata
    def account_info(self) -> AccountInfo:
        if not self._connected or not MT5_AVAILABLE:
            return AccountInfo(
                broker_id=self.id, label=self.label, server=self.server, account_type=self.account_type,
                balance=0.0, equity=0.0, free_margin=0.0, health=Health.disconnected,
                adapter=self.adapter_type, live_allowed=self.live_allowed,
                message=self._last_error or "MT5 terminal not connected",
                regulated_note=self.regulated_note, last_sync=time.time(),
            )
        info = mt5.account_info()
        if info is None:
            raise BrokerError(f"account_info failed: {mt5.last_error()}")
        return AccountInfo(
            broker_id=self.id, label=self.label, server=self.server, account_type=self.account_type,
            login=str(info.login), currency=info.currency, balance=float(info.balance), equity=float(info.equity),
            margin=float(info.margin), free_margin=float(info.margin_free), leverage=int(info.leverage),
            health=self.health(), adapter=self.adapter_type, live_allowed=self.live_allowed,
            last_sync=time.time(), message="", regulated_note=self.regulated_note,
        )

    def symbol_spec(self, symbol: str) -> SymbolSpec:
        if not self._connected or not MT5_AVAILABLE:
            raw = self.declared.get(symbol)
            if not raw:
                raise BrokerError(f"symbol {symbol} unknown and MT5 is offline")
            return SymbolSpec(symbol=symbol, source="declared", **raw)
        broker_symbol = self._broker_symbol(symbol)
        info = mt5.symbol_info(broker_symbol)
        if info is None:
            raise BrokerError(f"symbol_info({broker_symbol}) failed: {mt5.last_error()}")
        if not info.visible:
            mt5.symbol_select(broker_symbol, True)
        rate, rate_source = self._quote_rate(str(info.currency_profit))
        return SymbolSpec(
            symbol=symbol,
            description=info.description,
            quote_to_account_rate=rate,
            rate_source=rate_source,
            digits=int(info.digits),
            point=float(info.point),
            tick_size=float(info.trade_tick_size or info.point),
            contract_size=float(info.trade_contract_size),
            min_lot=float(info.volume_min),
            max_lot=float(info.volume_max),
            lot_step=float(info.volume_step),
            stops_level_points=float(info.trade_stops_level),
            freeze_level_points=float(info.trade_freeze_level),
            spread_typical_points=float(info.spread),
            commission_per_lot_round_turn=0.0,
            profit_currency=info.currency_profit,
            source="broker",
        )

    def _quote_rate(self, profit_currency: str) -> tuple[float, str]:
        """Resolve profit currency -> account currency using visible MT5 quotes."""
        account_currency = "USD"
        try:
            account = mt5.account_info()
            if account is not None and getattr(account, "currency", None):
                account_currency = str(account.currency)
        except Exception:  # noqa: BLE001 - account_info is best effort
            pass

        def price_of(name: str) -> float | None:
            for candidate in (name, self._broker_symbol(name)):
                tick = mt5.symbol_info_tick(candidate)
                if tick is not None and tick.bid and tick.ask:
                    return (float(tick.bid) + float(tick.ask)) / 2.0
            return None

        return resolve_quote_rate(profit_currency, account_currency, price_of)

    def ticker(self, symbol: str) -> Tick:
        self._require()
        tick = mt5.symbol_info_tick(self._broker_symbol(symbol))
        if tick is None:
            raise BrokerError(f"no tick for {symbol}: {mt5.last_error()}")
        spec = self.symbol_spec(symbol)
        spread = (tick.ask - tick.bid) / spec.point if spec.point else 0.0
        return Tick(t=float(tick.time), bid=float(tick.bid), ask=float(tick.ask),
                    spread_points=round(spread, 1), last=float(tick.last or tick.bid))

    def candles(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        self._require()
        tf = TIMEFRAME_MAP.get(timeframe, 1)
        rates = mt5.copy_rates_from_pos(self._broker_symbol(symbol), tf, 0, int(limit))
        if rates is None or len(rates) == 0:
            raise BrokerError(f"no rates for {symbol} {timeframe}: {mt5.last_error()}")
        df = pd.DataFrame(rates)
        df = df.rename(columns={"time": "t", "tick_volume": "v"})[["t", "open", "high", "low", "close", "v"]]
        df.columns = ["t", "o", "h", "l", "c", "v"]
        return df.astype({"t": "int64"})

    # --------------------------------------------------------------- trading
    def positions(self) -> list[Position]:
        self._require()
        raw = mt5.positions_get() or []
        out: list[Position] = []
        for p in raw:
            spec = self.symbol_spec(p.symbol)
            direction = Direction.up if p.type == 0 else Direction.down
            tick = mt5.symbol_info_tick(p.symbol)
            current = float(tick.bid if direction == Direction.up and tick else (tick.ask if tick else p.price_current))
            out.append(Position(
                ticket=str(p.ticket), symbol=p.symbol, direction=direction, volume=float(p.volume),
                entry=float(p.price_open), sl=float(p.sl), tp=float(p.tp), open_time=int(p.time),
                current_price=current,
                points=round((current - p.price_open) * (1 if direction == Direction.up else -1) / spec.point, 1),
                unrealized=float(p.profit), comment=p.comment, broker_id=self.id,
                signal_id=(p.comment.split("|")[1] if "|" in p.comment else None),
            ))
        return out

    def _filling_mode(self, broker_symbol: str) -> int | None:
        info = mt5.symbol_info(broker_symbol)
        if info is None:
            return None
        mode = int(info.filling_mode)
        if mode & 1:
            return mt5.ORDER_FILLING_FOK
        if mode & 2:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def order_send(self, request: OrderRequest, ticket_hint: str = "") -> OrderResult:
        self._require()
        started = time.perf_counter()
        broker_symbol = self._broker_symbol(request.symbol)
        spec = self.symbol_spec(request.symbol)
        tick = self.ticker(request.symbol)
        volume = spec.normalize_lot(request.volume)
        price = tick.ask if request.side == OrderSide.buy else tick.bid
        comment = f"No7|{request.signal_id or '-'}|{request.idempotency_key or '-'}"[:31]
        payload: dict[str, Any] = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": broker_symbol,
            "volume": volume,
            "type": mt5.ORDER_TYPE_BUY if request.side == OrderSide.buy else mt5.ORDER_TYPE_SELL,
            "price": float(price),
            "deviation": int(max(1, round(float(self.profile.get("max_slippage_points", 15))))),
            "magic": self._magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(broker_symbol) or mt5.ORDER_FILLING_IOC,
        }
        if request.sl:
            payload["sl"] = spec.round_price(request.sl)
        if request.tp:
            payload["tp"] = spec.round_price(request.tp)
        result = mt5.order_send(payload)
        if result is None:
            raise BrokerError(f"order_send returned None: {mt5.last_error()}", retcode=-1)
        filled = result.retcode == mt5.TRADE_RETCODE_DONE
        return OrderResult(
            order_id=request.idempotency_key or f"mt5-{result.order}",
            idempotency_key=request.idempotency_key or "",
            status=OrderState.filled if filled else OrderState.rejected,
            retcode=int(result.retcode),
            message=result.comment or getattr(mt5, "TRADE_RETCODE_DONE", "done"),
            ticket=str(result.order) if result.order else None,
            filled_volume=float(result.volume or 0),
            fill_price=float(result.price or 0) or None,
            slippage_points=round(abs(float(result.price or price) - price) / spec.point, 1),
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
            verified=False,
            created_at=time.time(),
        )

    def modify_position(self, ticket: str, sl: float | None = None, tp: float | None = None) -> bool:
        self._require()
        positions = mt5.positions_get(ticket=int(ticket)) or []
        if not positions:
            raise BrokerError(f"position {ticket} not found")
        pos = positions[0]
        payload = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": int(ticket),
            "symbol": pos.symbol,
            "sl": float(sl if sl is not None else pos.sl),
            "tp": float(tp if tp is not None else pos.tp),
        }
        result = mt5.order_send(payload)
        return bool(result and result.retcode == mt5.TRADE_RETCODE_DONE)

    def close_position(self, ticket: str, volume: float | None = None, comment: str = "") -> OrderResult:
        self._require()
        positions = mt5.positions_get(ticket=int(ticket)) or []
        if not positions:
            raise BrokerError(f"position {ticket} not found")
        pos = positions[0]
        spec = self.symbol_spec(pos.symbol)
        tick = mt5.symbol_info_tick(pos.symbol)
        direction = OrderSide.sell if pos.type == 0 else OrderSide.buy
        price = tick.bid if direction == OrderSide.sell else tick.ask
        payload = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": int(ticket),
            "symbol": pos.symbol,
            "volume": spec.normalize_lot(volume or pos.volume),
            "type": mt5.ORDER_TYPE_SELL if direction == OrderSide.sell else mt5.ORDER_TYPE_BUY,
            "price": float(price),
            "deviation": 20,
            "magic": self._magic,
            "comment": (comment or "no7 close")[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(pos.symbol) or mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(payload)
        ok = bool(result and result.retcode == mt5.TRADE_RETCODE_DONE)
        return OrderResult(
            order_id=f"close-{ticket}-{int(time.time())}", idempotency_key="", status=OrderState.closed if ok else OrderState.rejected,
            retcode=int(result.retcode) if result else -1, message=result.comment if result else "send failed",
            ticket=ticket, filled_volume=float(volume or pos.volume), fill_price=float(price),
            verified=ok, created_at=time.time(),
        )

    def calc_profit(self, symbol: str, direction: Direction, volume: float, entry: float, exit_price: float) -> float:
        """Broker-authoritative P&L via order_calc_profit (falls back to the contract formula)."""
        if not self._connected or not MT5_AVAILABLE:
            spec = self.symbol_spec(symbol)
            sign = 1 if direction == Direction.up else -1
            return (exit_price - entry) * sign * spec.contract_size * volume
        order_type = mt5.ORDER_TYPE_BUY if direction == Direction.up else mt5.ORDER_TYPE_SELL
        profit = mt5.order_calc_profit(order_type, self._broker_symbol(symbol), volume, entry, exit_price)
        return float(profit) if profit is not None else 0.0

    def closed_trades(self) -> list[TradeRecord]:
        """History deals are reconciled by the execution gateway, not here."""
        return []

    def shutdown(self) -> None:
        if MT5_AVAILABLE and self._connected:
            mt5.shutdown()
            self._connected = False
