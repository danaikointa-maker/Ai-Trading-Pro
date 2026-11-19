"""Position management: break-even, trailing, partials, time and smart exits.

Rules live in ``config/risk.yaml`` so the behaviour is auditable and can be
backtested rather than buried in the EA.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from packages.shared_schemas.models import (
    Direction,
    ForecastBundle,
    Position,
    Signal,
    SymbolSpec,
    ZoneQuality,
)
from packages.shared_schemas.settings import Settings


@dataclass
class PositionAction:
    kind: str                 # modify | partial_close | close
    ticket: str
    reason: str
    volume: float | None = None
    new_sl: float | None = None
    note: str = ""
    metadata: dict[str, Any] | None = None


class PositionManager:
    def __init__(self, settings: Settings) -> None:
        cfg = settings.risk_cfg().get("management", {})
        self.be = cfg.get("break_even", {})
        self.trailing = cfg.get("trailing", {})
        self.time_exit = cfg.get("time_exit", {})
        self.smart = cfg.get("smart_exit", {})
        # Partials are on by default, but the switch has to actually work.
        self.partials = cfg.get("partials", {"enabled": True})

    def protection_candidate(self, pos: Position, spec: SymbolSpec, plan: Signal | None,
                             profile: dict[str, Any], *, close_price: float,
                             atr_points: float | None = None,
                             atr_is_closed: bool = False,
                             atr_age_seconds: float | None = None,
                             requested_action: str | None = None) -> tuple[PositionAction | None, list[str]]:
        """Build one safe V1.1 SL candidate; preview only, never calls a broker.

        Original R is measured from the actual fill and the immutable initial SL
        in the approved signal plan. Positions without that evidence are refused.
        The legacy ``evaluate`` behavior remains unchanged unless a caller opts in.
        """
        blockers: list[str] = []
        if profile.get("version") != "1.1":
            return None, ["unsupported protection profile version"]
        if not pos.ticket or pos.volume <= 0 or pos.entry <= 0 or not spec.point or not spec.tick_size:
            return None, ["position or broker symbol identity is incomplete"]
        plan_data = getattr(plan, "plan", None) if plan else None
        if plan_data is None or plan.broker_id != pos.broker_id or plan.symbol != pos.symbol:
            return None, ["immutable matching initial plan is unavailable"]
        initial_sl = float(plan_data.sl)
        if not initial_sl or not math.isfinite(initial_sl):
            return None, ["initial stop is unavailable"]
        is_buy = pos.direction == Direction.up
        initial_r = pos.entry - initial_sl if is_buy else initial_sl - pos.entry
        if not math.isfinite(initial_r) or initial_r <= spec.tick_size:
            return None, ["initial R from fill to approved stop is invalid"]
        if not math.isfinite(close_price) or close_price <= 0:
            return None, ["fresh closing-side price is unavailable"]

        policy = profile.get("protection", {})
        be_cfg = profile.get("break_even", {})
        trail_cfg = profile.get("trailing", {})
        candidates: list[PositionAction] = []
        move = pos.points * spec.point
        if (requested_action in (None, "break_even") and be_cfg.get("enabled", True)
                and move >= initial_r * float(be_cfg.get("activation_r", 1.0))):
            if spec.sizing_blocked:
                blockers.append("broker cost and symbol metadata are incomplete")
            else:
                # Convert round-turn commission into price distance using the
                # account-currency value of one point; add a configured slippage
                # reserve. No FX/THB display conversion enters execution math.
                cost_per_lot = (spec.commission_per_lot_round_turn
                                + float(be_cfg.get("estimated_swap_cost_per_lot", 0.0)))
                cost_points = max(0.0, cost_per_lot / spec.value_per_point_per_lot)
                cost_points += max(0.0, float(be_cfg.get("slippage_allowance_points", 0.0)))
                offset = cost_points + max(0.0, float(be_cfg.get("extra_lock_points", 0.0)))
                raw = pos.entry + (1 if is_buy else -1) * offset * spec.point
                candidate = spec.round_price(raw)
                action, reason = self._validate_protection_sl(pos, spec, candidate, close_price, policy)
                if action:
                    candidates.append(PositionAction(
                        kind="modify", ticket=pos.ticket, new_sl=candidate, reason="break_even_v1_1",
                        note="V1.1 break-even candidate; cost allowance is an estimate",
                        metadata={"initial_r_price": initial_r, "cost_points": round(cost_points, 6),
                                  "profile_version": "1.1"}))
                elif reason:
                    blockers.append(reason)

        if (requested_action in (None, "trailing") and trail_cfg.get("enabled", False)
                and move >= initial_r * float(trail_cfg.get("activation_r", 1.5))):
            if not atr_is_closed or atr_age_seconds is None or atr_age_seconds < 0 or \
                    atr_age_seconds > float(trail_cfg.get("max_atr_age_seconds", 90)):
                blockers.append("fresh closed-bar ATR is unavailable")
            elif atr_points is None or not math.isfinite(atr_points) or atr_points <= 0:
                blockers.append("ATR is invalid")
            elif trail_cfg.get("require_break_even_confirmed", True) and not self._stop_at_or_beyond_be(
                    pos, spec, be_cfg):
                blockers.append("trailing waits for broker-confirmed break-even protection")
            else:
                distance_points = max(
                    float(atr_points) * float(trail_cfg.get("atr_multiplier", 1.0)),
                    float(spec.stops_level_points), float(spec.freeze_level_points),
                )
                raw = close_price - (1 if is_buy else -1) * distance_points * spec.point
                candidate = spec.round_price(raw)
                step_price = max(0.0, float(trail_cfg.get("step_atr", 0.2))
                                 * float(atr_points) * spec.point)
                current_sl = pos.sl
                improvement = (candidate - current_sl) if is_buy else (current_sl - candidate)
                if improvement + 1e-12 < step_price:
                    blockers.append("trailing improvement is below the configured step")
                else:
                    action, reason = self._validate_protection_sl(pos, spec, candidate, close_price, policy)
                    if action:
                        candidates.append(PositionAction(
                            kind="modify", ticket=pos.ticket, new_sl=candidate, reason="trailing_v1_1",
                            note="V1.1 closed-bar ATR trailing candidate",
                            metadata={"initial_r_price": initial_r, "atr_points": float(atr_points),
                                      "profile_version": "1.1"}))
                    elif reason:
                        blockers.append(reason)

        if not candidates:
            return None, blockers or ["no protection action is eligible"]
        # One command per position and cycle. The tightest valid stop in the
        # profitable direction is the safest candidate, independent of order.
        selected = max(candidates, key=lambda item: item.new_sl or 0) if is_buy else \
            min(candidates, key=lambda item: item.new_sl or float("inf"))
        return selected, blockers

    @staticmethod
    def _stop_at_or_beyond_be(pos: Position, spec: SymbolSpec, be_cfg: dict[str, Any]) -> bool:
        if not pos.sl:
            return False
        cost_points = max(0.0, float(be_cfg.get("slippage_allowance_points", 0.0)))
        threshold = pos.entry + (1 if pos.direction == Direction.up else -1) * cost_points * spec.point
        return pos.sl >= threshold if pos.direction == Direction.up else pos.sl <= threshold

    @staticmethod
    def _validate_protection_sl(pos: Position, spec: SymbolSpec, candidate: float,
                                close_price: float, policy: dict[str, Any]) -> tuple[bool, str | None]:
        if not math.isfinite(candidate) or candidate <= 0:
            return False, "normalized stop is invalid"
        is_buy = pos.direction == Direction.up
        if is_buy and candidate >= close_price or not is_buy and candidate <= close_price:
            return False, "stop would cross the current closing-side price"
        minimum = max(float(spec.stops_level_points), float(spec.freeze_level_points)) * spec.point
        if abs(close_price - candidate) + 1e-12 < minimum:
            return False, "stop violates broker stops/freeze distance"
        if policy.get("never_widen_stop_loss", True):
            if is_buy and pos.sl and candidate < pos.sl - 1e-12:
                return False, "candidate would widen the BUY stop"
            if not is_buy and pos.sl and candidate > pos.sl + 1e-12:
                return False, "candidate would widen the SELL stop"
        if pos.sl and abs(candidate - pos.sl) < spec.tick_size - 1e-12:
            return False, "candidate does not improve the broker stop by one tick"
        return True, None

    def automatic_protection_actions(self, positions: list[Position], specs: dict[str, SymbolSpec],
                                     plans: dict[str, Signal], profile: dict[str, Any], *,
                                     mode: str, account_type: str,
                                     explicit_authorization: bool = False,
                                     atr_points_by_symbol: dict[str, float] | None = None,
                                     closed_atr_symbols: set[str] | None = None,
                                     close_prices_by_symbol: dict[str, float] | None = None) -> list[PositionAction]:
        """Auto-dispatch is opt-in, Demo-only, and remains OFF in the V1.1 profile."""
        automation = profile.get("automation", {})
        if (mode not in {"FULL_AUTO", "HYBRID"} or account_type != "demo"
                or not explicit_authorization or automation.get("enabled") is not True):
            return []
        actions: list[PositionAction] = []
        closed_atr_symbols = closed_atr_symbols or set()
        atr_points_by_symbol = atr_points_by_symbol or {}
        close_prices_by_symbol = close_prices_by_symbol or {}
        for pos in positions:
            spec = specs.get(pos.symbol)
            plan = plans.get(pos.signal_id or "")
            if spec is None or pos.symbol not in close_prices_by_symbol:
                continue
            candidate, _ = self.protection_candidate(
                pos, spec, plan, profile, close_price=close_prices_by_symbol[pos.symbol],
                atr_points=atr_points_by_symbol.get(pos.symbol),
                atr_is_closed=pos.symbol in closed_atr_symbols,
                atr_age_seconds=0 if pos.symbol in closed_atr_symbols else None)
            if candidate:
                actions.append(candidate)
        return actions

    def evaluate(self, positions: list[Position], specs: dict[str, SymbolSpec],
                 plans: dict[str, Signal], forecast: ForecastBundle | None,
                 snapshot: Any = None, now: float | None = None,
                 atr_points: float = 0.0) -> list[PositionAction]:
        from time import time as _time

        now = now or _time()
        actions: list[PositionAction] = []
        for pos in positions:
            spec = specs.get(pos.symbol)
            if spec is None:
                continue
            sign = 1 if pos.direction == Direction.up else -1
            plan = plans.get(pos.signal_id or "")
            plan_data = plan.plan if plan else None

            # --- 1. hard exits first
            exit_action = self._smart_exit(pos, plan, forecast, snapshot, spec)
            if exit_action:
                actions.append(exit_action)
                continue

            # --- 2. partial closes at the ladder levels
            if plan_data and self._partial_enabled():
                partial = self._partial_action(pos, plan_data, spec, sign)
                if partial:
                    actions.append(partial)

            # --- 3. break-even
            if self.be.get("enabled", True) and not pos.breakeven_done:
                trigger = float(self.be.get("trigger_points", 250))
                if pos.points >= trigger:
                    lock = sign * spec.points_to_price(float(self.be.get("lock_points", 30)))
                    candidate = spec.round_price(pos.entry + lock)
                    if (sign > 0 and candidate > pos.sl) or (sign < 0 and (pos.sl == 0 or candidate < pos.sl)):
                        actions.append(PositionAction(
                            kind="modify", ticket=pos.ticket, new_sl=candidate,
                            reason="break_even",
                            note=f"+{pos.points:.0f} pts reached; stop to break-even +{self.be.get('lock_points')} pts",
                        ))

            # --- 4. trailing
            if self.trailing.get("enabled", True) and pos.points >= float(self.trailing.get("start_after_points", 500)):
                distance = (float(self.trailing.get("atr_multiplier", 1.0)) * atr_points
                            if self.trailing.get("mode", "atr") == "atr" else float(self.trailing.get("distance_points", 300)))
                distance = max(distance, spec.spread_typical_points * 3)
                candidate = spec.round_price(pos.current_price - sign * spec.points_to_price(distance))
                step = spec.points_to_price(float(self.trailing.get("step_points", 50)))
                improvement = (candidate - pos.sl) * sign
                if improvement >= step and ((sign > 0 and candidate > pos.sl) or
                                            (sign < 0 and (pos.sl == 0 or candidate < pos.sl))):
                    actions.append(PositionAction(
                        kind="modify", ticket=pos.ticket, new_sl=candidate, reason="trailing_stop",
                        note=f"trail {distance:.0f} pts behind price, locking {pos.points - distance:+.0f} pts",
                    ))

            # --- 5. time exit
            if self.time_exit.get("enabled", True):
                minutes = (now - pos.open_time) / 60.0
                limit = float(self.time_exit.get("max_minutes_in_trade", 240))
                weak = pos.points < float(self.time_exit.get("close_if_profit_below_points", 50))
                if minutes >= limit and weak:
                    actions.append(PositionAction(
                        kind="close", ticket=pos.ticket, reason="time_exit",
                        note=f"{minutes:.0f} min open with only {pos.points:+.0f} pts — closing",
                    ))
        return actions

    # ------------------------------------------------------------- internals
    def _partial_enabled(self) -> bool:
        return bool(self.partials.get("enabled", True))

    def _partial_action(self, pos: Position, plan_data: Any, spec: SymbolSpec, sign: int) -> PositionAction | None:
        levels = getattr(plan_data, "partials", []) or []
        for target in levels:
            if target.level <= pos.partials_done:
                continue
            if not target.feasible:
                continue
            if pos.points >= target.points - 1e-9:
                volume = min(target.volume, pos.volume - spec.min_lot)
                if volume < spec.min_lot:
                    continue
                return PositionAction(
                    kind="partial_close", ticket=pos.ticket, volume=spec.normalize_lot(volume),
                    reason=f"partial_tp{target.level}",
                    note=f"TP{target.level} at {target.points:.0f} pts ({target.close_pct:.0f}% of size)",
                )
        return None

    def _smart_exit(self, pos: Position, plan: Signal | None, forecast: ForecastBundle | None,
                    snapshot: Any, spec: SymbolSpec) -> PositionAction | None:
        if not self.smart.get("enabled", True) or plan is None:
            return None
        direction = pos.direction
        if self.smart.get("close_on_opposite_choch", True) and snapshot is not None:
            events = getattr(snapshot, "structure", []) or []
            if events:
                last = events[-1]
                opposed = ((direction == Direction.up and last.kind == "CHoCH" and last.direction == Direction.down)
                           or (direction == Direction.down and last.kind == "CHoCH" and last.direction == Direction.up))
                if opposed and last.bars_ago <= 2 and pos.points > -0.6 * abs(pos.entry - pos.sl) / spec.point:
                    return PositionAction(
                        kind="close", ticket=pos.ticket, reason="smart_exit_choch",
                        note=f"opposite {last.direction.value} CHoCH invalidated the entry thesis",
                    )
        if self.smart.get("close_on_regime_flip", True) and snapshot is not None:
            regime = getattr(snapshot, "regime", None)
            if regime is not None and regime.regime.value in ("news_shock",):
                return PositionAction(
                    kind="close", ticket=pos.ticket, reason="smart_exit_regime",
                    note=f"regime flipped to {regime.regime.value} — protecting capital",
                )
        if forecast is not None and self.smart.get("close_if_forecast_edge_below") is not None:
            edge = float(self.smart.get("close_if_forecast_edge_below") or 0.0)
            primary = max(forecast.horizons, key=lambda h: h.confidence) if forecast.horizons else None
            if primary is not None:
                aligned = primary.p_up if direction == Direction.up else primary.p_down
                if aligned < edge and pos.points < 0:
                    return PositionAction(
                        kind="close", ticket=pos.ticket, reason="smart_exit_forecast",
                        note=f"forecast alignment dropped to {aligned:.0%} while the trade is underwater",
                    )
        return None

    def ladder_state(self, pos: Position, plan: Signal | None) -> dict[str, Any]:
        if not plan or not plan.plan:
            return {}
        sign = 1 if pos.direction == Direction.up else -1
        return {
            "next_partial": next((t.level for t in plan.plan.partials if t.level > pos.partials_done), None),
            "tp1_points": plan.plan.tp_points[0] if plan.plan.tp_points else 0,
            "distance_to_tp1": round(plan.plan.tp_points[0] - pos.points, 1) if plan.plan.tp_points else 0,
            "sign": sign,
        }


def stop_distance(pos: Position) -> float:
    return abs(pos.entry - pos.sl)


def quality_tag(zone: Any) -> str:
    return zone.quality.value if isinstance(zone.quality, ZoneQuality) else str(zone.quality)
