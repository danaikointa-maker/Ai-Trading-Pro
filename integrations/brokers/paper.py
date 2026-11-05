"""Paper broker built on the synthetic feed.

This is a *simulated MT5 account*: same contract specs, same lot steps, same
spread and commission maths as the live adapter, but local fills. It lets the
entire execution path (risk gate -> idempotent order -> verification ->
management -> journal) be tested before a single real order exists.
"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from integrations.brokers.base import BrokerAdapter, BrokerError
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
from services.market_data.simulator import SyntheticFeed, resample


def gross_pnl(direction: Direction, entry: float, exit_price: float, volume: float, spec: SymbolSpec) -> float:
    sign = 1.0 if direction == Direction.up else -1.0
    return sign * (exit_price - entry) * spec.contract_size * volume


def commission_for(volume: float, spec: SymbolSpec) -> float:
    return spec.commission_per_lot_round_turn * volume


@dataclass
class PaperPosition:
    ticket: str
    symbol: str
    spec: SymbolSpec
    direction: Direction
    volume: float
    initial_volume: float
    entry: float
    sl: float
    tp: float
    open_time: int
    sl_initial: float = 0.0
    comment: str = ""
    signal_id: str | None = None
    strategy: str = ""
    mode: str = "manual"
    realized_pnl: float = 0.0
    closed_volume: float = 0.0
    weighted_exit: float = 0.0
    max_favorable_points: float = 0.0
    breakeven_done: bool = False
    trailing_active: bool = False
    partials_done: int = 0
    last_price: float = 0.0
    exit_reason: str = ""
    journal: dict[str, Any] = field(default_factory=dict)

    def floating(self, price: float) -> float:
        return gross_pnl(self.direction, self.entry, price, self.volume, self.spec)

    def points(self, price: float) -> float:
        sign = 1.0 if self.direction == Direction.up else -1.0
        return (price - self.entry) * sign / self.spec.point


class PaperBroker(BrokerAdapter):
    adapter_type = "simulated_mt5"

    def __init__(self, profile: dict[str, Any], feed: SyntheticFeed, starting_balance: float = 10000.0,
                 slippage_points: float = 0.4, commission_enabled: bool = True, seed: int = 11,
                 clock: Any = None) -> None:
        self.profile = profile
        self.id = profile["id"]
        self.label = profile.get("label", profile["id"])
        self.server = profile.get("server", "Simulated")
        self.account_type = profile.get("account_type", "demo")
        self.live_allowed = bool(profile.get("live_allowed", False))
        self.regulated_note = (profile.get("regulated_note") or "").strip()
        self.feed = feed
        self.balance = float(starting_balance)
        self.starting_balance = float(starting_balance)
        self.slippage_points = slippage_points
        self.commission_enabled = commission_enabled
        self.rng = np.random.default_rng(seed)
        self._specs: dict[str, SymbolSpec] = {}
        for symbol, raw in (profile.get("symbols") or {}).items():
            self._specs[symbol] = SymbolSpec(symbol=symbol, **{k: v for k, v in raw.items() if k != "description"},
                                             description=raw.get("description", ""))
        self._seq = itertools.count(1001)
        self._positions: dict[str, PaperPosition] = {}
        self._closed: list[TradeRecord] = []
        self._pending_closed: list[TradeRecord] = []
        self.last_tick_at = 0.0
        self.clock = clock or time.time
        self._market_map = self._build_market_map(profile)

    # ------------------------------------------------------------------ maps
    @staticmethod
    def _build_market_map(profile: dict[str, Any]) -> dict[str, str]:
        mapping = profile.get("symbol_mapping") or {}
        out = {}
        for symbol in (profile.get("symbols") or {}):
            out[symbol] = mapping.get(symbol, symbol)
        return out

    def _market_symbol(self, symbol: str) -> str:
        return self._market_map.get(symbol, symbol)

    # -------------------------------------------------------------- metadata
    def health(self) -> Health:
        if not self._positions and self.last_tick_at and (time.time() - self.last_tick_at) > 30:
            return Health.stale
        return Health.connected

    def symbol_names(self) -> list[str]:
        return list(self._specs)

    def symbol_spec(self, symbol: str) -> SymbolSpec:
        if symbol not in self._specs:
            raise BrokerError(f"symbol {symbol} not available on {self.label}")
        return self._specs[symbol].model_copy()

    def account_info(self) -> AccountInfo:
        equity = self.balance + self._floating_total()
        return AccountInfo(
            broker_id=self.id,
            label=self.label,
            server=self.server,
            account_type=self.account_type,
            login=f"SIM-{self.id[:6].upper()}",
            currency="USD",
            balance=round(self.balance, 2),
            equity=round(equity, 2),
            margin=0.0,
            free_margin=round(equity, 2),
            leverage=int(self.profile.get("leverage", 100)),
            health=self.health(),
            adapter=self.adapter_type,
            live_allowed=self.live_allowed,
            last_sync=float(self.clock()),
            message="Simulated MT5 account — no real money, no real broker connection",
            regulated_note=self.regulated_note,
        )

    def ticker(self, symbol: str) -> Tick:
        return self.feed.ticker(self._market_symbol(symbol))

    def candles(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        market = self._market_symbol(symbol)
        multiplier = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}[timeframe]
        need = int(limit * multiplier * 1.05) + 20
        m1 = self.feed.warm_history(market, max(need, 600))
        df = resample(m1, timeframe)
        return df.tail(limit).reset_index(drop=True)

    # --------------------------------------------------------------- trading
    def positions(self) -> list[Position]:
        out: list[Position] = []
        for pos in self._positions.values():
            tick = self.feed.ticker(self._market_symbol(pos.symbol))
            price = tick.bid if pos.direction == Direction.up else tick.ask
            out.append(Position(
                ticket=pos.ticket,
                symbol=pos.symbol,
                direction=pos.direction,
                volume=round(pos.volume, 4),
                entry=round(pos.entry, pos.spec.digits),
                sl=round(pos.sl, pos.spec.digits),
                tp=round(pos.tp, pos.spec.digits),
                open_time=pos.open_time,
                current_price=round(price, pos.spec.digits),
                points=round(pos.points(price), 1),
                unrealized=round(pos.floating(price), 2),
                comment=pos.comment,
                signal_id=pos.signal_id,
                strategy=pos.strategy,
                partials_done=pos.partials_done,
                max_favorable_points=round(pos.max_favorable_points, 1),
                breakeven_done=pos.breakeven_done,
                trailing_active=pos.trailing_active,
                broker_id=self.id,
            ))
        return out

    def order_send(self, request: OrderRequest, ticket_hint: str = "") -> OrderResult:
        started = time.perf_counter()
        if request.symbol not in self._specs:
            raise BrokerError(f"symbol {request.symbol} not available on {self.label}", retcode=10013)
        spec = self._specs[request.symbol]
        volume = spec.normalize_lot(request.volume)
        if request.volume < spec.min_lot - 1e-9:
            raise BrokerError(
                f"volume {request.volume} is below the minimum lot {spec.min_lot}", retcode=10014)
        if request.volume > spec.max_lot + 1e-9:
            raise BrokerError(
                f"volume {request.volume} exceeds the maximum lot {spec.max_lot}", retcode=10014)
        if not spec.lot_is_valid(volume):
            raise BrokerError(f"volume {request.volume} violates lot step {spec.lot_step}", retcode=10014)
        tick = self.ticker(request.symbol)
        side = request.side
        slip = abs(self.rng.normal(0, self.slippage_points)) * spec.point
        price = (tick.ask if side == OrderSide.buy else tick.bid) + (slip if side == OrderSide.buy else -slip)
        price = spec.round_price(price)
        direction = Direction.up if side == OrderSide.buy else Direction.down

        sl = request.sl or 0.0
        tp = request.tp or 0.0
        if sl:
            sl = spec.round_price(sl)
            distance = abs(price - sl) / spec.point
            if distance < spec.stops_level_points:
                raise BrokerError(f"SL too close: {distance:.0f} pts < stops level {spec.stops_level_points:.0f}",
                                  retcode=10016)
            if (direction == Direction.up and sl >= price) or (direction == Direction.down and sl <= price):
                raise BrokerError("SL on the wrong side of the entry", retcode=10016)
        if tp:
            tp = spec.round_price(tp)
            if (direction == Direction.up and tp <= price) or (direction == Direction.down and tp >= price):
                raise BrokerError("TP on the wrong side of the entry", retcode=10016)

        ticket = ticket_hint or f"P{next(self._seq)}"
        pos = PaperPosition(
            ticket=ticket, symbol=request.symbol, spec=spec, direction=direction, volume=volume,
            initial_volume=volume, entry=price, sl=sl, tp=tp, sl_initial=sl,
            open_time=int(self.clock()),
            comment=request.comment, signal_id=request.signal_id, mode=request.mode.value,
        )
        self._positions[ticket] = pos
        self.last_tick_at = time.time()
        return OrderResult(
            order_id=request.idempotency_key or f"ord-{ticket}",
            idempotency_key=request.idempotency_key or "",
            status=OrderState.filled,
            retcode=10009,
            message="Paper fill (simulated MT5)",
            ticket=ticket,
            filled_volume=volume,
            fill_price=price,
            slippage_points=round(abs(price - (tick.ask if side == OrderSide.buy else tick.bid)) / spec.point, 1),
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
            verified=True,
            created_at=time.time(),
        )

    def modify_position(self, ticket: str, sl: float | None = None, tp: float | None = None) -> bool:
        pos = self._positions.get(ticket)
        if not pos:
            raise BrokerError(f"position {ticket} not found", retcode=10013)
        if sl is not None:
            pos.sl = pos.spec.round_price(sl)
        if tp is not None:
            pos.tp = pos.spec.round_price(tp)
        return True

    def close_position(self, ticket: str, volume: float | None = None, comment: str = "",
                       reason: str = "") -> TradeRecord:
        pos = self._positions.get(ticket)
        if not pos:
            raise BrokerError(f"position {ticket} not found", retcode=10013)
        tick = self.ticker(pos.symbol)
        price = tick.bid if pos.direction == Direction.up else tick.ask
        vol = pos.volume if volume is None else max(0.0, min(pos.volume, pos.spec.normalize_lot(volume)))
        if vol <= 0:
            raise BrokerError("close volume is zero")
        if vol < pos.volume - 1e-9:
            pos.partials_done += 1
        return self._realize(pos, price, vol, reason or comment or "manual close")

    # ---------------------------------------------------------------- ticks
    def on_tick(self, ticks: dict[str, Tick]) -> list[TradeRecord]:
        closed: list[TradeRecord] = []
        for ticket in list(self._positions):
            pos = self._positions.get(ticket)
            if not pos:
                continue
            market = self._market_symbol(pos.symbol)
            tick = ticks.get(market)
            if not tick:
                continue
            self.last_tick_at = time.time()
            exit_price = tick.bid if pos.direction == Direction.up else tick.ask
            pos.last_price = exit_price
            mfe = pos.points(exit_price)
            pos.max_favorable_points = max(pos.max_favorable_points, mfe)

            hit_sl = pos.sl > 0 and ((pos.direction == Direction.up and exit_price <= pos.sl) or
                                     (pos.direction == Direction.down and exit_price >= pos.sl))
            hit_tp = pos.tp > 0 and ((pos.direction == Direction.up and exit_price >= pos.tp) or
                                    (pos.direction == Direction.down and exit_price <= pos.tp))
            if hit_sl:
                rec = self._realize(pos, pos.sl, pos.volume, "stop loss")
                if rec:
                    closed.append(rec)
            elif hit_tp:
                rec = self._realize(pos, pos.tp, pos.volume, "take profit")
                if rec:
                    closed.append(rec)
        return closed

    # -------------------------------------------------------------- internals
    def _realize(self, pos: PaperPosition, price: float, volume: float, reason: str) -> TradeRecord | None:
        price = pos.spec.round_price(price)
        pnl = gross_pnl(pos.direction, pos.entry, price, volume, pos.spec)
        costs = commission_for(volume, pos.spec) if self.commission_enabled else 0.0
        net = pnl - costs
        self.balance += net
        pos.realized_pnl += net
        pos.closed_volume += volume
        pos.weighted_exit += price * volume
        pos.exit_reason = reason
        pos.volume = round(pos.volume - volume, 4)
        record: TradeRecord | None = None
        if pos.volume <= 1e-6:
            avg_exit = pos.weighted_exit / pos.closed_volume if pos.closed_volume else price
            total_costs = commission_for(pos.closed_volume, pos.spec) if self.commission_enabled else 0.0
            sign = 1.0 if pos.direction == Direction.up else -1.0
            points = (avg_exit - pos.entry) * sign / pos.spec.point
            # R is measured against the stop the trade was opened with; once
            # break-even/trailing moves the stop, this denominator must not shrink.
            initial_sl = pos.sl_initial or pos.sl
            risk_points = abs(pos.entry - initial_sl) / pos.spec.point if initial_sl else 0.0
            record = TradeRecord(
                ticket=pos.ticket,
                symbol=pos.symbol,
                direction=pos.direction,
                volume=round(pos.closed_volume, 4),
                entry=round(pos.entry, pos.spec.digits),
                exit=round(avg_exit, pos.spec.digits),
                sl=round(pos.sl, pos.spec.digits),
                tp=round(pos.tp, pos.spec.digits),
                opened_at=pos.open_time,
                closed_at=int(self.clock()),
                points=round(points, 1),
                gross_pnl=round(pos.realized_pnl + total_costs, 2),
                costs=round(total_costs, 2),
                pnl=round(pos.realized_pnl, 2),
                r_multiple=round(pos.realized_pnl / (risk_points * pos.spec.value_per_point_per_lot * pos.closed_volume), 2)
                if risk_points and pos.closed_volume else 0.0,
                exit_reason=reason,
                strategy=pos.strategy,
                signal_id=pos.signal_id,
                mode=pos.mode,  # type: ignore[arg-type]
                broker_id=self.id,
                journal={"max_favorable_points": round(pos.max_favorable_points, 1),
                         "partials_done": pos.partials_done, "breakeven_done": pos.breakeven_done},
            )
            self._closed.append(record)
            self._pending_closed.append(record)
            self._positions.pop(pos.ticket, None)
        return record

    def _floating_total(self) -> float:
        total = 0.0
        for pos in self._positions.values():
            tick = self.feed.ticker(self._market_symbol(pos.symbol))
            price = tick.bid if pos.direction == Direction.up else tick.ask
            total += pos.floating(price)
        return total

    def equity(self) -> tuple[float, float]:
        return round(self.balance, 2), round(self.balance + self._floating_total(), 2)

    def closed_trades(self) -> list[TradeRecord]:
        return list(self._closed)

    def drain_closed_trades(self) -> list[TradeRecord]:
        out = self._pending_closed
        self._pending_closed = []
        return out

    def set_balance(self, balance: float) -> None:
        self.balance = float(balance)

    def raw_position(self, ticket: str) -> PaperPosition | None:
        return self._positions.get(ticket)
