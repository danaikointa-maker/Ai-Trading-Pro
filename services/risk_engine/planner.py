"""Trade planner: stop, 500-1000 point ladder, lot and net reward/risk.

Two invariants:
1. Lot size is derived from *money at risk* and *stop distance*, never fixed.
2. If the ladder cannot clear the configured net reward/risk after spread and
   commission, the planner returns no plan — a good signal without a good
   trade is still a NO TRADE.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
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
    # Candidate-only: legacy keeps nearest-tick rounding until profile migration.
    directional_tick_rounding: bool = False
    sl_policy: str = "legacy"
    sl_structure_buffer_atr: float = 0.35
    swing_lookback_bars: int = 0
    m5_bar_count: int = 0
    single_target_r: float | None = None


@dataclass
class PlanResult:
    plan: TradePlan | None
    blockers: list[str]
    notes: list[str]
    # Same length and order as `blockers`. The text carries live numbers and is
    # written for a human; the code is what gets counted. Keeping them parallel
    # (rather than parsing the text later) is what stops the attribution report
    # from silently rotting when someone rewords a message.
    blocker_codes: list[str] = field(default_factory=list)


def build_plan_inputs(*, risk_cfg: dict[str, Any], effective: Any,
                      direction: Direction, entry: float, spec: SymbolSpec,
                      atr_points: float, equity: float, spread_points: float,
                      supports: list[Zone], resistances: list[Zone],
                      swings: list[dict] | None = None,
                      m5_bar_count: int = 0) -> PlanInputs:
    """Build the same planner inputs for automatic and manual entries.

    `effective` is the existing RiskSettings snapshot, so UI/runtime overrides
    retain their current precedence while planner policy comes from risk.yaml.
    Candidate-only fields remain opt-in and absent defaults preserve legacy.
    """
    limits = effective.limits
    stops = risk_cfg.get("stops", {})
    targets = risk_cfg.get("targets", {})
    adaptive = targets.get("adaptive", {})
    ladder = targets.get("ladder", {})
    return PlanInputs(
        direction=direction, entry=entry, spec=spec,
        atr_points=atr_points, equity=equity,
        risk_pct=float(limits.risk_per_trade_pct),
        spread_points=spread_points, supports=supports,
        resistances=resistances, swings=swings or [],
        target_mode=effective.targets_mode,
        min_points=float(effective.min_points),
        max_points=float(effective.max_points),
        fixed_points=list(effective.fixed_points),
        sl_atr_multiplier=float(effective.sl_atr_multiplier),
        sl_min_points=float(stops.get("sl_min_points", 150)),
        sl_max_points=float(stops.get("sl_max_points", 1200)),
        min_rr_net=float(limits.min_reward_risk),
        atr_target_multiplier=float(adaptive.get("atr_multiplier", 2.2)),
        zone_buffer_atr=float(adaptive.get("zone_buffer_atr", 0.35)),
        respect_zones=bool(adaptive.get("respect_zones", True)),
        closes_pct=list(ladder.get("closes_pct", [40, 30, 30])),
        sl_policy=str(risk_cfg.get("plan_options", {}).get("sl_policy", "legacy")),
        sl_structure_buffer_atr=float(
            risk_cfg.get("plan_options", {}).get("sl_structure_buffer_atr", 0.35)),
        swing_lookback_bars=int(
            risk_cfg.get("plan_options", {}).get("swing_lookback_bars", 0)),
        m5_bar_count=int(m5_bar_count),
        single_target_r=(float(risk_cfg["plan_options"]["single_target_r"])
                         if risk_cfg.get("plan_options", {}).get("single_target_r") is not None
                         else None),
        directional_tick_rounding=bool(
            risk_cfg.get("plan_options", {}).get("directional_tick_rounding", False)),
    )


def _split_lot(spec: SymbolSpec, lot: float, closes_pct: list[float]) -> list[float]:
    """Split a position into close volumes that are legal and sum to ``lot``.

    Each slice is floored to the broker lot step (never rounded up, which would
    close more than the position) and the final slice absorbs the remainder. If
    the position is too small to split legally, it is kept as one block.
    """
    if lot <= 0:
        return [0.0, 0.0, 0.0]
    step = spec.lot_step or 0.01
    volumes: list[float] = []
    for pct in closes_pct[:2]:
        raw = lot * float(pct) / 100.0
        floored = round(math.floor(raw / step + 1e-9) * step, 4)
        volumes.append(floored)
    remainder = round(lot - sum(volumes), 4)
    if remainder < spec.min_lot - 1e-9 or any(v < spec.min_lot - 1e-9 for v in volumes):
        # Cannot split: trade the whole position to the final target.
        return [round(lot, 4), 0.0, 0.0]
    volumes.append(remainder)
    return volumes


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

    @staticmethod
    def _round_level(spec: SymbolSpec, price: float, direction: Direction,
                     *, is_stop: bool, directional: bool) -> float:
        """Normalize protective levels outward when the candidate flag is on."""
        if not directional:
            return spec.round_price(price)
        tick = spec.tick_size or spec.point
        units = price / tick
        round_up = (direction == Direction.down) if is_stop else (direction == Direction.up)
        ticks = math.ceil(units - 1e-10) if round_up else math.floor(units + 1e-10)
        return round(ticks * tick, spec.digits)

    def _stop_from_structure(self, direction: Direction, entry: float,
                             ctx: PlanInputs) -> tuple[float, str]:
        """Nearest structural invalidation beyond entry, with an ATR buffer."""
        buffer = ctx.spec.points_to_price(ctx.atr_points * ctx.sl_structure_buffer_atr)
        candidates: list[tuple[float, str]] = []
        if direction == Direction.up:
            for zone in ctx.supports:
                if zone.low < entry:
                    distance = entry - (zone.low - buffer)
                    candidates.append((distance / ctx.spec.point,
                                       f"support {zone.id} @ {zone.low:.2f}"))
            for swing in (ctx.swings or []):
                if swing.get("kind") == "low" and swing["price"] < entry:
                    distance = entry - (swing["price"] - buffer)
                    candidates.append((distance / ctx.spec.point,
                                       f"swing low @ {swing['price']:.2f}"))
        else:
            for zone in ctx.resistances:
                if zone.high > entry:
                    distance = (zone.high + buffer) - entry
                    candidates.append((distance / ctx.spec.point,
                                       f"resistance {zone.id} @ {zone.high:.2f}"))
            for swing in (ctx.swings or []):
                if swing.get("kind") == "high" and swing["price"] > entry:
                    distance = (swing["price"] + buffer) - entry
                    candidates.append((distance / ctx.spec.point,
                                       f"swing high @ {swing['price']:.2f}"))

        valid = [(pts, label) for pts, label in candidates if ctx.sl_min_points <= pts <= ctx.sl_max_points]
        if valid:
            pts, label = min(valid, key=lambda x: x[0])
            return pts, f"structural stop beyond {label}"
        return 0.0, ""

    def _candidate_structure_distance(self, direction: Direction, entry: float,
                                      ctx: PlanInputs) -> tuple[float, str]:
        """Use the most adverse confirmed swing in the configured closed-bar window."""
        cutoff = (ctx.m5_bar_count - ctx.swing_lookback_bars
                  if ctx.m5_bar_count > 0 and ctx.swing_lookback_bars > 0 else None)
        if ctx.swing_lookback_bars > 0 and ctx.m5_bar_count <= 0:
            return 0.0, "closed-M5 bar count is unavailable"
        buffer = ctx.spec.points_to_price(ctx.atr_points * ctx.sl_structure_buffer_atr)
        kind = "low" if direction == Direction.up else "high"
        swings = [s for s in (ctx.swings or [])
                  if s.get("kind") == kind and float(s.get("price", 0)) > 0
                  and (cutoff is None or int(s.get("idx", -1)) >= cutoff)]
        if not swings:
            return 0.0, "no confirmed swing in configured closed-M5 lookback"
        swing = min(swings, key=lambda row: float(row["price"])) if kind == "low" else max(
            swings, key=lambda row: float(row["price"]))
        price = float(swing["price"])
        distance = (entry - (price - buffer) if direction == Direction.up
                    else (price + buffer) - entry)
        return max(0.0, distance / ctx.spec.point), f"M5 swing {kind} @ {price:.2f} + ATR buffer"

    def _tp_ladder(self, direction: Direction, entry: float,
                   ctx: PlanInputs) -> tuple[list[float], list[str], list[str]]:
        notes: list[str] = []
        blockers: list[str] = []
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
        ladder[0] = max(min_pts, ladder[0], ctx.spec.stops_level_points + 1)
        ladder[1] = max(ladder[0] + 1, ladder[1])
        ladder[2] = max(ladder[1] + 1, ladder[2])

        if ctx.respect_zones:
            sign = 1 if direction == Direction.up else -1
            target_price = entry + sign * ctx.spec.points_to_price(ladder[0])
            blocker = strongest_opposing_zone(ctx.resistances if direction == Direction.up else ctx.supports,
                                              entry, target_price, "up" if direction == Direction.up else "down")
            if blocker is not None and blocker.quality != ZoneQuality.low:
                buffer = ctx.spec.points_to_price(ctx.zone_buffer_atr * ctx.atr_points)
                capped_price = (blocker.low - buffer) if direction == Direction.up else (blocker.high + buffer)
                capped_pts = abs(capped_price - entry) / ctx.spec.point
                if capped_pts < ladder[0]:
                    if capped_pts < min_pts:
                        blockers.append(
                            f"opposing zone {blocker.id} leaves only {capped_pts:.0f} points before "
                            f"the configured minimum target {min_pts:.0f}; reject instead of placing "
                            "the target through the zone")
                        return ladder, notes, blockers
                    notes.append(
                        f"TP1 capped from {ladder[0]:.0f} to {capped_pts:.0f} points by strong "
                        f"opposing zone {blocker.id} ({blocker.quality.value})")
                    ladder[0] = capped_pts
                    ladder[1] = max(ladder[0] + 1, min(ladder[1], ladder[0] + (max_pts - ladder[0]) * 0.6))
                    ladder[2] = max(ladder[1] + 1, max_pts)
                else:
                    notes.append(f"Respecting opposing zone {blocker.id} ({blocker.mid:.2f}) beyond TP1")
        return ladder, notes, blockers

    # ------------------------------------------------------------------ plan
    def build(self, ctx: PlanInputs) -> PlanResult:
        blockers: list[str] = []
        codes: list[str] = []
        notes: list[str] = []

        def block(code: str, text: str) -> None:
            codes.append(code)
            blockers.append(text)

        spec = ctx.spec
        direction = ctx.direction
        if spec.sizing_blocked:
            # No FX rate for the profit currency: sizing would be wrong by the
            # whole exchange rate, so refuse rather than guess.
            block("no_fx_rate",
                  f"invalid/incomplete symbol spec or no FX rate to value {spec.profit_currency} "
                  f"P&L in {spec.account_currency}; size this symbol on the broker terminal instead")
            return PlanResult(plan=None, blockers=blockers, blocker_codes=codes, notes=notes)
        sign = 1 if direction == Direction.up else -1
        costs = self.cost_points(spec, ctx.spread_points)

        # Volatility floor: a stop inside normal noise is not a stop, it is a donation.
        vol_floor = max(ctx.atr_points * 0.75, ctx.spread_points * 4.0, ctx.sl_min_points)
        sl_points, sl_note = 0.0, ""
        if ctx.sl_policy == "atr_structure":
            if (not math.isfinite(ctx.atr_points) or ctx.atr_points <= 0
                    or not math.isfinite(ctx.sl_max_points) or ctx.sl_max_points <= 0
                    or ctx.swing_lookback_bars < 0 or ctx.m5_bar_count < 0
                    or not math.isfinite(ctx.sl_atr_multiplier) or ctx.sl_atr_multiplier <= 0
                    or not math.isfinite(ctx.sl_structure_buffer_atr)
                    or ctx.sl_structure_buffer_atr < 0):
                block("invalid_stop_policy", "ATR/structure stop parameters are invalid")
                return PlanResult(plan=None, blockers=blockers,
                                  blocker_codes=codes, notes=notes)
            structure_points, structure_note = self._candidate_structure_distance(
                direction, ctx.entry, ctx)
            if ctx.swing_lookback_bars > 0 and structure_points <= 0:
                block("structure_missing", structure_note)
                return PlanResult(plan=None, blockers=blockers,
                                  blocker_codes=codes, notes=notes)
            atr_reference = ctx.atr_points * ctx.sl_atr_multiplier
            sl_points = max(atr_reference, structure_points, vol_floor)
            sl_note = (f"ATR+structure stop: max({ctx.sl_atr_multiplier:.2f} ATR, "
                       f"{structure_points:.0f}-point structure, volatility floor); "
                       f"{structure_note}")
            if sl_points > ctx.sl_max_points:
                block("stop_distance_max",
                      f"required stop {sl_points:.0f} points exceeds configured maximum "
                      f"{ctx.sl_max_points:.0f}; reject instead of narrowing protection")
                return PlanResult(plan=None, blockers=blockers,
                                  blocker_codes=codes, notes=notes + [sl_note])
        elif ctx.sl_policy == "legacy":
            if self.stops.get("use_structure_stop", True):
                sl_points, sl_note = self._stop_from_structure(direction, ctx.entry, ctx)
                if sl_points > 0 and sl_points < vol_floor:
                    sl_note += (f" (widened to the {vol_floor:.0f}-point volatility floor: "
                                "0.75 ATR / 4x spread)")
                    sl_points = vol_floor
            if sl_points <= 0:
                multiplier = self.stops.get("sl_atr_multiplier", 1.0)
                sl_points = float(np.clip(ctx.atr_points * multiplier,
                                          vol_floor, ctx.sl_max_points))
                sl_note = f"ATR stop {multiplier} x ATR"
            sl_points = float(np.clip(sl_points, vol_floor, ctx.sl_max_points))
        else:
            block("invalid_stop_policy", f"unsupported stop policy {ctx.sl_policy!r}")
            return PlanResult(plan=None, blockers=blockers,
                              blocker_codes=codes, notes=notes)
        min_stop = float(spec.stops_level_points)
        if min_stop > 0 and sl_points < min_stop + 1:
            if ctx.sl_policy == "atr_structure" and min_stop + 1 > ctx.sl_max_points:
                block("broker_stop_distance", "broker stops level exceeds candidate maximum stop distance")
                return PlanResult(plan=None, blockers=blockers,
                                  blocker_codes=codes, notes=notes)
            sl_note += (f" (widened to the broker stops level of {min_stop:.0f} points)"
                        if sl_note else f"Broker stops level {min_stop:.0f} points")
            sl_points = min_stop + 1
        sl_price = self._round_level(
            spec, ctx.entry - sign * spec.points_to_price(sl_points), direction,
            is_stop=True, directional=ctx.directional_tick_rounding)

        single_target = ctx.single_target_r is not None
        if single_target:
            target_r = float(ctx.single_target_r)
            if not math.isfinite(target_r) or target_r <= 0:
                block("invalid_target_policy", "single-target R multiple must be positive")
                return PlanResult(plan=None, blockers=blockers,
                                  blocker_codes=codes, notes=notes)
            target_points = sl_points * target_r
            if target_points > ctx.max_points:
                block("target_distance_max",
                      f"{target_r:.2f}R target is {target_points:.0f} points, above configured "
                      f"maximum {ctx.max_points:.0f}; reject instead of truncating the target")
                return PlanResult(plan=None, blockers=blockers,
                                  blocker_codes=codes, notes=notes)
            if target_points <= spec.stops_level_points:
                block("broker_target_distance", "single target is inside the broker stops level")
                return PlanResult(plan=None, blockers=blockers,
                                  blocker_codes=codes, notes=notes)
            target_price = ctx.entry + sign * spec.points_to_price(target_points)
            opposing = strongest_opposing_zone(
                ctx.resistances if direction == Direction.up else ctx.supports,
                ctx.entry, target_price, "up" if direction == Direction.up else "down")
            if opposing is not None and opposing.quality != ZoneQuality.low:
                block("opposing_zone",
                      f"strong opposing zone {opposing.id} is before the {target_r:.2f}R target; "
                      "reject the plan")
                return PlanResult(plan=None, blockers=blockers,
                                  blocker_codes=codes, notes=notes)
            ladder = [target_points, target_points, target_points]
            tp_notes: list[str] = [f"single target at {target_r:.2f}R; partials disabled"]
            tp_blockers: list[str] = []
        else:
            ladder, tp_notes, tp_blockers = self._tp_ladder(direction, ctx.entry, ctx)
        notes.extend(tp_notes)
        for text in tp_blockers:
            block("opposing_zone", text)
        closes = [100, 0, 0] if single_target else (ctx.closes_pct or [40, 30, 30])
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
            block("risk_budget_min_lot",
                  f"risk budget ${risk_amount:.2f} cannot fund the {spec.min_lot} minimum lot at a "
                  f"{sl_points:.0f}-point stop")
        elif not spec.lot_is_valid(lot):
            block("lot_step", f"computed lot {lot} violates lot step {spec.lot_step}")
        actual_risk = lot * loss_per_lot

        # The blended figure assumes the whole ladder fills; TP1 has to work on
        # its own, otherwise the "expected" reward is really a hoped-for TP3.
        tp1_reward = ladder[0] - costs
        rr_net_tp1 = tp1_reward / (sl_points + costs) if sl_points > 0 else 0.0
        if rr_net < ctx.min_rr_net:
            block("reward_risk",
                  f"net reward/risk {rr_net:.2f} below the {ctx.min_rr_net:.2f} minimum after "
                  f"{costs:.0f} points of cost")
        if rr_net_tp1 < 1.0:
            block("tp1_reward",
                  f"first target only pays {rr_net_tp1:.2f}R net ({ladder[0]:.0f} pts reward vs "
                  f"{sl_points:.0f} pts stop + {costs:.0f} pts cost)")
        notes.append(
            f"Net R:R TP1 {rr_net_tp1:.2f} / blended {rr_net:.2f} (cost {costs:.0f} pts)")
        if sl_points <= costs * 3:
            block("stop_vs_costs", "stop distance is too small relative to trading costs")

        # --- partial close feasibility (lot step aware)
        partials: list[PartialTarget] = []
        if single_target:
            partials.append(PartialTarget(
                level=1, price=self._round_level(
                    spec, ctx.entry + sign * spec.points_to_price(ladder[0]), direction,
                    is_stop=False, directional=ctx.directional_tick_rounding),
                points=round(ladder[0], 0), close_pct=100.0, volume=lot,
                feasible=bool(lot > 0 and spec.lot_is_valid(lot)),
                note="single broker TP; manager partial closes disabled",
            ))
        else:
            volumes = _split_lot(spec, lot, closes)
            feasible_all = lot > 0
            running = 0.0
            for i, (tp, pct, vol) in enumerate(zip(ladder, closes, volumes), start=1):
                running = round(running + vol, 4)
                feasible = bool(lot > 0 and spec.lot_is_valid(vol) and vol >= spec.min_lot - 1e-9)
                if not feasible:
                    feasible_all = False
                partials.append(PartialTarget(
                    level=i,
                    price=self._round_level(
                        spec, ctx.entry + sign * spec.points_to_price(tp), direction,
                        is_stop=False, directional=ctx.directional_tick_rounding),
                    points=round(tp, 0),
                    close_pct=pct,
                    volume=vol,
                    feasible=feasible,
                    note="" if feasible else (
                        f"{vol:.2f} lot cannot be closed legally with step {spec.lot_step} / "
                        f"min {spec.min_lot}"),
                ))
            # The ladder must add up to exactly the position that was opened.
            if lot > 0 and abs(running - lot) > 1e-6:
                notes.append(f"Partial ladder sums to {running:.2f} lot instead of {lot:.2f}; "
                             f"remaining volume runs to the final target.")
            if not feasible_all:
                notes.append(
                    f"Lot {lot:.2f} is too small to split into 3 partials legally "
                    f"(min {spec.min_lot}, step {spec.lot_step}) — the ladder will run as a single position "
                    f"or be skipped.")

        if blockers:
            return PlanResult(plan=None, blockers=blockers, blocker_codes=codes,
                              notes=notes + [sl_note] * bool(sl_note))

        tp_prices = [
            self._round_level(
                spec, ctx.entry + sign * spec.points_to_price(tp), direction,
                is_stop=False, directional=ctx.directional_tick_rounding)
            for tp in ladder
        ]
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
            target_mode="single_2r" if single_target else ctx.target_mode,
            notes=notes + ([sl_note] if sl_note else []),
        )
        return PlanResult(plan=plan, blockers=[], blocker_codes=[], notes=plan.notes)

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
