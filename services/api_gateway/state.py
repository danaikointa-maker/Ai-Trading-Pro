"""Application runtime: owns every service and the background trading loop.

Threading model
---------------
one worker thread drives the simulated feed, position management and the
decision cycle. The FastAPI handlers only read immutable snapshots (guarded by
a lock) or call explicit actions, so a slow HTTP request can never stall
trading and vice versa.
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from collections import deque
from typing import Any

from integrations.brokers.base import BrokerAdapter, BrokerError
from integrations.brokers.registry import BrokerRegistry
from packages.persistence.db import Database
from packages.shared_schemas.models import (
    AnalysisSnapshot,
    Direction,
    ForecastBundle,
    Health,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderState,
    Position,
    Signal,
    SignalAction,
    SignalStatus,
    Tick,
    TradeMode,
    TradeRecord,
)
from packages.shared_schemas.settings import Settings, get_settings
from services.ai_forecast.predictor import ForecastPredictor
from services.ai_forecast.registry import ModelRegistry
from services.ai_forecast.trainer import ForecastTrainer
from services.execution_gateway.gateway import ExecutionGateway
from services.market_data.news import NewsService
from services.market_data.service import MarketDataService
from services.market_data.simulator import SyntheticFeed
from services.notification.notifier import Notifier
from services.risk_engine.engine import RiskEngine, default_risk_state
from services.risk_engine.manager import PositionAction, PositionManager
from services.risk_engine.planner import PlanInputs, TradePlanner
from services.strategy_engine.analysis import AnalysisContext, AnalysisService
from services.strategy_engine.engine import StrategyEngine

class TradingRuntime:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.db = Database(self.settings.database_path)
        md = self.settings.market_data
        sim = md.get("simulation", {})

        # --- market data: union of symbols from every simulated broker profile
        symbols: dict[str, dict[str, Any]] = {}
        for profile in self.settings.brokers.get("brokers", []):
            if profile.get("adapter") in ("simulated_mt5", "paper"):
                for symbol, spec in (profile.get("symbols") or {}).items():
                    symbols.setdefault(symbol, spec)
        self.feed = SyntheticFeed(
            symbols=symbols or {"XAUUSD": self.settings.symbol_spec("connext-demo", "XAUUSD")},
            history_bars=int(md.get("history_bars", 60000)),
            seed=int(sim.get("seed", 7)),
            start_price=float(sim.get("start_price", 4180.0)),
            annual_vol=float(sim.get("annual_volatility", 0.16)),
            speed_minutes_per_second=float(sim.get("speed_minutes_per_second", 6.0)),
            tick_seconds=float(sim.get("tick_seconds", 0.5)),
            news_shock_probability=float(sim.get("news_shock_probability", 0.0015)),
        )
        self.db.kv_set("virtual_clock_start", self.feed.end_time)

        self.registry = BrokerRegistry(self.settings, self.feed)
        self.registry.build()
        for adapter in self.registry.all():
            if hasattr(adapter, "clock"):
                adapter.clock = lambda: self.feed.end_time  # type: ignore[attr-defined]

        self.news = NewsService(self.db, high_impact_currencies=["USD"], now=self.feed.end_time)
        self.market = MarketDataService(self.settings, self.registry, self.news)
        self.market.set_virtual_now(self.feed.end_time)

        # --- engines
        self.risk = RiskEngine(self.settings, self.db)
        self.model_registry = ModelRegistry(self.settings.paths["models"], self.db)
        self.predictor = ForecastPredictor(self.settings, self.model_registry)
        self.analysis = AnalysisService(self.settings, self.market, self.news)
        self.planner = TradePlanner(self.settings.risk_cfg(), self.settings.strategy_cfg())
        self.strategy = StrategyEngine(self.settings, self.risk, self.predictor, self.planner)
        self.manager = PositionManager(self.settings)
        self.gateway = ExecutionGateway(self.settings, self.db)
        self.notifier = Notifier(self.db, min_score=float(self.settings.strategy_cfg()
                                                          .get("scoring", {}).get("thresholds", {}).get("weak", 50)))
        self.trainer = ForecastTrainer(self.settings)

        # --- runtime state
        self.lock = threading.RLock()
        self.contexts: dict[str, AnalysisContext] = {}
        self.forecasts: dict[str, ForecastBundle] = {}
        self.signals: dict[str, Signal] = {}
        self.signal_log: deque[Signal] = deque(maxlen=400)
        self.plans: dict[str, Signal] = {}
        self.gates: dict[str, dict[str, Any]] = {}
        self.positions_cache: list[Position] = []
        self.ticks: dict[str, Tick] = {}
        self.version = 0
        self.started_at = time.time()
        self.last_decision_at = 0.0
        self.last_tick_at = 0.0
        self.last_reconcile: dict[str, Any] = {}
        self.errors: deque[dict[str, Any]] = deque(maxlen=25)
        self.mode = self.risk.record_mode()
        self.model_approved = bool(self.predictor.approved)
        self.training: dict[str, Any] = {"state": "idle", "message": "", "pct": 0.0, "version": None}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._decision_interval = float(self.settings.app.get("app", {}).get("decision_interval_seconds", 4))
        self._alert_dedupe: dict[str, int] = {}
        self._last_persisted: dict[str, tuple[str, float]] = {}
        self._forecast_invalid: dict[str, bool] = {}
        self.active_symbol = self.settings.market_data.get("default_symbol", "XAUUSD")

    # -------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        # Run one cycle inline: the dashboard's very first paint then has a
        # snapshot/forecast instead of an empty card that fills in seconds later.
        self.prime()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="no7-runtime", daemon=True)
        self._thread.start()
        if self.settings.ai.get("training", {}).get("auto_train_on_boot", True):
            self.train_async(self.active_symbol)

    def prime(self) -> None:
        """Compute the first snapshot/forecast synchronously (never fatal)."""
        for step in (self._tick_cycle, self._decision_cycle):
            try:
                step()
            except Exception as exc:  # noqa: BLE001 - boot must not die on data
                self._log_error("prime", exc)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self) -> None:
        next_decision = 0.0
        next_reconcile = 0.0
        tick_seconds = float(self.settings.market_data.get("simulation", {}).get("tick_seconds", 0.5))
        while not self._stop.is_set():
            cycle_start = time.time()
            try:
                self._tick_cycle()
                now = time.time()
                if now >= next_decision:
                    next_decision = now + self._decision_interval
                    self._decision_cycle()
                if now >= next_reconcile:
                    next_reconcile = now + float(self.settings.execution.get("reconcile_interval_seconds", 10))
                    self._reconcile_cycle()
                self._record_equity()
            except Exception as exc:  # noqa: BLE001 - the loop must survive anything
                self._log_error("runtime", exc)
            elapsed = time.time() - cycle_start
            self._stop.wait(max(0.05, tick_seconds - elapsed))

    def _log_error(self, where: str, exc: Exception) -> None:
        self.errors.append({"where": where, "error": str(exc), "t": time.time(),
                            "trace": traceback.format_exc()[-1500:]})

    @property
    def adapter(self) -> BrokerAdapter:
        return self.registry.get()

    def symbols(self) -> list[str]:
        return self.adapter.symbol_names()

    # ------------------------------------------------------------- tick cycle
    def _tick_cycle(self) -> None:
        ticks = self.feed.tick()
        self.feed.advance_clock()
        now = self.feed.end_time
        self.market.set_virtual_now(now)
        self.market.on_ticks(ticks)
        self.news.refresh(now)
        with self.lock:
            self.ticks.update(ticks)
            self.last_tick_at = now
        for adapter in self.registry.all():
            try:
                closed = adapter.on_tick(ticks)
            except Exception as exc:  # noqa: BLE001
                self._log_error(f"adapter:{adapter.id}", exc)
                continue
            for trade in closed:
                self._on_trade_closed(trade)
        self._manage_cycle(now)
        self.version += 1

    def _on_trade_closed(self, trade: TradeRecord) -> None:
        self.gateway.record_trade(trade)
        self._journal(trade)
        tone = "success" if trade.pnl >= 0 else "warning"
        self.notifier.emit(tone, f"Trade closed {'+' if trade.pnl >= 0 else ''}{trade.pnl:.2f} USD",
                           f"{trade.symbol} {trade.direction.value} {trade.volume} lot closed at "
                           f"{trade.exit:.2f} ({trade.points:+.0f} pts) via {trade.exit_reason}",
                           symbol=trade.symbol, meta={"ticket": trade.ticket, "pnl": trade.pnl}, dedupe_seconds=0)
        with self.lock:
            self.version += 1
        if trade.pnl < 0 and self.risk.state(self.adapter, now=self.market.now()).consecutive_losses >= \
                self.risk.limits().max_consecutive_losses:
            self.notifier.emit("critical", "Cooldown engaged",
                               f"{self.risk.limits().max_consecutive_losses} consecutive losses — new entries paused "
                               f"for {self.risk.limits().cooldown_minutes} minutes.", dedupe_seconds=0)

    def _journal(self, trade: TradeRecord) -> None:
        """Deterministic, data-driven trade journal entry (no LLM required)."""
        worked, failed = [], []
        rr = trade.r_multiple
        if trade.pnl > 0:
            worked.append(f"setup followed the plan and captured {trade.points:+.0f} points")
            if rr >= 1.5:
                worked.append(f"reward reached {rr:.1f}R — the ladder had room")
        else:
            failed.append(f"invalidation hit at {trade.points:+.0f} points ({trade.exit_reason})")
            if trade.journal.get("max_favorable_points", 0) > 0:
                failed.append(f"price ran {trade.journal['max_favorable_points']:.0f} points in favour before failing "
                              f"— consider the break-even rule triggering earlier")
        if trade.exit_reason in ("time_exit", "smart_exit_choch", "smart_exit_forecast"):
            worked.append("exit rule protected capital instead of waiting for the stop")
        lesson = ("Keep the same risk per trade; repeatable process beats single winners."
                  if trade.pnl > 0 else
                  "A loss inside the risk budget is a business cost, not a mistake — only a violated rule is a mistake.")
        entry = {
            "trade": trade.model_dump(),
            "headline": f"{trade.symbol} {trade.direction.value.upper()} {trade.volume} lot — "
                        f"{'win' if trade.pnl >= 0 else 'loss'} {trade.pnl:+.2f} USD",
            "what_worked": worked,
            "what_failed": failed,
            "lesson": lesson,
            "tags": [trade.strategy or "unlabelled", trade.exit_reason, trade.mode.value
                     if hasattr(trade.mode, "value") else str(trade.mode)],
        }
        self.db.execute("INSERT OR REPLACE INTO journal(ticket, created_at, payload) VALUES(?,?,?)",
                        (trade.ticket, int(trade.closed_at), json.dumps(entry, default=str)))

    # --------------------------------------------------------- decision cycle
    def _decision_cycle(self) -> None:
        now = self.market.now()
        symbols = self.symbols()
        equity = 0.0
        health = Health.disconnected
        try:
            info = self.adapter.account_info()
            equity = info.equity
            health = info.health
        except Exception as exc:  # noqa: BLE001
            self._log_error("account", exc)
        try:
            risk_state = self.risk.state(self.adapter, now=now)
        except Exception:  # noqa: BLE001
            risk_state = default_risk_state(equity)

        for symbol in symbols:
            try:
                self._decide_symbol(symbol, equity, health, risk_state, now)
            except Exception as exc:  # noqa: BLE001
                self._log_error(f"decision:{symbol}", exc)
        with self.lock:
            self.last_decision_at = now

    def _decide_symbol(self, symbol: str, equity: float, health: Health, risk_state, now: float) -> None:
        ctx = self.analysis.snapshot(symbol)
        spec = ctx.snapshot.spec
        forecast: ForecastBundle | None = None
        try:
            forecast = self.predictor.forecast(ctx.frames["M5"], spec, symbol)
            forecast.regime = ctx.snapshot.regime.regime.value if ctx.snapshot.regime else ""
        except Exception as exc:  # noqa: BLE001
            self._log_error(f"forecast:{symbol}", exc)
        tick = self.market.ticker(symbol)
        signal = self.strategy.generate(
            ctx, symbol, self.adapter.id, self.mode, tick, health, forecast, equity, now=now)
        atr_pct = (ctx.snapshot.indicators.atr14 / ctx.snapshot.price * 100) if ctx.snapshot.price else 0.0
        gate = self.strategy.evaluate_gate(
            signal, spec, tick, risk_state, ctx.snapshot.data_quality, ctx.snapshot.news_lockout,
            health, self.predictor.approved, atr_pct)
        if not gate.allow:
            signal.blockers = list(dict.fromkeys(signal.blockers + gate.blockers))
            if signal.action in (SignalAction.buy, SignalAction.sell):
                signal.action = SignalAction.wait
                signal.status = SignalStatus.weak if signal.score >= 50 else SignalStatus.no_trade

        with self.lock:
            self.contexts[symbol] = ctx
            if forecast:
                self.forecasts[symbol] = forecast
            self.signals[symbol] = signal
            self.plans[signal.id] = signal
            self.gates[symbol] = {
                "allow": gate.allow, "blockers": gate.blockers, "warnings": gate.warnings,
                "checks": gate.checks, "t": now,
            }
            self.signal_log.append(signal)
            self.version += 1
        self._persist_signal(signal, now)
        self._maybe_alert(signal, ctx, now)

        if self.mode == TradeMode.full_auto and signal.action in (SignalAction.buy, SignalAction.sell):
            self.execute_signal(signal.id, actor="full-auto")

    def _persist_signal(self, signal: Signal, now: float) -> None:
        last = self._last_persisted.get(signal.symbol)
        changed = (last is None or last[0] != signal.action.value or now - last[1] > 300
                   or signal.status in (SignalStatus.strong, SignalStatus.valid))
        if not changed:
            return
        self._last_persisted[signal.symbol] = (signal.action.value, now)
        self.db.execute(
            "INSERT OR REPLACE INTO signals(id, t, symbol, action, score, payload) VALUES(?,?,?,?,?,?)",
            (signal.id, signal.t, signal.symbol, signal.action.value, signal.score,
             json.dumps(signal.model_dump(), default=str)),
        )

    def _maybe_alert(self, signal: Signal, ctx: AnalysisContext, now: float) -> None:
        if signal.action in (SignalAction.buy, SignalAction.sell) and signal.status in (
                SignalStatus.strong, SignalStatus.valid):
            key = f"{signal.symbol}:{signal.action.value}"
            if now - self._alert_dedupe.get(key, 0) < 120:
                return
            self._alert_dedupe[key] = now
            plan = signal.plan
            self.notifier.emit(
                "success" if signal.status == SignalStatus.strong else "info",
                f"{signal.action.value} signal {signal.score:.0f}/100 — {signal.symbol}",
                (f"{signal.strategy} setup, entry {plan.entry:.2f}, SL {plan.sl:.2f} "
                 f"({plan.sl_points:.0f} pts), TP1 {plan.tp1:.2f} ({plan.tp_points[0]:.0f} pts), "
                 f"lot {plan.lot}. Net R:R {plan.reward_risk_net:.2f}." if plan else ""),
                symbol=signal.symbol, meta={"signal_id": signal.id, "score": signal.score}, dedupe_seconds=0)
        # forecast invalidation watchdog
        forecast = self.forecasts.get(signal.symbol)
        primary = signal.forecast
        if forecast and primary:
            invalid = ctx.snapshot.price > primary.invalidate_above or ctx.snapshot.price < primary.invalidate_below
            if invalid and not self._forecast_invalid.get(signal.symbol):
                self._forecast_invalid[signal.symbol] = True
                self.notifier.emit("warning", f"Forecast invalidated on {signal.symbol}",
                                   f"Price {ctx.snapshot.price:.2f} left the projected band "
                                   f"({primary.invalidate_below:.2f}–{primary.invalidate_above:.2f}); re-running the "
                                   f"analysis before acting.", symbol=signal.symbol, dedupe_seconds=0)
            elif not invalid:
                self._forecast_invalid[signal.symbol] = False

    # --------------------------------------------------------- manage cycle
    def _manage_cycle(self, now: float) -> None:
        try:
            positions = self.adapter.positions()
        except Exception as exc:  # noqa: BLE001
            self._log_error("positions", exc)
            return
        with self.lock:
            self.positions_cache = positions
            plans = dict(self.plans)
            ctx = self.contexts.get(self.active_symbol)
            forecast = self.forecasts.get(self.active_symbol)
        specs = {p.symbol: self.adapter.symbol_spec(p.symbol) for p in positions}
        atr_points = 0.0
        if ctx is not None:
            atr_points = ctx.snapshot.indicators.atr_points
        actions: list[PositionAction] = self.manager.evaluate(
            positions, specs, plans, forecast, ctx.snapshot if ctx else None, now, atr_points)
        for action in actions:
            try:
                self._apply_action(action, specs)
            except Exception as exc:  # noqa: BLE001
                self._log_error(f"action:{action.kind}", exc)
        # Always sync (including the empty list) so a closed trade cannot linger
        # in the local mirror and trip the reconciler.
        self.gateway.open_position_snapshot(positions)

    def _apply_action(self, action: PositionAction, specs: dict[str, Any]) -> None:
        if action.kind == "modify" and action.new_sl is not None:
            ok = self.gateway.modify(self.adapter, action.ticket, sl=action.new_sl, reason=action.reason)
            if ok:
                self.notifier.emit("info", f"Stop moved ({action.reason.replace('_', ' ')})",
                                   f"Ticket {action.ticket}: {action.note}", dedupe_seconds=20)
        elif action.kind == "partial_close":
            result = self.gateway.close(self.adapter, action.ticket, volume=action.volume,
                                        reason=action.reason, actor="position-manager")
            self.notifier.emit("success", f"Partial close {action.reason.replace('_', ' ')}",
                               f"Ticket {action.ticket} closed {action.volume} lot — {action.note}",
                               dedupe_seconds=0)
            del result
        elif action.kind == "close":
            self.gateway.close(self.adapter, action.ticket, reason=action.reason, actor="position-manager")
            self.notifier.emit("warning", "Position closed by management rule",
                               f"Ticket {action.ticket}: {action.note}", dedupe_seconds=0)

    # ------------------------------------------------------------- execution
    def build_manual_plan(self, symbol: str, direction: Direction) -> tuple[Signal | None, str]:
        with self.lock:
            ctx = self.contexts.get(symbol)
        if ctx is None:
            return None, "no analysis available yet"
        latest = self.signals.get(symbol)
        if latest and latest.plan and latest.plan.direction == direction and latest.action.value in ("BUY", "SELL"):
            return latest, ""
        tick = self.market.ticker(symbol)
        spec = ctx.snapshot.spec
        equity = self.adapter.account_info().equity
        entry_price = tick.ask if direction == Direction.up else tick.bid
        settings = self.risk.settings_view()
        result = self.planner.build(PlanInputs(
            direction=direction, entry=entry_price, spec=spec,
            atr_points=max(1.0, ctx.snapshot.indicators.atr_points), equity=equity,
            risk_pct=self.risk.limits().risk_per_trade_pct, spread_points=float(tick.spread_points),
            supports=ctx.snapshot.supports, resistances=ctx.snapshot.resistances,
            swings=[{"kind": s.kind, "price": s.price} for s in ctx.snapshot.swings if s.confirmed],
            target_mode=settings.targets_mode, min_points=settings.min_points, max_points=settings.max_points,
            fixed_points=settings.fixed_points,
            sl_min_points=float(self.settings.risk_cfg().get("stops", {}).get("sl_min_points", 150)),
            sl_max_points=float(self.settings.risk_cfg().get("stops", {}).get("sl_max_points", 1200)),
            min_rr_net=self.risk.limits().min_reward_risk,
            closes_pct=list(self.settings.risk_cfg().get("targets", {}).get("ladder", {}).get("closes_pct", [40, 30, 30])),
        ))
        if result.plan is None:
            return None, "; ".join(result.blockers)
        import hashlib as _hashlib

        sig_id = f"M{int(self.market.now())}-{_hashlib.sha1(f'{symbol}{entry_price}'.encode()).hexdigest()[:6]}"
        signal = Signal(
            id=sig_id, t=int(self.market.now()), symbol=symbol, timeframe=ctx.snapshot.timeframe,
            broker_id=self.adapter.id,
            action=SignalAction.buy if direction == Direction.up else SignalAction.sell,
            status=SignalStatus.valid, score=0.0, strategy="manual", regime="manual",
            reasons=[f"manual {'buy' if direction == Direction.up else 'sell'} requested by the user",
                     *result.notes],
            blockers=[], plan=result.plan, mode=self.mode, approval_required=False,
            expires_at=int(self.market.now()) + 120,
            explanation={"manual": True, "plan_notes": result.notes},
        )
        with self.lock:
            self.plans[sig_id] = signal
            self.signal_log.append(signal)
        return signal, ""

    def execute_signal(self, signal_id: str, actor: str = "user") -> dict[str, Any]:
        signal = self.plans.get(signal_id)
        if signal is None:
            row = self.db.query_one("SELECT payload FROM signals WHERE id = ?", (signal_id,))
            if row:
                signal = Signal(**json.loads(row["payload"]))
                with self.lock:
                    self.plans[signal_id] = signal
        if signal is None:
            return {"ok": False, "error": "signal not found"}
        if signal.plan is None:
            return {"ok": False, "error": "signal has no trade plan"}
        if signal.executed_order_id:
            return {"ok": False, "error": "signal already executed", "order_id": signal.executed_order_id}
        now = self.market.now()
        if signal.expires_at and now > signal.expires_at:
            return {"ok": False, "error": "signal expired — wait for a fresh one"}
        if signal.action not in (SignalAction.buy, SignalAction.sell):
            return {"ok": False, "error": "signal is not actionable"}
        # A hand-approval must not lower the bar the signal was generated against:
        # anything under the execution threshold is weak by the strategy's own rule,
        # and the risk gate only enforces the score floor in full-auto mode.
        min_score = float(getattr(self.strategy, "scoring", {}).get("min_score_to_execute", 70))
        if signal.score < min_score:
            return {"ok": False,
                    "error": (f"signal score {signal.score:.0f} is below the {min_score:.0f} "
                              "execution threshold — it cannot be approved by hand"),
                    "blockers": [f"score {signal.score:.0f} < {min_score:.0f}"]}

        try:
            risk_state = self.risk.state(self.adapter, now=now)
            tick = self.market.ticker(signal.symbol)
            spec = self.adapter.symbol_spec(signal.symbol)
            with self.lock:
                ctx = self.contexts.get(signal.symbol)
            quality = (ctx.snapshot.data_quality if ctx else self.market.data_quality(signal.symbol))
            news_lock = (ctx.snapshot.news_lockout if ctx else self.news.lockout(now))
            atr_pct = (ctx.snapshot.indicators.atr14 / ctx.snapshot.price * 100) if ctx else 0.0
            gate = self.strategy.evaluate_gate(signal, spec, tick, risk_state, quality, news_lock,
                                              self.adapter.health(), self.predictor.approved, atr_pct)
            if not gate.allow:
                return {"ok": False, "error": "risk gate rejected the order", "blockers": gate.blockers}
            request = OrderRequest(
                symbol=signal.symbol,
                side=OrderSide.buy if signal.action == SignalAction.buy else OrderSide.sell,
                volume=signal.plan.lot,
                sl=signal.plan.sl,
                tp=signal.plan.tp3,
                comment=f"No7 {signal.strategy}"[:26],
                signal_id=signal.id,
                idempotency_key=f"sig-{signal.id}",
                mode=self.mode,
                broker_id=self.adapter.id,
            )
            result: OrderResult = self.gateway.submit(self.adapter, request, actor=actor)
        except BrokerError as exc:
            return {"ok": False, "error": str(exc)}
        if result.status == OrderState.filled:
            # Slippage moves the fill away from the plan's entry while SL stays
            # where the structure put it, so the money at risk at the fill is not
            # necessarily the money the lot size was computed for. Say so loudly.
            fill_check = self._check_fill_risk(signal, result, spec)
            signal.executed_order_id = result.order_id
            signal.approved_by = actor
            signal.approved_at = int(now)
            self.db.execute(
                "INSERT OR REPLACE INTO signals(id, t, symbol, action, score, payload) VALUES(?,?,?,?,?,?)",
                (signal.id, signal.t, signal.symbol, signal.action.value, signal.score,
                 json.dumps(signal.model_dump(), default=str)))
            self.notifier.emit(
                "success", f"Order filled: {signal.action.value} {signal.symbol}",
                f"{signal.plan.lot} lot at {result.fill_price} | SL {signal.plan.sl:.2f} | "
                f"TP3 {signal.plan.tp3:.2f} | order {result.order_id}", symbol=signal.symbol,
                meta={"ticket": result.ticket, "signal_id": signal.id}, dedupe_seconds=0)
            with self.lock:
                self.version += 1
            return {"ok": True, "order": result.model_dump(), "signal": signal.id,
                    "risk_check": fill_check}
        return {"ok": False, "error": result.message or "order not filled", "order": result.model_dump()}

    def _check_fill_risk(self, signal: Signal, result: OrderResult, spec: Any) -> dict[str, Any]:
        """Compare the risk implied by the real fill with the planned budget."""
        plan = signal.plan
        fill = float(result.fill_price or 0.0)
        if plan is None or fill <= 0:
            return {"ok": True, "note": "no fill price to check"}
        actual_points = abs(fill - plan.sl) / spec.point if spec.point else 0.0
        actual_risk = actual_points * spec.value_per_point_per_lot * (result.filled_volume or plan.lot)
        planned = plan.risk_amount or 0.0
        drift = (actual_risk / planned - 1.0) * 100 if planned > 0 else 0.0
        planned_points = float(plan.sl_points or 0.0)
        geometry_broken = planned_points > 0 and actual_points < planned_points * 0.5
        payload = {
            "ok": actual_risk <= planned * 1.25 + 1e-9 and not geometry_broken,
            "planned_risk": round(planned, 2),
            "actual_risk": round(actual_risk, 2),
            "planned_sl_points": round(planned_points, 0),
            "actual_sl_points": round(actual_points, 0),
            "drift_pct": round(drift, 1),
            "geometry_broken": geometry_broken,
            "slippage_points": getattr(result, "slippage_points", 0.0),
        }
        if geometry_broken:
            self.notifier.emit(
                "critical", "Fill landed next to the stop",
                f"Stop is now only {actual_points:.0f} pts away (plan {planned_points:.0f} pts). "
                f"The trade no longer has the planned room — review or close it.",
                symbol=signal.symbol, dedupe_seconds=0)
        elif not payload["ok"]:
            self.notifier.emit(
                "warning", "Fill moved the stop further than planned",
                f"Risk now ${actual_risk:.2f} vs ${planned:.2f} planned "
                f"({drift:+.0f}%). Check the position before it runs.",
                symbol=signal.symbol, dedupe_seconds=0)
        self.db.audit("risk-engine", "risk.fill_drift", payload)
        return payload

    def reject_signal(self, signal_id: str, reason: str = "rejected by user") -> dict[str, Any]:
        signal = self.plans.get(signal_id)
        if signal is None:
            return {"ok": False, "error": "signal not found"}
        signal.rejected_reason = reason
        signal.action = SignalAction.wait
        self.db.audit("user", "signal.reject", {"signal_id": signal_id, "reason": reason})
        return {"ok": True}

    def manual_trade(self, symbol: str, direction: Direction, actor: str = "user") -> dict[str, Any]:
        signal, error = self.build_manual_plan(symbol, direction)
        if signal is None:
            return {"ok": False, "error": error or "could not build a valid plan"}
        return self.execute_signal(signal.id, actor=actor)

    def close_ticket(self, ticket: str, volume: float | None = None) -> dict[str, Any]:
        return self.gateway.close(self.adapter, ticket, volume=volume, reason="manual close", actor="user")

    def close_all(self) -> dict[str, Any]:
        closed = []
        for pos in self.adapter.positions():
            result = self.gateway.close(self.adapter, pos.ticket, reason="emergency close", actor="user")
            closed.append({"ticket": pos.ticket, "ok": bool(result.get("ok")),
                           "trade": result.get("trade"), "order": result.get("order")})
        if closed:
            self.notifier.emit("critical", "Emergency close executed",
                               f"{len(closed)} position(s) flattened on request.", dedupe_seconds=0)
        return {"ok": True, "closed": closed}

    def set_mode(self, mode: TradeMode, actor: str = "user") -> dict[str, Any]:
        try:
            self.mode = self.risk.set_mode(mode, actor)
        except PermissionError as exc:
            return {"ok": False, "error": str(exc)}
        self.notifier.emit("info", f"Trading mode changed to {mode.value}",
                           "Signals will follow the new execution policy.", dedupe_seconds=0)
        with self.lock:
            self.version += 1
        return {"ok": True, "mode": self.mode.value}

    # ------------------------------------------------------------ reconcile
    def _reconcile_cycle(self) -> None:
        try:
            self.last_reconcile = self.gateway.reconcile(self.adapter)
        except Exception as exc:  # noqa: BLE001
            self._log_error("reconcile", exc)

    def _record_equity(self) -> None:
        now = time.time()
        if now - getattr(self, "_last_equity_at", 0) < 5:
            return
        self._last_equity_at = now
        try:
            info = self.adapter.account_info()
        except Exception:  # noqa: BLE001
            return
        self.db.record_equity(self.market.now(), info.balance, info.equity, f"mode={self.mode.value}")
        with self.lock:
            self.version += 1

    # --------------------------------------------------------------- training
    def train_async(self, symbol: str, force: bool = False) -> dict[str, Any]:
        if self.training.get("state") == "running":
            return {"ok": False, "error": "training already running"}
        if not force and self.predictor.models and self.predictor.approved:
            return {"ok": False, "error": "an approved model is already active; pass force=true to retrain"}

        def worker() -> None:
            self.training = {"state": "running", "message": "preparing data", "pct": 0.0, "version": None}
            try:
                m1 = self.feed.warm_history(symbol, len(self.feed.warm_history(symbol, 10 ** 9)))
                version = self.model_registry.new_version("no7-lgbm")

                def progress(message: str, pct: float) -> None:
                    self.training = {"state": "running", "message": message, "pct": round(pct * 100, 1),
                                     "version": version}

                result = self.trainer.train(m1, version, progress)
                self.model_registry.save(result, symbol, activate=result.approved)
                # Install regardless: the predictor only uses horizons that passed their
                # own out-of-sample gate, and labels the rest as baseline.
                self.predictor.install_payload({
                    "version": result.version, "symbol": symbol, "models": result.models,
                    "feature_columns": result.feature_columns, "trained_at": result.trained_at,
                    "metrics": result.metrics, "approved": result.approved, "notes": result.notes,
                }, result.path_table.arrays())
                self.model_approved = bool(result.approved)
                self.training = {
                    "state": "done", "message": result.notes, "pct": 100.0, "version": version,
                    "approved": result.approved, "metrics": result.metrics,
                }
                self.notifier.emit(
                    "success" if result.approved else "warning",
                    f"Model training finished ({result.version})",
                    result.notes + ("" if result.approved else " The baseline forecast stays active."),
                    dedupe_seconds=0)
            except Exception as exc:  # noqa: BLE001
                self._log_error("training", exc)
                self.training = {"state": "error", "message": str(exc), "pct": 0.0, "version": None}

        threading.Thread(target=worker, name="no7-training", daemon=True).start()
        return {"ok": True, "state": "started"}

    # ---------------------------------------------------------------- payload
    def account(self) -> dict[str, Any]:
        try:
            return self.adapter.account_info().model_dump()
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc), "broker_id": self.adapter.id}

    def risk_state(self) -> Any:
        try:
            return self.risk.state(self.adapter, now=self.market.now())
        except Exception:  # noqa: BLE001
            return default_risk_state(0.0)

    def live_payload(self, light: bool = False) -> dict[str, Any]:
        symbol = self.active_symbol
        with self.lock:
            snapshot = self.contexts.get(symbol)
            forecast = self.forecasts.get(symbol)
            signal = self.signals.get(symbol)
            gate = self.gates.get(symbol)
            positions = list(self.positions_cache)
            ticks = dict(self.ticks)
            version = self.version
            errors = list(self.errors)[-3:]
            training = dict(self.training)
        payload: dict[str, Any] = {
            "server_time": time.time(),
            "virtual_time": self.market.now(),
            "version": version,
            "symbol": symbol,
            "mode": self.mode.value,
            "account": self.account(),
            "risk_state": self.risk_state().model_dump(),
            "limits": self.risk.limits().model_dump(),
            "ticker": (ticks.get(symbol).model_dump() if ticks.get(symbol) else
                       self.market.ticker(symbol).model_dump()),
            "positions": [p.model_dump() for p in positions],
            "signal": signal.model_dump() if signal else None,
            "gate": gate,
            "model": {
                "version": self.predictor.version,
                "approved": self.predictor.approved,
                "metrics": self.predictor.metrics.get("horizons", {}),
                "trained_at": self.predictor.trained_at,
                "notes": self.predictor.notes,
            },
            "training": training,
            "reconcile": self.last_reconcile,
            "errors": errors,
            "feed": "simulated" if self.adapter.adapter_type == "simulated_mt5" else "mt5",
            "alerts": self.notifier.recent(8),
        }
        if not light:
            payload["analysis"] = snapshot.snapshot.model_dump() if snapshot else None
            payload["forecast"] = forecast.model_dump() if forecast else None
        return payload

    def health(self) -> dict[str, Any]:
        services = {
            "db": "ok",
            "feed": "ok" if (time.time() - self.last_tick_at) < 10 else "stale",
            "runtime": "running" if self._thread and self._thread.is_alive() else "stopped",
            "model": "approved" if self.predictor.approved else "baseline",
            "training": self.training.get("state", "idle"),
        }
        return {
            "status": "ok" if services["runtime"] == "running" else "degraded",
            "version": self.settings.app.get("app", {}).get("version", "V1"),
            "env": self.settings.env,
            "server_time": time.time(),
            "virtual_time": self.market.now(),
            "uptime_seconds": round(time.time() - self.started_at, 1),
            "feed_mode": self.settings.market_data.get("feed_mode", "simulate"),
            "broker_health": self.registry.health_map(),
            "model": self.predictor.status().model_dump() if self.predictor.status() else None,
            "services": services,
        }

    # ------------------------------------------------------------------ misc
    def snapshot(self, symbol: str) -> AnalysisSnapshot | None:
        with self.lock:
            ctx = self.contexts.get(symbol)
        return ctx.snapshot if ctx else None

    def forecast_for(self, symbol: str) -> ForecastBundle | None:
        with self.lock:
            cached = self.forecasts.get(symbol)
        if cached:
            return cached
        try:
            ctx = self.analysis.snapshot(symbol)
            bundle = self.predictor.forecast(ctx.frames["M5"], ctx.snapshot.spec, symbol)
            with self.lock:
                self.contexts[symbol] = ctx
                self.forecasts[symbol] = bundle
            return bundle
        except Exception:  # noqa: BLE001
            return None

    def ensure_analysis(self, symbol: str) -> AnalysisContext:
        with self.lock:
            ctx = self.contexts.get(symbol)
        if ctx is not None:
            return ctx
        ctx = self.analysis.snapshot(symbol)
        with self.lock:
            self.contexts[symbol] = ctx
        return ctx

    def switch_symbol(self, symbol: str) -> None:
        if symbol in self.symbols():
            self.active_symbol = symbol
            with self.lock:
                self.version += 1

    def sign_strength(self) -> str:
        sig = self.signals.get(self.active_symbol)
        return sig.status.value if sig else "none"

    def alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.notifier.recent(limit)
