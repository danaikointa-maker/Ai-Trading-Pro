"""Trade planner: stop, 500-1000 point ladder, lot and net reward/risk.

Two invariants:
1. Lot size is derived from *money at risk* and *stop distance*, never fixed.
2. If the ladder cannot clear the configured net reward/risk after spread and
   commission, the planner returns no plan — a good signal without a good
   trade is still a NO TRADE.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from packages.shared_schemas.models import (
    Direction,
    PartialTarget,
    SymbolSpec,
    TradePlan,
    Zone,
    ZoneKind,
    ZoneQuality,
)
from packages.strategy_rules.zones import strongest_opposing_zone


@dataclass
class PlanInputs:
    direction: Direction
    entry: float
    spec: SymbolSpec
    atr_points: float
    equity: float
    risk_pct: float
    spread_points: float
    supports: list[Zone]
    resistances: list[Zone]
    swings: list[dict] | None = None
    target_mode: str = "adaptive"
    min_points: float = 500
    max_points: float = 1000
    fixed_points: list[float] | None = None
    sl_atr_multiplier: float = 1.0
    sl_min_points: float = 150
    sl_max_points: float = 1200
    min_rr_net: float = 1.3
    atr_target_multiplier: float = 2.2
    zone_buffer_atr: float = 0.35
    respect_zones: bool = True
    closes_pct: list[float] | None = None


@dataclass
class PlanResult:
    plan: TradePlan | None
    blockers: list[str]
    notes: list[str]


class TradePlanner:
    def __init__(self, risk_cfg: dict[str, Any], score_cfg: dict[str, Any] | None = None) -> None:
        self.cfg = risk_cfg
        self.stops = risk_cfg.get("stops", {})
        self.targets = risk_cfg.get("targets", {})
        self.management = risk_cfg.get("management", {})
        self.limits = risk_cfg.get("limits", {})
        self.score_cfg = score_cfg or {}
        del self.score_cfg

    # ------------------------------------------------------------------ util
    def cost_points(self, spec: SymbolSpec, spread_points: float) -> float:
        commission_points = (spec.commission_per_lot_round_turn / spec.value_per_point_per_lot
                             if spec.value_per_point_per_lot else 0.0)
        return float(spread_points / 2.0 + commission_points)

    def _stop_from_structure(self, direction: Direction, entry: float, ctx: PlanInputs) -> tuple[float, str]:
        """Nearest structural invalidation beyond entry, with an ATR buffer."""
        buffer = ctx.atr_points * 0.35
        candidates: list[tuple[float, str]] = []
        if direction == Direction.up:
            for zone in ctx.supports:
                if zone.low < entry:
                    candidates.append((entry - (zone.low - buffer), f"support {zone.id} @ {zone.low:.2f}"))
            for swing in (ctx.swings or []):
                if swing.get("kind") == "low" and swing["price"] < entry:
                    candidates.append((entry - (swing["price"] - buffer), f"swing low @ {swing['price']:.2f}"))
        else:
            for zone in ctx.resistances:
                if zone.high > entry:
                    candidates.append(((zone.high + buffer) - entry, f"resistance {zone.id} @ {zone.high:.2f}"))
            for swing in (ctx.swings or []):
                if swing.get("kind") == "high" and swing["price"] > entry:
                    candidates.append(((swing["price"] + buffer) - entry, f"swing high @ {swing['price']:.2f}"))

        valid = [(pts, label) for pts, label in candidates if ctx.sl_min_points <= pts <= ctx.sl_max_points]
        if valid:
            pts, label = min(valid, key=lambda x: x[0])
            return pts, f"structural stop beyond {label}"
        return 0.0, ""

    def _tp_ladder(self, direction: Direction, entry: float, ctx: PlanInputs) -> tuple[list[float], list[str]]:
        notes: list[str] = []
        min_pts, max_pts = ctx.min_points, ctx.max_points
        base = ctx.atr_points * ctx.atr_target_multiplier
        if ctx.target_mode == "fixed" and ctx.fixed_points:
            ladder = sorted(float(p) for p in ctx.fixed_points)[:3]
        else:
            tp1 = float(np.clip(base, min_pts, max_pts))
            mid = tp1 + (max_pts - tp1) * 0.5
            ladder = [tp1, mid, float(max_pts)]
        ladder = [float(np.clip(v, min_pts, max_pts)) for v in ladder]
        while len(ladder) < 3:
            ladder.append(float(max_pts))
        ladder[0] = max(min_pts, ladder[0])
        ladder[1] = max(ladder[0] + 1, ladder[1])
        ladder[2] = max(ladder[1] + 1, ladder[2])

        if ctx.respect_zones:
            sign = 1 if direction == Direction.up else -1
            target_price = entry + sign * ctx.spec.points_to_price(ladder[0])
            blocker = strongest_opposing_zone(ctx.resistances if direction == Direction.up else ctx.supports,
                                              entry, target_price, "up" if direction == Direction.up else "down")
            if blocker is not None and blocker.quality != ZoneQuality.low:
                buffer = ctx.zone_buffer_atr * ctx.atr_points
                capped_price = (blocker.low - buffer) if direction == Direction.up else (blocker.high + buffer)
                capped_pts = abs(capped_price - entry) / ctx.spec.point
                if capped_pts < ladder[0]:
                    notes.append(
                        f"TP1 capped from {ladder[0]:.0f} to {max(min_pts, capped_pts):.0f} points by strong "
                        f"opposing zone {blocker.id} ({blocker.quality.value})")
                    ladder[0] = max(min_pts, capped_pts)
                    ladder[1] = max(ladder[0] + 1, min(ladder[1], ladder[0] + (max_pts - ladder[0]) * 0.6))
                    ladder[2] = max(ladder[1] + 1, max_pts)
                else:
                    notes.append(f"Respecting opposing zone {blocker.id} ({blocker.mid:.2f}) beyond TP1")
        return ladder, notes

    # ------------------------------------------------------------------ plan
    def build(self, ctx: PlanInputs) -> PlanResult:
        blockers: list[str] = []
        notes: list[str] = []
        spec = ctx.spec
        direction = ctx.direction
        sign = 1 if direction == Direction.up else -1
        costs = self.cost_points(spec, ctx.spread_points)

        # Volatility floor: a stop inside normal noise is not a stop, it is a donation.
        vol_floor = max(ctx.atr_points * 0.75, ctx.spread_points * 4.0, ctx.sl_min_points)
        sl_points, sl_note = 0.0, ""
        if self.stops.get("use_structure_stop", True):
            sl_points, sl_note = self._stop_from_structure(direction, ctx.entry, ctx)
            if sl_points > 0 and sl_points < vol_floor:
                sl_note += (f" (widened to the {vol_floor:.0f}-point volatility floor: 0.75 ATR / 4x spread)")
                sl_points = vol_floor
        if sl_points <= 0:
            sl_points = float(np.clip(ctx.atr_points * self.stops.get("sl_atr_multiplier", 1.0),
                                      vol_floor, ctx.sl_max_points))
            sl_note = f"ATR stop {self.stops.get('sl_atr_multiplier', 1.0)} x ATR"
        sl_points = float(np.clip(sl_points, vol_floor, ctx.sl_max_points))
        sl_price = ctx.entry - sign * spec.points_to_price(sl_points)

        ladder, tp_notes = self._tp_ladder(direction, ctx.entry, ctx)
        notes.extend(tp_notes)
        closes = ctx.closes_pct or [40, 30, 30]
        closes = closes[:3] if len(closes) >= 3 else (closes + [100 / max(1, len(closes))] * 3)[:3]
        blended = float(sum(t * c for t, c in zip(ladder, closes)) / max(1e-9, sum(closes)))

        # --- net reward/risk including spread + commission, both ways
        rr_gross = blended / sl_points if sl_points > 0 else 0.0
        rr_net = (blended - costs) / (sl_points + costs) if sl_points > 0 else 0.0

        # --- position size from money at risk
        loss_per_lot = sl_points * spec.value_per_point_per_lot
        risk_amount = ctx.equity * ctx.risk_pct / 100.0
        raw_lot = risk_amount / loss_per_lot if loss_per_lot > 0 else 0.0
        lot = spec.normalize_lot(raw_lot)
        if lot < spec.min_lot - 1e-9:
            blockers.append(
                f"risk budget ${risk_amount:.2f} cannot fund the {spec.min_lot} minimum lot at a "
                f"{sl_points:.0f}-point stop")
        elif not spec.lot_is_valid(lot):
            blockers.append(f"computed lot {lot} violates lot step {spec.lot_step}")
        actual_risk = lot * loss_per_lot

        if rr_net < ctx.min_rr_net:
            blockers.append(
                f"net reward/risk {rr_net:.2f} below the {ctx.min_rr_net:.2f} minimum after "
                f"{costs:.0f} points of cost")
        if sl_points <= costs * 3:
            blockers.append("stop distance is too small relative to trading costs")

        # --- partial close feasibility (lot step aware)
        partials: list[PartialTarget] = []
        feasible_all = True
        for i, (tp, pct) in enumerate(zip(ladder, closes), start=1):
            vol = spec.normalize_lot(lot * pct / 100.0) if lot > 0 else 0.0
            feasible = lot > 0 and spec.lot_is_valid(vol) and vol >= spec.min_lot
            if feasible and i < 3:
                remaining = lot - sum(p.volume for p in partials)
                feasible = remaining - vol >= spec.min_lot - 1e-9
            if not feasible:
                feasible_all = False
            partials.append(PartialTarget(
                level=i,
                price=spec.round_price(ctx.entry + sign * spec.points_to_price(tp)),
                points=round(tp, 0),
                close_pct=pct,
                volume=vol,
                feasible=feasible,
                note="" if feasible else f"{vol:.2f} lot violates step {spec.lot_step}/{spec.min_lot} minimum",
            ))
        if not feasible_all:
            notes.append(
                f"Lot {lot:.2f} is too small to split into 3 partials legally "
                f"(min {spec.min_lot}, step {spec.lot_step}) — the ladder will run as a single position "
                f"or be skipped.")

        if blockers:
            return PlanResult(plan=None, blockers=blockers, notes=notes + [sl_note] * bool(sl_note))

        tp_prices = [spec.round_price(ctx.entry + sign * spec.points_to_price(tp)) for tp in ladder]
        plan = TradePlan(
            direction=direction,
            entry=spec.round_price(ctx.entry),
            sl=sl_price,
            tp1=tp_prices[0], tp2=tp_prices[1], tp3=tp_prices[2],
            sl_points=round(sl_points, 0),
            tp_points=[round(v, 0) for v in ladder],
            lot=lot,
            risk_amount=round(actual_risk, 2),
            risk_pct=round(actual_risk / ctx.equity * 100, 3) if ctx.equity else 0.0,
            reward_risk=round(rr_gross, 2),
            reward_risk_net=round(rr_net, 2),
            estimated_cost=round(costs, 1),
            expected_value=0.0,
            partials=partials,
            target_mode=ctx.target_mode,
            notes=notes + ([sl_note] if sl_note else []),
        )
        return PlanResult(plan=plan, blockers=[], notes=plan.notes)

    # --------------------------------------------------------------- utility
    @staticmethod
    def profit_at(spec: SymbolSpec, points: float, lot: float) -> float:
        return points * spec.value_per_point_per_lot * lot

    @staticmethod
    def lot_for_risk(spec: SymbolSpec, equity: float, risk_pct: float, sl_points: float) -> float:
        loss_per_lot = sl_points * spec.value_per_point_per_lot
        if loss_per_lot <= 0:
            return 0.0
        return spec.normalize_lot(equity * risk_pct / 100.0 / loss_per_lot)


def points_calculator(spec: SymbolSpec, points: float, lot: float) -> dict[str, float]:
    """Mirror of the dashboard calculator, but using the *live* contract specs."""
    price_move = points * spec.point
    gross = price_move * spec.contract_size * lot
    commission = spec.commission_per_lot_round_turn * lot
    return {
        "points": points,
        "point_size": spec.point,
        "lot": lot,
        "contract_size": spec.contract_size,
        "price_move": round(price_move, spec.digits),
        "value_per_point_per_lot": round(spec.value_per_point_per_lot, 4),
        "gross_profit": round(gross, 2),
        "commission": round(commission, 2),
        "net_profit": round(gross - commission, 2),
        "currency": spec.profit_currency,
        "spread_cost": round(spec.spread_typical_points * spec.value_per_point_per_lot * lot, 2),
    }


def zone_blockers_for_stop(zones: list[Zone], direction: Direction, entry: float) -> list[Zone]:
    if direction == Direction.up:
        return [z for z in zones if z.kind == ZoneKind.support and z.high <= entry]
    return [z for z in zones if z.kind == ZoneKind.resistance and z.low >= entry]


PlanProbability = Callable[[float, float, int, float, int], tuple[float, int]]
