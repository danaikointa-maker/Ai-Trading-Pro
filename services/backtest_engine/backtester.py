"""Event-driven backtester that reuses the production analysis + scoring code.

Fidelity notes
--------------
* Decisions are made on closed M5 bars; fills happen on the *next* bar's open
  with spread + slippage, so a bar's own future is never used for its entry.
* If a bar contains both the stop and a target, the stop is assumed first.
* Commission and spread are charged on every fill; swap is not modelled for
  intraday holds (documented assumption).
* The TP-before-SL probability table is built on the first 60% of the sample and
  reused out-of-sample, and the forecast direction proxy is rule-based, so the
  numbers measure the rule core rather than a trained model's edge.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from packages.indicators.pipeline import enrich
from packages.shared_schemas.models import (
    BacktestMetrics,
    BacktestReport,
    BacktestRequest,
    Direction,
    EquityPoint,
    ForecastBundle,
    Health,
    HorizonForecast,
    Position,
    RiskState,
    SignalAction,
    SymbolSpec,
    Tick,
    TradeMode,
    TradeRecord,
)
from packages.shared_schemas.settings import Settings
from services.ai_forecast.pathprob import PathProbabilityTable
from services.backtest_engine.metrics import compute_metrics, verdict
from services.market_data.simulator import resample
from services.risk_engine.engine import RiskEngine
from services.risk_engine.planner import TradePlanner
from services.strategy_engine.analysis import AnalysisService
from services.strategy_engine.engine import StrategyEngine


@dataclass
class SimPosition:
    direction: Direction
    entry: float
    sl: float
    sl_initial: float
    tps: list[float]
    volumes: list[float]
    partials_done: int
    remaining: float
    initial_volume: float
    opened_at: int
    entry_bar: int
    risk_amount: float
    trade_mode: TradeMode
    strategy: str
    signal_id: str
    realized: float = 0.0
    costs: float = 0.0
    entry_cost: float = 0.0
    weighted_exit: float = 0.0
    closed_volume: float = 0.0
    mfe_points: float = 0.0
    breakeven_done: bool = False
    trailing_active: bool = False
    exit_reason: str = ""
    notes: list[str] = field(default_factory=list)


class _PathAdapter:
    """Minimal predictor surface used by the scoring code inside the backtest."""

    def __init__(self, table: PathProbabilityTable | None) -> None:
        self.table = table
        self.approved = False
        self.version = "backtest-path-table"

    def p_tp_before_sl(self, tp_points: float, sl_points: float, horizon_minutes: int,
                       p_up: float, atr_points: float, direction: int = 1) -> tuple[float, int]:
        if self.table is None or atr_points <= 0:
            return 0.5 * p_up + 0.25, 0
        return self.table.p_tp_before_sl(horizon_minutes, tp_points / atr_points,
                                         sl_points / atr_points, p_up, direction)


class Backtester:
    def __init__(self, settings: Settings, risk: RiskEngine, planner: TradePlanner) -> None:
        self.settings = settings
        self.risk = risk
        self.planner = planner
        self.analysis = AnalysisService(settings, market=None, news=None)  # type: ignore[arg-type]
        self.decision_stride = 2  # every 10 minutes of market time
        risk_cfg = settings.risk_cfg()
        mgmt = risk_cfg.get("management", {})
        self.be_cfg = mgmt.get("break_even", {})
        self.trail_cfg = mgmt.get("trailing", {})
        self.time_cfg = mgmt.get("time_exit", {})
        self.kill_cfg = risk_cfg.get("kill_switch", {})

    # ------------------------------------------------------------------- run
    def run(self, m1: pd.DataFrame, spec: SymbolSpec, request: BacktestRequest,
            broker_id: str = "connext-demo") -> BacktestReport:
        started = time.time()
        spread_points = float(request.spread_points if request.spread_points is not None
                              else spec.spread_typical_points)
        commission = float(request.commission_per_lot if request.commission_per_lot is not None
                           else spec.commission_per_lot_round_turn)
        m1 = m1.tail(max(1200, min(20000, request.bars))).reset_index(drop=True)
        m5 = enrich(resample(m1, "M5"))
        m15 = enrich(resample(m1, "M15"))
        h1 = enrich(resample(m1, "H1"))
        h4 = enrich(resample(m1, "H4"))
        m1e = enrich(m1)
        n = len(m5)
        warmup = 320
        horizon_bars = [1, 3, 6, 12, 48]
        train_cut = int(n * 0.6)
        table = None
        if train_cut > 200:
            table = PathProbabilityTable.build(
                m5.iloc[:train_cut], m5["atr"].to_numpy(float)[:train_cut], horizon_bars, bar_minutes=5)
        path_adapter = _PathAdapter(table)
        strategy = StrategyEngine(self.settings, self.risk, path_adapter, self.planner)  # type: ignore[arg-type]

        balance = float(request.starting_balance)
        equity_curve: list[EquityPoint] = []
        trades: list[TradeRecord] = []
        holds: list[float] = []
        sim = {
            "balance": balance, "peak": balance, "day": None, "day_start_equity": balance,
            "consecutive_losses": 0, "cooldown_until": 0, "trades_today": 0, "trades_week": 0,
            "kill": False, "kill_reason": "", "day_pnl": 0.0,
        }
        pos: SimPosition | None = None
        decisions = 0
        skipped = 0
        last_ctx = None
        fold_marks: list[dict[str, Any]] = []
        fold_count = 4
        fold_bounds = np.linspace(warmup, n, fold_count + 1).astype(int)
        fold_times = [(int(m5["t"].iloc[min(n - 1, b)]), int(m5["t"].iloc[min(n - 1, max(0, b - 1))]))
                      for b in fold_bounds]
        per_strategy: dict[str, list[TradeRecord]] = {}
        per_regime: dict[str, list[TradeRecord]] = {}

        for i in range(warmup, n):
            bar = m5.iloc[i]
            bar_time = int(bar["t"])
            spread_price = spread_points * spec.point

            # ---------------- daily bookkeeping
            day = bar_time // 86400
            if sim["day"] != day:
                sim["day"] = day
                sim["day_start_equity"] = balance + (self._floating(pos, float(bar["c"]), spec) if pos else 0.0)
                sim["trades_today"] = 0
                if sim["kill"] and not self.kill_cfg.get("require_manual_reset", True):
                    sim["kill"] = False
                    sim["kill_reason"] = ""

            # ---------------- manage open position on this bar
            if pos is not None:
                pos, closed = self._manage_bar(pos, bar, spec, spread_price, commission)
                if closed is not None:
                    trades.append(closed)
                    holds.append((closed.closed_at - closed.opened_at) / 60.0)
                    per_strategy.setdefault(closed.strategy or "unknown", []).append(closed)
                    regime_key = self._regime_key(last_ctx)
                    per_regime.setdefault(regime_key, []).append(closed)
                    # Realised P&L must move the simulated account, otherwise the
                    # equity curve, drawdown, return and position sizing are all
                    # wrong (the account would look flat forever).
                    sim["balance"] = round(sim["balance"] + closed.pnl, 2)
                    balance = sim["balance"]
                    sim["day_pnl"] = round(balance - sim["day_start_equity"], 2)
                    if closed.pnl <= 0:
                        sim["consecutive_losses"] += 1
                        if sim["consecutive_losses"] >= self.risk.limits().max_consecutive_losses:
                            sim["cooldown_until"] = bar_time + self.risk.limits().cooldown_minutes * 60
                    else:
                        sim["consecutive_losses"] = 0
                    pos = None

            equity = balance + (self._floating(pos, float(bar["c"]), spec) if pos else 0.0)
            sim["peak"] = max(sim["peak"], equity)
            equity_curve.append(EquityPoint(
                t=bar_time, equity=round(equity, 2), balance=round(balance, 2),
                drawdown_pct=round((equity - sim["peak"]) / sim["peak"] * 100, 3) if sim["peak"] else 0.0))

            # ---------------- decision
            if i % self.decision_stride != 0 or pos is not None:
                continue
            decisions += 1
            ctx = self._context(m5, m15, h1, h4, m1e, i, spec, spread_points, broker_id)
            if ctx is None:
                continue
            last_ctx = ctx
            price = float(bar["c"])
            horizon_choice = 30
            p_up, p_side = self._direction_proxy(ctx)
            forecast = self._forecast_proxy(price, spec, ctx, p_up, p_side, horizon_choice)
            tick = Tick(t=float(bar_time), bid=price - spread_price / 2, ask=price + spread_price / 2,
                        spread_points=spread_points, last=price)
            signal = strategy.generate(ctx, spec.symbol, broker_id, TradeMode.manual, tick,
                                       Health.connected, forecast, equity, now=bar_time)
            if signal.action not in (SignalAction.buy, SignalAction.sell) or signal.plan is None:
                continue
            risk_state = RiskState(
                balance=balance, equity=equity, peak_equity=sim["peak"],
                daily_pnl=round(equity - sim["day_start_equity"], 2),
                daily_pnl_pct=round((equity - sim["day_start_equity"]) / max(1e-9, sim["day_start_equity"]) * 100, 3),
                weekly_pnl=round(equity - request.starting_balance, 2),
                weekly_pnl_pct=round((equity - request.starting_balance) / request.starting_balance * 100, 3),
                drawdown_pct=round((equity - sim["peak"]) / max(1e-9, sim["peak"]) * 100, 3),
                open_trades=0, open_lots=0.0, exposure_pct=0.0,
                consecutive_losses=sim["consecutive_losses"], trades_today=sim["trades_today"],
                trades_this_week=sim["trades_today"], cooldown_until=sim["cooldown_until"] or None,
                kill_switch_active=sim["kill"], kill_switch_reason=sim["kill_reason"],
            )
            gate = strategy.evaluate_gate(
                signal, spec, tick, risk_state, ctx.snapshot.data_quality, {"active": False},
                Health.connected, False,
                ctx.snapshot.indicators.atr14 / price * 100 if price else 0.0)
            if not gate.allow:
                continue

            # ---------------- open on the next bar's open
            if i + 1 >= n:
                continue
            nxt = m5.iloc[i + 1]
            sign = 1 if signal.action == SignalAction.buy else -1
            raw_open = float(nxt["o"]) + sign * (spread_price / 2 + request.slippage_points * spec.point)
            entry = spec.round_price(raw_open)
            plan = signal.plan
            # If the market gapped away from the plan between the decision bar and
            # the fill, the stop/target geometry no longer holds: the "trade" would
            # start next to its stop (or past its first target). Skip it rather
            # than book a meaningless R multiple.
            planned_distance = abs(plan.entry - plan.sl)
            drift = abs(entry - plan.entry)
            # Two independent guards: the fill may not drift far in absolute terms
            # (slippage) and may not eat more than a quarter of the stop distance.
            max_drift = min(planned_distance * 0.25,
                            max(spread_price * 3.0, spec.points_to_price(5)))
            remaining_stop = abs(entry - plan.sl)
            if drift > max_drift or remaining_stop < planned_distance * 0.5:
                skipped += 1
                continue
            if (sign > 0 and (entry <= plan.sl or entry >= plan.tp1)) or \
                    (sign < 0 and (entry >= plan.sl or entry <= plan.tp1)):
                skipped += 1
                continue
            qty = plan.lot
            if qty < spec.min_lot:
                continue
            volumes = [round(qty * p.close_pct / 100.0, 4) for p in plan.partials]
            volumes = [v if v >= spec.min_lot else 0.0 for v in volumes]
            volumes[-1] = round(qty - sum(volumes[:-1]), 4)
            if volumes[-1] < spec.min_lot:
                volumes = [qty, 0.0, 0.0]
            # The plan was priced off the decision bar; the fill happens on the
            # next bar's open plus slippage. Absolute SL/TP levels stay where the
            # structure put them, so the money actually at risk can differ from
            # the budget. Measure it at the fill instead of assuming the plan.
            # price distance -> points -> money (forgetting the /point step turns
            # a $48 risk into $0.49 and every R multiple into nonsense)
            actual_risk = (abs(entry - plan.sl) / spec.point) * spec.value_per_point_per_lot * qty
            pos = SimPosition(
                direction=signal.action == SignalAction.buy and Direction.up or Direction.down,
                entry=entry, sl=plan.sl, sl_initial=plan.sl,
                tps=[plan.tp1, plan.tp2, plan.tp3], volumes=volumes, partials_done=0,
                remaining=qty, initial_volume=qty, opened_at=int(nxt["t"]), entry_bar=i + 1,
                risk_amount=round(actual_risk, 2) or plan.risk_amount,
                trade_mode=TradeMode.manual, strategy=signal.strategy,
                signal_id=signal.id,
                # The spread half and the slippage are already inside `entry`, so
                # the money they cost is invisible unless it is booked here.
                entry_cost=round((spread_price / 2 + request.slippage_points * spec.point)
                                 / spec.point * spec.value_per_point_per_lot * qty, 2),
            )
            pos.costs += pos.entry_cost
            sim["trades_today"] += 1
            sim["trades_week"] += 1

        # fold metrics
        for f in range(fold_count):
            lo, hi = fold_bounds[f], fold_bounds[f + 1]
            t_lo, t_hi = fold_times[f][0], fold_times[f + 1][0]
            fold_trades = [t for t in trades if t_lo <= t.opened_at < t_hi]
            fold_curve = [p for p in equity_curve if t_lo <= p.t < t_hi]
            m = compute_metrics(fold_trades, fold_curve, max(1, (hi - lo) // self.decision_stride),
                                request.starting_balance)
            fold_marks.append({
                "fold": f + 1, "trades": m.trades, "net_profit": m.net_profit,
                "profit_factor": m.profit_factor, "win_rate": m.win_rate,
                "max_drawdown_pct": m.max_drawdown_pct, "expectancy": m.expectancy,
            })

        metrics = compute_metrics(trades, equity_curve, decisions, request.starting_balance, holds)
        gap_notes = ([
            f"{skipped} signal(s) were not taken because the fill gapped outside the plan's "
            f"entry tolerance (stop already too close or first target already gone)."
        ] if skipped else [])
        report = BacktestReport(
            id=f"BT-{uuid.uuid4().hex[:8].upper()}",
            created_at=int(time.time()),
            symbol=spec.symbol,
            strategy=request.strategy,
            broker_id=broker_id,
            bars=len(m1),
            from_t=int(m5["t"].iloc[warmup]),
            to_t=int(m5["t"].iloc[-1]),
            metrics=metrics,
            equity_curve=equity_curve[:: max(1, len(equity_curve) // 600)],
            trades=trades[-200:],
            per_strategy={k: compute_metrics(v, [], len(v), request.starting_balance) for k, v in per_strategy.items()},
            per_regime={k: compute_metrics(v, [], len(v), request.starting_balance) for k, v in per_regime.items()},
            walk_forward=fold_marks,
            assumptions=[
                f"Spread {spread_points:.0f} points and commission {commission:.2f}/lot on every fill; "
                f"slippage {request.slippage_points:.1f} points.",
                "No swap/modelling of overnight financing (intraday strategy).",
                "When a bar contains both stop and target, the stop is assumed first (conservative).",
                "The trained ML model's directional edge is NOT used inside this backtest; the "
                "forecast component is a deterministic rule proxy and is discounted as unvalidated.",
                "TP-before-SL probability table is fitted on the first 60% of the sample and reused "
                "out-of-sample, so it is mildly in-sample for early folds.",
                f"Decisions every {self.decision_stride * 5} minutes of market time; "
                f"{len(trades)} trades from {decisions} decision points.",
                "Simulated feed data — replace with MT5 tick history before trusting any number here.",
                *gap_notes,
            ],
            verdict=verdict(metrics),
        )
        del started
        return report

    # -------------------------------------------------------------- context
    def _context(self, m5, m15, h1, h4, m1e, i: int, spec: SymbolSpec, spread_points: float,
                 broker_id: str) -> Any:
        t_now = int(m5["t"].iloc[i])
        base = m5.iloc[max(0, i - 899): i + 1]
        frames = {
            "M5": base,
            "M15": m15[m15["t"] <= t_now].tail(600),
            "H1": h1[h1["t"] <= t_now].tail(500),
            "H4": h4[h4["t"] <= t_now].tail(300),
            "M1": m1e[m1e["t"] <= t_now].tail(600),
        }
        if len(frames["M1"]) < 220 or len(frames["H1"]) < 60:
            return None
        price = float(base["c"].iloc[-1])
        quality = {"ok": True, "health": "connected", "staleness_seconds": 0.0,
                   "spread_points": spread_points, "reason": "", "feed": "backtest"}
        daily = m15[m15["t"] <= t_now]
        daily_bars = resample(daily.assign(t=daily["t"]), "D1") if len(daily) > 100 else None
        return self.analysis.assemble(spec.symbol, spec, frames, price, quality, {"active": False},
                                      broker_id, daily_bars)

    @staticmethod
    def _regime_key(ctx: Any) -> str:
        if ctx is None:
            return "unknown"
        return ctx.snapshot.regime.regime.value if ctx.snapshot.regime else "unknown"

    @staticmethod
    def _direction_proxy(ctx: Any) -> tuple[float, float]:
        """Deterministic direction prior from structure/trend only (no look-ahead)."""
        weights = {"H4": 1.4, "H1": 1.2, "M15": 1.0, "M5": 0.7, "M1": 0.4}
        score = 0.0
        for trend in ctx.snapshot.trend:
            w = weights.get(trend.timeframe, 0.5) * trend.strength
            score += w if trend.direction == Direction.up else -w if trend.direction == Direction.down else 0.0
        p_up = float(1 / (1 + np.exp(-1.6 * score)))
        atr_pctile = getattr(ctx.snapshot.regime, "atr_percentile", 0.5) if ctx.snapshot.regime else 0.5
        p_side = float(np.clip(0.45 - 0.25 * atr_pctile, 0.05, 0.6))
        return float(np.clip(p_up, 0.05, 0.95)) * (1 - p_side) + 0.5 * p_side, p_side

    @staticmethod
    def _forecast_proxy(price: float, spec: SymbolSpec, ctx: Any, p_up: float, p_side: float,
                        horizon: int) -> ForecastBundle:
        atr = ctx.snapshot.indicators.atr14
        p_down = float(np.clip(1 - p_up - p_side, 0.02, 0.9))
        band = atr * np.sqrt(horizon / 5)
        row = HorizonForecast(
            horizon_minutes=horizon, p_up=round(p_up, 3), p_down=round(p_down, 3),
            p_sideways=round(p_side, 3), calibrated=False, method="rule-proxy",
            expected_move_points=round((p_up - p_down) * band / spec.point, 1),
            p10_points=round(-1.28 * band / spec.point, 0), p50_points=0.0,
            p90_points=round(1.28 * band / spec.point, 0),
            p10_price=round(price - 1.28 * band, spec.digits),
            p50_price=round(price, spec.digits),
            p90_price=round(price + 1.28 * band, spec.digits),
            confidence=0.3, coverage_note="Rule proxy — not a validated model.",
            invalidate_above=round(price + band, spec.digits),
            invalidate_below=round(price - band, spec.digits),
        )
        return ForecastBundle(symbol=spec.symbol, generated_at=int(ctx.snapshot.server_time), price=price,
                              model_version="backtest-proxy", model_approved=False, method="rule-proxy",
                              confidence=0.3, horizons=[row], scenarios=[], invalidation=[], narrative="",
                              metrics={})

    # ------------------------------------------------------------ simulation
    @staticmethod
    def _floating(pos: SimPosition | None, price: float, spec: SymbolSpec) -> float:
        if pos is None:
            return 0.0
        sign = 1 if pos.direction == Direction.up else -1
        return spec.pnl_in_account_currency((price - pos.entry) * sign, pos.remaining)

    def _manage_bar(self, pos: SimPosition, bar: pd.Series, spec: SymbolSpec, spread_price: float,
                    commission: float) -> tuple[SimPosition | None, TradeRecord | None]:
        high, low, close = float(bar["h"]), float(bar["l"]), float(bar["c"])
        bar_time = int(bar["t"])
        sign = 1 if pos.direction == Direction.up else -1
        points = (close - pos.entry) * sign / spec.point
        pos.mfe_points = max(pos.mfe_points, (high - pos.entry) * sign / spec.point if sign > 0
                             else (pos.entry - low) / spec.point)

        def book(volume: float, price: float, reason: str) -> None:
            nonlocal pos
            # Account currency, not quote currency: a JPY-quoted pair would
            # otherwise book ~157x the real profit next to USD commission.
            pnl = spec.pnl_in_account_currency((price - pos.entry) * sign, volume)
            cost = commission * volume
            pos.realized += pnl - cost
            pos.costs += cost
            pos.weighted_exit += price * volume
            pos.closed_volume += volume
            pos.remaining = round(pos.remaining - volume, 4)
            pos.exit_reason = reason

        # --- stop first (conservative intrabar assumption)
        stop_hit = (pos.direction == Direction.up and low <= pos.sl) or \
                   (pos.direction == Direction.down and high >= pos.sl)
        if stop_hit:
            book(pos.remaining, pos.sl, "stop loss")
            return None, self._finalize(pos, bar_time, spec)

        # --- targets in order
        for idx in range(pos.partials_done, 3):
            tp = pos.tps[idx]
            hit = (pos.direction == Direction.up and high >= tp) or (pos.direction == Direction.down and low <= tp)
            if not hit:
                break
            volume = pos.volumes[idx]
            if volume <= 0:
                pos.partials_done = idx + 1
                continue
            volume = min(volume, pos.remaining)
            if pos.remaining - volume < spec.min_lot:
                volume = pos.remaining
            book(volume, tp, "take profit" if idx == 2 or pos.remaining - volume < 1e-9 else f"partial_tp{idx + 1}")
            pos.partials_done = idx + 1
            if pos.remaining <= 1e-9:
                return None, self._finalize(pos, bar_time, spec)

        # --- break-even / trailing at bar close
        if self.be_cfg.get("enabled", True) and not pos.breakeven_done:
            if points >= float(self.be_cfg.get("trigger_points", 250)):
                lock = sign * spec.points_to_price(float(self.be_cfg.get("lock_points", 30)))
                candidate = spec.round_price(pos.entry + lock)
                if (sign > 0 and candidate > pos.sl) or (sign < 0 and candidate < pos.sl):
                    pos.sl = candidate
                    pos.breakeven_done = True
        if self.trail_cfg.get("enabled", True) and points >= float(self.trail_cfg.get("start_after_points", 500)):
            atr_points = max(1.0, (float(bar["h"]) - float(bar["l"])) / spec.point)
            distance = (float(self.trail_cfg.get("atr_multiplier", 1.0)) * atr_points
                        if self.trail_cfg.get("mode", "atr") == "atr"
                        else float(self.trail_cfg.get("distance_points", 300)))
            candidate = spec.round_price(close - sign * spec.points_to_price(distance))
            step = spec.points_to_price(float(self.trail_cfg.get("step_points", 50)))
            if (candidate - pos.sl) * sign >= step:
                pos.sl = candidate
                pos.trailing_active = True

        # --- time exit
        if self.time_cfg.get("enabled", True):
            minutes = (bar_time - pos.opened_at) / 60.0
            if minutes >= float(self.time_cfg.get("max_minutes_in_trade", 240)) and \
                    points < float(self.time_cfg.get("close_if_profit_below_points", 50)):
                book(pos.remaining, close, "time_exit")
                return None, self._finalize(pos, bar_time, spec)
        return pos, None

    @staticmethod
    def _finalize(pos: SimPosition, bar_time: int, spec: SymbolSpec) -> TradeRecord:
        avg_exit = pos.weighted_exit / pos.closed_volume if pos.closed_volume else pos.entry
        sign = 1 if pos.direction == Direction.up else -1
        points = (avg_exit - pos.entry) * sign / spec.point
        # Net P&L already carries the spread inside the entry price; adding the
        # booked costs back gives the cost-free result, so gross - pnl == costs.
        net = pos.realized
        gross = net + pos.costs
        return TradeRecord(
            ticket=f"BT{pos.entry_bar}-{pos.signal_id[-6:]}",
            symbol=spec.symbol, direction=pos.direction, volume=round(pos.closed_volume, 4),
            entry=round(pos.entry, spec.digits), exit=round(avg_exit, spec.digits),
            sl=round(pos.sl_initial, spec.digits),
            tp=round(pos.tps[0], spec.digits),
            opened_at=pos.opened_at, closed_at=bar_time,
            points=round(points, 1), gross_pnl=round(gross, 2), costs=round(pos.costs, 2),
            pnl=round(pos.realized, 2),
            r_multiple=round(pos.realized / pos.risk_amount, 2) if pos.risk_amount else 0.0,
            exit_reason=pos.exit_reason or "closed", strategy=pos.strategy,
            signal_id=pos.signal_id, mode=pos.trade_mode, broker_id="backtest",
            journal={"max_favorable_points": round(pos.mfe_points, 1),
                     "partials_done": pos.partials_done, "breakeven_done": pos.breakeven_done,
                     "trailing_active": pos.trailing_active,
                     "risk_amount": round(pos.risk_amount, 2)},
        )


def positions_from_reports(*_: Any) -> list[Position]:
    return []
