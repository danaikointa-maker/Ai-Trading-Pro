"""Trading Decision Engine.

Pipeline: technical context -> candidate direction -> entry conditions per
strategy -> trade plan (risk engine) -> forecast edge -> weighted score ->
risk gate -> BUY / SELL / WAIT / NO TRADE, with a full explanation trail.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from packages.shared_schemas.models import (
    Direction,
    ForecastBundle,
    Health,
    Regime,
    ScoreComponent,
    Signal,
    SignalAction,
    SignalStatus,
    SymbolSpec,
    Tick,
    TradeMode,
    Zone,
    ZoneKind,
    ZoneQuality,
)
from packages.shared_schemas.settings import Settings
from packages.strategy_rules.trend import alignment_score
from packages.strategy_rules.zones import zone_contains
from services.ai_forecast.predictor import ForecastPredictor
from services.risk_engine.engine import RiskEngine, RiskGate
from services.risk_engine.planner import PlanInputs, TradePlanner
from services.strategy_engine.analysis import AnalysisContext


@dataclass
class EntryEvaluation:
    ok: bool
    strategy: str
    zone: Zone | None = None
    reasons: list[str] = field(default_factory=list)
    conditions: dict[str, bool] = field(default_factory=dict)


class StrategyEngine:
    def __init__(self, settings: Settings, risk: RiskEngine, predictor: ForecastPredictor,
                 planner: TradePlanner) -> None:
        self.settings = settings
        self.risk = risk
        self.predictor = predictor
        self.planner = planner
        cfg = settings.strategy_cfg()
        self.scoring = cfg.get("scoring", {})
        self.weights = self.scoring.get("weights", {})
        self.thresholds = self.scoring.get("thresholds", {})
        self.strategies = cfg.get("strategies", [])
        self.risk_cfg = settings.risk_cfg()

    # ------------------------------------------------------------------ entry
    def _candidate_direction(self, ctx: AnalysisContext) -> tuple[Direction, list[str]]:
        snap = ctx.snapshot
        reasons: list[str] = []
        regime = snap.regime
        weights = {"H4": 1.5, "H1": 1.3, "M15": 1.0, "M5": 0.7, "M1": 0.4}
        score = 0.0
        for trend in snap.trend:
            w = weights.get(trend.timeframe, 0.5) * max(0.15, trend.strength)
            if trend.direction == Direction.up:
                score += w
            elif trend.direction == Direction.down:
                score -= w
        if regime and regime.regime == Regime.sideways:
            # Fade the range: direction comes from where price sits in the range.
            mid = (snap.session_high + snap.session_low) / 2
            if snap.price < mid:
                reasons.append("Range regime: price in the lower half of the session range -> look for longs at support")
                return Direction.up, reasons
            reasons.append("Range regime: price in the upper half of the session range -> look for shorts at resistance")
            return Direction.down, reasons
        direction = Direction.up if score > 0 else Direction.down if score < 0 else Direction.sideways
        reasons.append(
            f"Multi-timeframe bias {direction.value} (weighted score {score:+.2f}, "
            f"{sum(1 for t in snap.trend if t.direction == direction)}/5 timeframes aligned)")
        return direction, reasons

    def _choose_strategy(self, ctx: AnalysisContext, direction: Direction) -> list[dict[str, Any]]:
        regime = ctx.snapshot.regime.regime.value if ctx.snapshot.regime else "sideways"
        out = []
        for strat in self.strategies:
            if not strat.get("enabled", False):
                continue
            if regime in (strat.get("regimes") or []):
                out.append(strat)
        return out

    def _evaluate_entry(self, ctx: AnalysisContext, direction: Direction, spec: SymbolSpec) -> EntryEvaluation:
        snap = ctx.snapshot
        price = snap.price
        zones = snap.supports if direction == Direction.up else snap.resistances
        near = [z for z in zones if z.distance_atr <= 1.5]
        best_zone = max(near, key=lambda z: (z.strength, -z.distance_atr)) if near else None
        conditions: dict[str, bool] = {}
        reasons: list[str] = []

        regime = snap.regime.regime if snap.regime else Regime.sideways
        strategy = "trend_pullback"
        if regime == Regime.sideways:
            strategy = "range_reversion"
        elif regime == Regime.high_volatility:
            strategy = "breakout_continuation"

        # --- condition 1: higher-timeframe agreement
        htf = [t for t in snap.trend if t.timeframe in ("H4", "H1")]
        conditions["htf_trend"] = any(t.direction == direction for t in htf)
        if conditions["htf_trend"]:
            reasons.append(f"H1/H4 trend supports {direction.value}")
        else:
            reasons.append(f"H1/H4 do not support {direction.value}")

        # --- condition 2: structure
        events = [e for e in ctx.events if e.bars_ago <= 60]
        aligned_event = next((e for e in reversed(events) if e.direction == direction and e.confirmed), None)
        opposing_event = next((e for e in reversed(events) if e.direction != direction and
                               e.kind == "CHoCH" and e.bars_ago <= 8), None)
        structure_fallback = (ctx.bias == direction and ctx.bias_confidence >= 0.4)
        conditions["structure"] = (aligned_event is not None or structure_fallback) and opposing_event is None
        if aligned_event:
            reasons.append(f"{aligned_event.kind} {aligned_event.direction.value} at "
                           f"{aligned_event.level:.2f} ({aligned_event.bars_ago} bars ago)")
        if opposing_event:
            reasons.append(f"fresh opposing CHoCH at {opposing_event.level:.2f} — stand aside")

        # --- condition 3: zone quality / proximity
        if best_zone is not None:
            strong_candidate = best_zone.status.value == "confirmed" or best_zone.strength >= 0.55
            conditions["zone"] = best_zone.quality != ZoneQuality.low and strong_candidate
            reasons.append(
                f"price is {best_zone.distance_atr:.2f} ATR from {best_zone.kind.value} {best_zone.id} "
                f"({best_zone.quality.value}, {best_zone.strength:.2f}, families: {', '.join(best_zone.families)})")
        else:
            conditions["zone"] = False
            reasons.append("no qualified zone within 1.1 ATR — no structural edge")

        # --- condition 4: momentum not exhausted / not against
        ind = snap.indicators
        if direction == Direction.up:
            momentum_ok = ind.rsi14 < 74 and ind.macd_hist > -0.35 and ind.adx14 > 15
        else:
            momentum_ok = ind.rsi14 > 26 and ind.macd_hist < 0.35 and ind.adx14 > 15
        conditions["momentum"] = bool(momentum_ok)
        reasons.append(f"RSI {ind.rsi14:.0f}, MACD hist {ind.macd_hist:+.2f}, ADX {ind.adx14:.0f}")

        # --- condition 5: breakout retest for the breakout strategy
        if strategy == "breakout_continuation":
            retest = aligned_event is not None and aligned_event.bars_ago <= 10 and abs(price - aligned_event.level) <= 0.6 * (snap.indicators.atr14)
            conditions["retest"] = bool(retest)
            if retest:
                strategy = "breakout_continuation"
            else:
                strategy = "trend_pullback"
        if strategy == "range_reversion":
            edge_zone = best_zone
            conditions["range_edge"] = bool(edge_zone is not None and edge_zone.distance_atr <= 0.6)
        ok = conditions.get("zone", False) and conditions.get("structure", False) and conditions["momentum"] \
            and not opposing_event
        return EntryEvaluation(ok=ok, strategy=strategy, zone=best_zone, reasons=reasons, conditions=conditions)

    # ------------------------------------------------------------------ score
    def _score(self, ctx: AnalysisContext, direction: Direction, entry: EntryEvaluation,
               forecast: ForecastBundle, plan: Any, p_path: float) -> tuple[float, list[ScoreComponent], list[str]]:
        notes: list[str] = []
        t_weight = float(self.weights.get("trend_alignment", 20))
        s_weight = float(self.weights.get("market_structure", 15))
        z_weight = float(self.weights.get("zone_confluence", 20))
        f_weight = float(self.weights.get("forecast_edge", 20))
        m_weight = float(self.weights.get("momentum_quality", 10))
        r_weight = float(self.weights.get("reward_risk", 15))

        align, align_notes = alignment_score(ctx.snapshot.trend, direction)
        notes.extend(align_notes)
        # 0.80 weighted alignment already means "H1 and H4 agree" -> full credit.
        trend_score = min(1.0, align / 0.80) * t_weight

        events = [e for e in ctx.events if e.bars_ago <= 40 and e.direction == direction]
        if events:
            recency = max(0.0, 1.0 - events[-1].bars_ago / 40.0)
            structure_frac = 0.55 + 0.45 * recency + (0.1 if events[-1].kind == "CHoCH" else 0.0)
            structure_frac = min(1.0, structure_frac)
        else:
            structure_frac = 0.2 if ctx.bias == direction else 0.0
        structure_score = structure_frac * s_weight

        zone = entry.zone
        if zone is not None:
            q = {"high": 1.0, "medium": 0.78, "low": 0.30}[zone.quality.value]
            proximity = max(0.0, 1.0 - zone.distance_atr / 1.5)
            # strength 0.7 already means "three independent families agree", so it
            # counts as a full-quality zone rather than being permanently discounted.
            strength_norm = float(np.clip(zone.strength / 0.60, 0.0, 1.0))
            zone_score = z_weight * strength_norm * q * (0.60 + 0.40 * proximity)
        else:
            zone_score = 0.0

        primary = self._primary_horizon(forecast, plan)
        calibrated = bool(primary and primary.calibrated)
        if primary is not None and plan is not None:
            cost = float(plan.estimated_cost)
            breakeven = (plan.sl_points + cost) / max(1e-9, (plan.sl_points + plan.tp_points[0]))
            edge = max(-0.2, p_path - breakeven)
            normalized = float(np.clip(edge / 0.10, 0.0, 1.0))
            if not calibrated:
                normalized *= 0.55
            forecast_score = normalized * f_weight
            notes.append(
                f"Path model: P(TP1 before SL) = {p_path:.0%} vs {breakeven:.0%} break-even at "
                f"TP {plan.tp_points[0]:.0f}/SL {plan.sl_points:.0f} pts"
                f"{'' if calibrated else ' (unvalidated model, discounted)'}")
        else:
            forecast_score = 0.0
            notes.append("No forecast/plan -> no forecast edge credited")

        ind = ctx.snapshot.indicators
        if direction == Direction.up:
            momentum_frac = float(np.clip(
                0.35 + 0.25 * (ind.macd_hist > 0) + 0.2 * (ind.adx14 > 22) + 0.2 * (ind.volume_z > 0), 0, 1))
            if ind.rsi14 > 72:
                momentum_frac *= 0.5
                notes.append("RSI above 72 — chasing penalty applied")
        else:
            momentum_frac = float(np.clip(
                0.35 + 0.25 * (ind.macd_hist < 0) + 0.2 * (ind.adx14 > 22) + 0.2 * (ind.volume_z > 0), 0, 1))
            if ind.rsi14 < 28:
                momentum_frac *= 0.5
                notes.append("RSI below 28 — chasing penalty applied")
        momentum_score = momentum_frac * m_weight

        if plan is not None:
            min_rr = self.risk.limits().min_reward_risk
            rr_frac = float(np.clip((plan.reward_risk_net - min_rr) / 0.70, 0.0, 1.0))
            rr_score = rr_frac * r_weight
            notes.append(f"Net R:R {plan.reward_risk_net:.2f} (blended ladder) vs {min_rr:.2f} minimum")
        else:
            rr_score = 0.0

        components = [
            ScoreComponent(key="trend_alignment", label="Trend alignment", score=round(trend_score, 1),
                           max_score=t_weight, detail=f"{align * 100:.0f}% weighted multi-TF alignment"),
            ScoreComponent(key="market_structure", label="Market structure", score=round(structure_score, 1),
                           max_score=s_weight,
                           detail=(f"Latest aligned event: {events[-1].kind} {events[-1].direction.value} "
                                   f"{events[-1].bars_ago} bars ago" if events else "no aligned BOS/CHoCH")),
            ScoreComponent(key="zone_confluence", label="Zone confluence", score=round(zone_score, 1),
                           max_score=z_weight,
                           detail=(f"{zone.id} {zone.quality.value} zone, {len(zone.families)} independent "
                                   f"families, {zone.distance_atr:.2f} ATR away" if zone else "no zone in range")),
            ScoreComponent(key="forecast_edge", label="Forecast edge", score=round(forecast_score, 1),
                           max_score=f_weight,
                           detail=(f"P(TP before SL) {p_path:.0%}, calibrated={calibrated}"
                                   if primary else "no forecast")),
            ScoreComponent(key="momentum_quality", label="Momentum quality", score=round(momentum_score, 1),
                           max_score=m_weight,
                           detail=f"MACD {ind.macd_hist:+.2f}, ADX {ind.adx14:.0f}, volume z {ind.volume_z:+.1f}"),
            ScoreComponent(key="reward_risk", label="Reward / risk", score=round(rr_score, 1),
                           max_score=r_weight,
                           detail=(f"net R:R {plan.reward_risk_net:.2f}" if plan else "no valid plan")),
        ]
        total = sum(c.score for c in components)
        return round(float(np.clip(total, 0, 100)), 1), components, notes

    @staticmethod
    def _primary_horizon(forecast: ForecastBundle | None, plan: Any | None = None):
        """Pick the horizon whose expected travel actually covers the target.

        Validated horizons win over unvalidated ones; among those, choose the
        shortest horizon whose volatility budget can plausibly reach TP1.
        """
        if not forecast or not forecast.horizons:
            return None
        pool = [h for h in forecast.horizons if h.calibrated] or list(forecast.horizons)
        if plan is not None and plan.tp_points:
            need = float(plan.tp_points[0])
            covering = [h for h in pool if h.volatility_points >= need * 0.9]
            if covering:
                return min(covering, key=lambda h: h.horizon_minutes)
        preferred = [h for h in pool if h.horizon_minutes in (30, 60)]
        return max(preferred or pool, key=lambda h: h.confidence)

    # ---------------------------------------------------------------- generate
    def generate(self, ctx: AnalysisContext, symbol: str, broker_id: str, mode: TradeMode,
                 tick: Tick, broker_health: Health, forecast: ForecastBundle | None,
                 equity: float, now: float | None = None) -> Signal:
        snap = ctx.snapshot
        spec = snap.spec
        # ATR in points drives stop distance: never let it collapse to zero on a
        # flat bar, or every stop lands on the entry price.
        atr_points = max(1.0, snap.indicators.atr_points)
        now = int(now if now is not None else time.time())
        sig_id = f"S{now}-{hashlib.sha1(f'{symbol}{snap.price}{now}'.encode()).hexdigest()[:6]}"
        direction, dir_reasons = self._candidate_direction(ctx)
        reasons: list[str] = list(dir_reasons)
        blockers: list[str] = []
        # Stable codes, parallel to `blockers`. The text is for a human and
        # contains live numbers; the code is what the attribution report counts.
        blocker_codes: list[str] = []

        def block(code: str, text: str) -> None:
            blocker_codes.append(code)
            blockers.append(text)

        mode_obj = mode
        if snap.news_lockout.get("active"):
            block("news_lockout", f"news lockout: {snap.news_lockout.get('reason')}")
        if not snap.data_quality.get("ok"):
            block("data_quality", f"data quality: {snap.data_quality.get('reason')}")
        if broker_health not in (Health.connected, Health.degraded):
            block("broker_health", f"broker health is {broker_health.value}")
        if snap.regime and snap.regime.regime == Regime.news_shock:
            block("regime_news_shock", "market regime is a news shock — no new entries")

        entry = self._evaluate_entry(ctx, direction, spec) if direction != Direction.sideways else None
        entry_price = tick.ask if direction == Direction.up else tick.bid
        plan = None
        plan_notes: list[str] = []
        if direction != Direction.sideways and entry is not None:
            reasons.extend(entry.reasons)
            if not entry.ok:
                block("entry_conditions", "entry conditions are not all satisfied")
            # Settings are needed for *any* plan, not only for a blocked entry:
            # keeping this inside the `if` crashed the exact path where entry
            # conditions are satisfied (UnboundLocalError -> no signal ever sent).
            risk_settings = self.risk.settings_view()
            plan_inputs = PlanInputs(
                direction=direction,
                entry=entry_price,
                spec=spec,
                atr_points=atr_points,
                equity=equity,
                risk_pct=self.risk.limits().risk_per_trade_pct,
                spread_points=float(tick.spread_points),
                supports=snap.supports,
                resistances=snap.resistances,
                swings=[{"kind": s.kind, "price": s.price} for s in snap.swings if s.confirmed],
                target_mode=risk_settings.targets_mode,
                min_points=risk_settings.min_points,
                max_points=risk_settings.max_points,
                fixed_points=risk_settings.fixed_points,
                sl_atr_multiplier=float(self.risk_cfg.get("stops", {}).get("sl_atr_multiplier", 1.0)),
                sl_min_points=float(self.risk_cfg.get("stops", {}).get("sl_min_points", 150)),
                sl_max_points=float(self.risk_cfg.get("stops", {}).get("sl_max_points", 1200)),
                min_rr_net=self.risk.limits().min_reward_risk,
                atr_target_multiplier=float(self.risk_cfg.get("targets", {}).get("adaptive", {}).get("atr_multiplier", 2.2)),
                zone_buffer_atr=float(self.risk_cfg.get("targets", {}).get("adaptive", {}).get("zone_buffer_atr", 0.35)),
                respect_zones=bool(self.risk_cfg.get("targets", {}).get("adaptive", {}).get("respect_zones", True)),
                closes_pct=list(self.risk_cfg.get("targets", {}).get("ladder", {}).get("closes_pct", [40, 30, 30])),
            )
            result = self.planner.build(plan_inputs)
            blockers.extend(result.blockers)
            blocker_codes.extend(
                result.blocker_codes or ["no_plan"] * len(result.blockers))
            plan_notes.extend(result.notes)
            plan = result.plan

        primary = self._primary_horizon(forecast, plan)
        p_path = 0.0
        if plan is not None and primary is not None:
            p_path, _ = self.predictor.p_tp_before_sl(
                plan.tp_points[0], plan.sl_points, primary.horizon_minutes, primary.p_up,
                atr_points=atr_points,
                direction=1 if direction == Direction.up else -1)
            plan.p_tp_before_sl = round(p_path, 4)
            # Expectancy of the *first* target, net of spread + commission on both legs.
            cost = float(plan.estimated_cost)
            win = self.planner.profit_at(spec, max(0.0, plan.tp_points[0] - cost), plan.lot)
            loss = self.planner.profit_at(spec, plan.sl_points + cost, plan.lot)
            plan.expected_value = round(p_path * win - (1 - p_path) * loss, 2)

        score, components, score_notes = self._score(ctx, direction, entry or EntryEvaluation(False, ""),
                                                     forecast, plan, p_path) if entry else (0.0, [], [])
        reasons.extend(score_notes)

        calibrated_prob = p_path if (primary is not None and primary.calibrated) else None

        status = SignalStatus.no_trade
        action = SignalAction.no_trade
        if entry is not None and plan is not None and not blockers:
            strong = float(self.thresholds.get("strong", 85))
            execute = float(self.scoring.get("min_score_to_execute", 70))
            min_prob = float(self.scoring.get("min_tp_before_sl_probability", 0.42))
            if score >= strong:
                status = SignalStatus.strong
            elif score >= execute:
                status = SignalStatus.valid
            elif score >= float(self.thresholds.get("weak", 50)):
                status = SignalStatus.weak
                block("score_below_execute",
                      f"signal score {score:.0f} is below the {execute:.0f} execution threshold")
            else:
                status = SignalStatus.no_trade
                block("score_below_execute",
                      f"signal score {score:.0f} is below the {execute:.0f} execution threshold")
            if calibrated_prob is not None and calibrated_prob < min_prob:
                status = SignalStatus.weak if score >= float(self.thresholds.get("weak", 50)) else SignalStatus.no_trade
                block("probability_floor",
                      f"TP-before-SL probability {calibrated_prob:.0%} below the {min_prob:.0%} floor")
            if status in (SignalStatus.strong, SignalStatus.valid):
                action = SignalAction.buy if direction == Direction.up else SignalAction.sell
        else:
            if blockers:
                status = SignalStatus.weak if score >= float(self.thresholds.get("weak", 50)) else SignalStatus.no_trade
            if direction != Direction.sideways and score >= float(self.thresholds.get("weak", 50)):
                action = SignalAction.wait

        # Every decision that is not tradable must say why. A silent `no_trade`
        # is the one outcome the attribution report cannot explain, so the two
        # paths that produce one without a blocker get an explicit code here.
        if action not in (SignalAction.buy, SignalAction.sell) and not blocker_codes:
            if direction == Direction.sideways or entry is None:
                block("no_direction",
                      "price structure does not point anywhere — no directional candidate")
            elif plan is None:
                block("no_plan", "no executable plan could be built for this candidate")

        signal = Signal(
            id=sig_id, t=now, symbol=symbol, timeframe=snap.timeframe, broker_id=broker_id,
            action=action, status=status, score=score,
            strategy=entry.strategy if entry else "none",
            regime=snap.regime.regime.value if snap.regime else "unknown",
            components=components, reasons=reasons, blockers=blockers,
            blocker_codes=blocker_codes,
            plan=plan,
            forecast=primary, zones_used=[z.id for z in ([entry.zone] if entry and entry.zone else [])],
            mode=mode_obj, approval_required=mode_obj != TradeMode.full_auto,
            expires_at=now + 180,
            explanation={
                "conditions": entry.conditions if entry else {},
                "alignment_notes": ctx.alignment_notes,
                "plan_notes": plan_notes,
                "p_tp_before_sl": round(p_path, 4),
                "breakeven_probability": round(
                    (plan.sl_points + plan.estimated_cost)
                    / max(1e-9, (plan.sl_points + plan.tp_points[0])), 4) if plan else None,
                "calibrated": bool(primary and primary.calibrated),
                "model_version": forecast.model_version if forecast else None,
                "regime_note": snap.regime.note if snap.regime else "",
                "zone": entry.zone.model_dump() if entry and entry.zone else None,
            },
        )
        return signal

    def evaluate_gate(self, signal: Signal, spec: SymbolSpec, tick: Tick, risk_state,
                      data_quality: dict, news_lockout: dict, broker_health: Health,
                      model_approved: bool, atr_pct: float, now: float | None = None) -> RiskGate:
        """Run the risk engine against an already-built signal.

        `now` matters for anything time-relative inside the gate (today: the cooldown
        deadline). Live callers leave it None and get the wall clock; a backtest must
        pass the bar's timestamp, or a cooldown set at bar time is compared against
        today's date and never blocks anything.
        """
        return self.risk.gate(
            risk_state, spec, float(tick.spread_points), data_quality, news_lockout,
            atr_pct=atr_pct, requested_lot=signal.plan.lot if signal.plan else 0.0,
            broker_health=broker_health, is_full_auto=signal.mode == TradeMode.full_auto,
            signal_score=signal.score, now=now,
            calibrated_probability=(signal.explanation.get("p_tp_before_sl")
                                    if signal.explanation.get("calibrated") else None),
            model_approved=model_approved,
        )

    @staticmethod
    def _adapter_placeholder(health: Health, equity: float):
        class _Placeholder:
            def account_info(self):
                from packages.shared_schemas.models import AccountInfo
                return AccountInfo(broker_id="", label="", server="", account_type="demo",
                                   balance=equity, equity=equity, free_margin=equity, health=health)

            def positions(self):
                return []
        return _Placeholder()


def zone_is_entry(zone: Zone, direction: Direction, price: float) -> bool:
    if direction == Direction.up:
        return zone.kind == ZoneKind.support and zone_contains(zone, price)
    return zone.kind == ZoneKind.resistance and zone_contains(zone, price)
