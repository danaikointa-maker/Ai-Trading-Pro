"""Position management: break-even, trailing, partials, time and smart exits.

Rules live in ``config/risk.yaml`` so the behaviour is auditable and can be
backtested rather than buried in the EA.
"""
from __future__ import annotations

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


class PositionManager:
    def __init__(self, settings: Settings) -> None:
        cfg = settings.risk_cfg().get("management", {})
        self.be = cfg.get("break_even", {})
        self.trailing = cfg.get("trailing", {})
        self.time_exit = cfg.get("time_exit", {})
        self.smart = cfg.get("smart_exit", {})
        # Partials are on by default, but the switch has to actually work.
        self.partials = cfg.get("partials", {"enabled": True})

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
