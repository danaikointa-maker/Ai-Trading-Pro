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
import os
import socket
import threading
import time
import traceback
from collections import deque
from typing import Any

from integrations.brokers.base import BrokerAdapter, BrokerError
from integrations.brokers.registry import BrokerRegistry
from services.bridge.relay import BridgeRelay
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
from services.api_gateway.cluster import (LIVE_KEY, build_shared_state, decide_role,
                                          replica_payload)
from services.ai_forecast.predictor import ForecastPredictor
from services.ai_forecast.registry import ModelRegistry
from services.ai_forecast.trainer import ForecastTrainer
from services.execution_gateway.gateway import ExecutionGateway
from services.market_data.news import NewsService
from services.market_data.service import MarketDataService
from services.market_data.replay import build_feed
from services.notification.notifier import Notifier
from services.risk_engine.engine import RiskEngine, default_risk_state
from services.risk_engine.manager import PositionAction, PositionManager
from services.risk_engine.planner import PlanInputs, TradePlanner
from services.strategy_engine.analysis import AnalysisContext, AnalysisService
from services.strategy_engine.attribution import BlockerTally, merge
from services.strategy_engine.engine import StrategyEngine

def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


LEASE_KEY = "runtime_lease"
LEASE_STALE_SECONDS = 30.0


def lease_owner() -> str:
    """Identify this process in the lease record."""
    return f"{socket.gethostname()}#{os.getpid()}"


def claim_runtime_lease(db: Any, owner: str, now: float | None = None,
                        stale_seconds: float = LEASE_STALE_SECONDS,
                        force: bool = False) -> tuple[bool, dict[str, Any]]:
    """Take the single-writer lease on the trading runtime.

    Only one process may drive ticks, decisions and orders against a database:
    two runtimes would each see the same signal and each send their own order.
    A lease whose heartbeat is older than ``stale_seconds`` is treated as a
    crashed process and taken over, so a hard kill cannot lock the system out.
    """
    now = time.time() if now is None else float(now)
    current = db.kv_get(LEASE_KEY, {}) or {}
    other = current.get("owner")
    beat = float(current.get("heartbeat") or 0)
    age = (now - beat) if beat else None
    if other and other != owner and age is not None and age < stale_seconds and not force:
        return False, {
            "state": "blocked",
            "owner": other,
            "heartbeat_age_seconds": round(age, 1),
            "blocked_owner": owner,
        }
    started = float(current.get("started_at") or now) if other == owner else now
    record = {
        "state": "shared" if (force and other and other != owner) else "held",
        "owner": owner,
        "heartbeat": now,
        "started_at": started,
    }

    if force:
        # An operator explicitly opted into sharing; the guard below would (correctly)
        # refuse to overwrite a live owner, so this path is a plain write.
        db.kv_set(LEASE_KEY, record)
        return True, dict(record)

    # Compare-and-set in one statement. A read-then-write let two processes that
    # started in the same instant both see a stale lease and both become leader —
    # which means two trading loops. The UPDATE only applies while the condition
    # still holds, so exactly one caller can win.
    written = db.execute(
        "INSERT INTO kv(key, value, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at "
        "WHERE json_extract(kv.value, '$.owner') = ? "
        "   OR CAST(COALESCE(json_extract(kv.value, '$.heartbeat'), 0) AS REAL) <= ?",
        (LEASE_KEY, json.dumps(record), now, owner, now - stale_seconds),
    )
    if not written:
        fresh = db.kv_get(LEASE_KEY, {}) or {}
        fresh_owner = fresh.get("owner", other)
        fresh_age = now - float(fresh.get("heartbeat") or 0)
        return False, {
            "state": "blocked",
            "owner": fresh_owner,
            "heartbeat_age_seconds": round(max(0.0, fresh_age), 1),
            "blocked_owner": owner,
            "raced": True,
        }
    return True, dict(record)


def heartbeat_lease(db: Any, owner: str, now: float | None = None) -> dict[str, Any]:
    """Refresh the heartbeat, reporting ``lost`` if another process took over."""
    now = time.time() if now is None else float(now)
    current = db.kv_get(LEASE_KEY, {}) or {}
    if current.get("owner") and current.get("owner") != owner:
        return {"state": "lost", "owner": current.get("owner")}
    record = {**current, "state": "held", "owner": owner, "heartbeat": now}
    db.kv_set(LEASE_KEY, record)
    return dict(record)


def release_runtime_lease(db: Any, owner: str) -> tuple[bool, dict[str, Any]]:
    """Release the lease if this process holds it; never touch another owner's."""
    current = db.kv_get(LEASE_KEY, {}) or {}
    if current.get("owner") != owner:
        return False, current
    record = {"state": "released", "owner": owner, "heartbeat": 0.0,
              "started_at": current.get("started_at")}
    db.kv_set(LEASE_KEY, record)
    return True, record


def build_bridge_relay(settings: Settings, audit=None, db=None) -> BridgeRelay:
    """Relay configured from `bridge:` in app.yaml (empty tokens disable accounts).

    With a database the relay keeps its session/queue in the shared `bridge_*` tables:
    the EA's poll can land on any worker, so per-process state would lose the leader's
    orders and let the EA flap between workers.
    """
    cfg = dict(settings.app.get("bridge") or {})
    accounts = {str(row.get("id")): str(row.get("token") or "")
                for row in (cfg.get("accounts") or []) if row.get("id")}
    relay = BridgeRelay(
        {k: v for k, v in accounts.items() if v},
        fresh_seconds=float(cfg.get("fresh_seconds", 5)),
        stale_seconds=float(cfg.get("stale_seconds", 15)),
        command_ttl_seconds=float(cfg.get("command_ttl_seconds", 30)),
        ack_grace_seconds=float(cfg.get("ack_grace_seconds", 20)),
        max_pending=int(cfg.get("max_pending", 50)),
        poll_interval_ms=int(cfg.get("poll_interval_ms", 1000)),
        order_timeout_seconds=float(cfg.get("order_timeout_seconds", 20)),
        enabled=bool(cfg.get("enabled", False)),
        db=db,
    )
    if audit is not None:
        relay.audit = audit
    return relay


class TradingRuntime:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.db = Database(self.settings.database_path)
        # --- market data: union of symbols from every simulated broker profile
        symbols: dict[str, dict[str, Any]] = {}
        for profile in self.settings.brokers.get("brokers", []):
            if profile.get("adapter") in ("simulated_mt5", "paper"):
                for symbol, spec in (profile.get("symbols") or {}).items():
                    symbols.setdefault(symbol, spec)
        # feed_mode decides what the whole platform reads. A replay that cannot
        # start falls back to the simulator and records why, so health can never
        # present simulated prices as if they were imported ones.
        active_broker = self.settings.default_broker_id()
        self.feed, self.feed_mode, self.feed_note = build_feed(
            self.settings,
            symbols or {"XAUUSD": self.settings.symbol_spec(active_broker, "XAUUSD")},
            required=list(self.settings.broker_symbols(active_broker)))
        if self.feed_note:
            self.settings.app.setdefault("_feed_notes", []).append(self.feed_note)
        self.db.kv_set("virtual_clock_start", self.feed.end_time)

        self.bridge = build_bridge_relay(self.settings, audit=self.db.audit, db=self.db)
        self.registry = BrokerRegistry(self.settings, self.feed, relay=self.bridge)
        self.registry.build()
        for adapter in self.registry.all():
            if hasattr(adapter, "clock"):
                adapter.clock = lambda: self.feed.end_time  # type: ignore[attr-defined]

        self.news = NewsService(self.db, high_impact_currencies=["USD"], now=self.feed.end_time)
        self.market = MarketDataService(self.settings, self.registry, self.news)
        self.market.set_virtual_now(self.feed.end_time)
        self.market.feed_mode = self.feed_mode

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
                                                          .get("scoring", {}).get("thresholds", {}).get("weak", 50)),
                                 cfg=self.settings.alerts)
        self.trainer = ForecastTrainer(self.settings)

        # --- runtime state
        self.lock = threading.RLock()
        self.contexts: dict[str, AnalysisContext] = {}
        self.forecasts: dict[str, ForecastBundle] = {}
        self.signals: dict[str, Signal] = {}
        self.signal_log: deque[Signal] = deque(maxlen=400)
        self.plans: dict[str, Signal] = {}
        self.gates: dict[str, dict[str, Any]] = {}
        # Why the live engine is not trading, counted per symbol by reason code.
        # The dashboard could already show the *last* decision; nobody could see
        # that, say, 95% of today's decisions died on one condition.
        self.attribution: dict[str, BlockerTally] = {}
        self.attribution_since = time.time()
        self.positions_cache: list[Position] = []
        self.ticks: dict[str, Tick] = {}
        self.version = 0
        self.started_at = time.time()
        self.last_decision_at = 0.0
        self.last_tick_at = 0.0
        self.last_tick_wall = time.time()
        self.last_reconcile: dict[str, Any] = {}
        self.errors: deque[dict[str, Any]] = deque(maxlen=25)
        self.mode = self.risk.record_mode()
        self.model_approved = bool(self.predictor.approved)
        self.training: dict[str, Any] = {"state": "idle", "message": "", "pct": 0.0, "version": None}
        self._owner = lease_owner()
        self.lease: dict[str, Any] = {"state": "unclaimed", "owner": self._owner}
        self._standby: threading.Thread | None = None
        self.shared, self.shared_status = build_shared_state(self.settings)
        self.replica = False
        self._replica_frame: dict[str, Any] | None = None
        self._last_publish = 0.0
        self._lease_last_beat = 0.0
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
        if not self._claim_lease():
            self._start_standby()
            return
        # Run one cycle inline: the dashboard's very first paint then has a
        # snapshot/forecast instead of an empty card that fills in seconds later.
        self.prime()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="no7-runtime", daemon=True)
        self._thread.start()
        if self.settings.ai.get("training", {}).get("auto_train_on_boot", True):
            self.train_async(self.active_symbol)

    def _claim_lease(self) -> bool:
        """Take the single-writer lease, or refuse to trade from this process.

        Refusing is deliberate: a second runtime on the same database would
        duplicate ticks, signals and — with Full Auto on — real orders. The API
        still boots so the dashboard and `/api/system/health` can explain why
        nothing is moving.
        """
        force = _truthy(os.getenv("NO7_ALLOW_MULTI_RUNTIME", ""))
        ok, record = claim_runtime_lease(self.db, self._owner, force=force)
        self.lease = record
        self._lease_last_beat = time.time()
        if ok:
            if record.get("state") == "shared":
                self._log_error("runtime-lease", RuntimeError(
                    "NO7_ALLOW_MULTI_RUNTIME is set: more than one runtime is driving this "
                    "database. Signals and orders may be duplicated."))
            return True
        frame = replica_payload(self.shared)
        self.replica = bool(frame) and self.shared_status.get("backend") != "local"
        self._log_error("runtime-lease", RuntimeError(
            f"another No7 runtime already owns this database ({record.get('owner')}, "
            f"heartbeat {record.get('heartbeat_age_seconds')}s ago). "
            + ("Serving its live frames as a read-only replica — this process will not trade."
               if self.replica else
               "Not starting the trading loop here, and there is no shared backend to read "
               "from — run one instance only.")))
        return False

    def _maybe_heartbeat(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        if now - self._lease_last_beat < 5.0:
            return
        self._lease_last_beat = now
        self.lease = heartbeat_lease(self.db, self._owner, now)

    # ------------------------------------------------------------ hot standby
    def try_promote(self) -> bool:
        """Take over from a leader that stopped breathing (atomic lease claim).

        A standby is a full runtime that simply never started its loop, so
        promotion is "claim the lease and start ticking" — no re-initialisation and
        no chance of two winners, because the claim is a compare-and-set.
        """
        if self._stop.is_set():
            return False
        if self.lease.get("state") in ("held", "shared") and not self.replica:
            return False
        ok, record = claim_runtime_lease(self.db, self._owner)
        if not ok:
            self.lease = record
            return False
        self.lease = record
        self.replica = False
        self._log_error("runtime-lease", RuntimeError(
            f"promoted to leader ({record.get('state')}) — the previous runtime stopped "
            f"sending heartbeats. This process now drives trading."))
        self.start()
        return True

    def _start_standby(self) -> None:
        """Poll for a dead leader while this process waits in the background."""
        if not bool(self.settings.cluster.get("hot_standby", True)):
            return
        if self._standby and self._standby.is_alive():
            return
        interval = float(self.settings.cluster.get("standby_poll_seconds", 5) or 5)

        def watch() -> None:
            while not self._stop.wait(max(0.2, interval)):
                try:
                    if self.try_promote():
                        return
                except Exception as exc:  # noqa: BLE001 - a standby must not crash
                    self._log_error("runtime-lease", exc)

        self._standby = threading.Thread(target=watch, name="no7-standby", daemon=True)
        self._standby.start()

    def _maybe_publish(self, now: float | None = None) -> None:
        """Publish this leader's live frame for any replicas (once a second)."""
        now = time.time() if now is None else now
        if now - self._last_publish < 1.0:
            return
        self._last_publish = now
        try:
            self.shared.publish(LIVE_KEY, {"owner": self._owner, "published_at": now,
                                           "payload": self.live_payload()})
        except Exception as exc:  # noqa: BLE001 - the shared backend must not stop trading
            self._log_error("cluster", exc)

    def role(self) -> str:
        frame = self._replica_frame if self.replica else None
        try:
            has_frame = bool(frame) or bool(replica_payload(self.shared))
        except Exception:  # noqa: BLE001 - a broken backend must not 500 the health page
            has_frame = bool(frame)
        return decide_role(self.lease.get("state", "unclaimed"),
                           str(self.shared_status.get("backend", "local")), has_frame)

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
        if self._standby:
            self._standby.join(timeout=2)
        try:
            self.shared.close()
        except Exception:  # noqa: BLE001 - shutdown must not raise
            pass
        try:
            released, record = release_runtime_lease(self.db, self._owner)
            self.lease = {**record, "state": "released" if released else self.lease.get("state")}
        except Exception:  # noqa: BLE001 - shutdown must not raise
            pass

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
                self._maybe_heartbeat(now)
                self._maybe_publish(now)
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
            # The loop's heartbeat is measured on the wall clock: a replayed series
            # lives in the past, so comparing virtual time to time.time() called a
            # healthy feed stale.
            self.last_tick_wall = time.time()
        for adapter in self.registry.all():
            try:
                closed = adapter.on_tick(ticks)
            except Exception as exc:  # noqa: BLE001
                self._log_error(f"adapter:{adapter.id}", exc)
                continue
            for trade in closed:
                self._on_trade_closed(trade)
        self._manage_cycle(now)
        self._drain_notify_outbox()
        self.version += 1

    # A backlog must clear even when nothing new is happening — an outage that
    # ends quietly should not leave alerts sitting in the queue until the next
    # trade. The drain itself runs on its own thread (see `Notifier.drain_async`):
    # a queued message may be pointed at a host that never answers, and blocking
    # the trading loop on socket timeouts would be the worse bug by far.
    OUTBOX_DRAIN_SECONDS = 15.0

    def _drain_notify_outbox(self) -> None:
        now = time.time()
        if now - getattr(self, "_last_outbox_drain", 0.0) < self.OUTBOX_DRAIN_SECONDS:
            return
        self._last_outbox_drain = now
        try:
            if self.notifier.outbox.pending():
                self.notifier.drain_async()
        except Exception as exc:  # noqa: BLE001 - never let the queue break the loop
            self._log_error("notify-outbox", exc)

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
        # Count before the lines below rewrite the signal: once a gate rejection
        # has turned a buy into a `wait` and merged the gate's prose into
        # `signal.blockers`, the decision can no longer be told apart from one
        # that never had a trade in it.
        tradable = (signal.action in (SignalAction.buy, SignalAction.sell)
                    and signal.plan is not None)
        with self.lock:
            tally = self.attribution.get(symbol)
            if tally is None:
                tally = self.attribution[symbol] = BlockerTally()
            tally.add_signal(tradable, signal.blocker_codes, signal.blockers)
            # The gate is consulted on every live decision, but counting it on
            # decisions that had nothing to trade anyway would bury the cases
            # that matter. Only signals that asked to trade are counted, which
            # is also the basis the backtest uses — so the two are comparable.
            if tradable:
                tally.add_gate(gate.allow, gate.checks)

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

    def attribution_summary(self, symbol: str | None = None) -> dict[str, Any]:
        """Why the live engine has or has not been trading since `since`.

        Counted on live decisions only. A backtest answers the same question for
        a historical sample; this answers it for the session that is running, so
        an operator watching a quiet dashboard can tell "nothing qualifies" from
        "one gate has been rejecting everything for an hour".
        """
        with self.lock:
            tallies = dict(self.attribution)
            since = self.attribution_since
        if symbol:
            chosen = {symbol: tallies[symbol]} if symbol in tallies else {}
        else:
            chosen = tallies
        overall = merge(chosen.values()) if chosen else BlockerTally()
        return {
            "since": since,
            "window_seconds": round(max(0.0, time.time() - since), 1),
            "symbols": sorted(chosen),
            "overall": overall.summary(),
            "per_symbol": {sym: t.summary() for sym, t in sorted(chosen.items())},
            "headline": overall.note(),
        }

    def reset_attribution(self) -> None:
        """Start a fresh window — e.g. after changing a threshold."""
        with self.lock:
            self.attribution.clear()
            self.attribution_since = time.time()

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
        if self.replica:
            frame = replica_payload(self.shared)
            if frame is not None:
                self._replica_frame = frame
                return frame
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
                # `metrics` stays the per-horizon map the dashboard iterates; the
                # approval rule that judged it travels beside it so the UI can say
                # *why* a horizon failed instead of only that it did.
                "metrics": self.predictor.metrics.get("horizons", {}),
                "validation": self.predictor.metrics.get("validation"),
                "approval_rule": self.predictor.metrics.get("approval_rule"),
                "min_validation_folds": self.predictor.metrics.get("min_validation_folds"),
                "min_fold_pass_rate": self.predictor.metrics.get("min_fold_pass_rate"),
                "trained_at": self.predictor.trained_at,
                "notes": self.predictor.notes,
            },
            "training": training,
            "reconcile": self.last_reconcile,
            "errors": errors,
            "feed": getattr(self, "feed_mode", None)
            or ("simulated" if self.adapter.adapter_type == "simulated_mt5" else "mt5"),
            "alerts": self.notifier.recent(8),
        }
        if not light:
            payload["analysis"] = snapshot.snapshot.model_dump() if snapshot else None
            payload["forecast"] = forecast.model_dump() if forecast else None
        return payload

    def health(self) -> dict[str, Any]:
        exhausted = bool(getattr(self.feed, "exhausted", False))
        services = {
            "db": "ok",
            "feed": "exhausted" if exhausted else (
                "ok" if (time.time() - self.last_tick_wall) < 10 else "stale"),
            "runtime": "running" if self._thread and self._thread.is_alive() else "stopped",
            "model": "approved" if self.predictor.approved else "baseline",
            "training": self.training.get("state", "idle"),
            "notify": self.notifier.status()["state"],
        }
        lease_state = self.lease.get("state", "unclaimed")
        role = self.role()
        if self.replica:
            services["runtime"] = "replica (read-only, serving the leader's frames)"
        elif lease_state in ("blocked", "lost"):
            services["runtime"] = f"blocked ({lease_state})"
            services["lease"] = lease_state
        return {
            "status": "ok" if (services["runtime"] == "running" or self.replica) else "degraded",
            "version": self.settings.app.get("app", {}).get("version", "V1"),
            "env": self.settings.env,
            "server_time": time.time(),
            "virtual_time": self.market.now(),
            "uptime_seconds": round(time.time() - self.started_at, 1),
            "feed_mode": getattr(self, "feed_mode", None)
            or self.settings.market_data.get("feed_mode", "simulate"),
            "feed_note": getattr(self, "feed_note", None),
            "feed": self._feed_status(),
            "broker_health": self.registry.health_map(),
            "model": self.predictor.status().model_dump() if self.predictor.status() else None,
            "services": services,
            "notify": self.notifier.status(),
            "security": self._security_status(),
            "ratelimit": self._ratelimit_status(),
            "websockets": self._websocket_status(),
            "cluster": {**self.shared_status, "role": role,
                        "shared_health": self.shared.healthy()},
            "runtime_lease": {**self.lease,
                              "heartbeat_age_seconds": round(time.time() - float(self.lease.get("heartbeat") or 0), 1)
                              if self.lease.get("heartbeat") else None},
        }

    def _ratelimit_status(self) -> dict[str, Any]:
        """Which budget applies, and whether it is shared by other processes.

        A memory store under `uvicorn --workers N` hands out N budgets — the limit the
        operator configured is then an illusion. Saying so here is the difference
        between a limiter and a decoration.
        """
        base = dict(getattr(self, "ratelimit_status", {}) or {})
        backend = str(base.get("backend", "memory"))
        out = {
            "store": backend,
            "requested": base.get("requested", backend),
            "shared": bool(base.get("shared", backend in ("sqlite", "redis"))),
            "reason": base.get("reason", ""),
        }
        if base.get("path") and backend == "sqlite":
            out["path"] = base["path"]

        # The lines above describe the store chosen at boot. They would keep claiming
        # `shared: true` through an outage, so ask the limiter that is actually
        # enforcing right now: every spend it could not send to the shared store was
        # answered by this process's own bucket (and marked x-ratelimit-degraded).
        limiter = getattr(self, "ratelimit", None)
        live = limiter.status() if limiter is not None else {}
        degraded = int(live.get("degraded", 0) or 0)
        out["degraded"] = degraded
        if degraded:
            out["shared"] = False
            out["last_error"] = str(live.get("last_error", ""))
            out["warning"] = (f"the {backend} store failed {degraded} time(s); those requests "
                              "were limited against this process only, so the configured "
                              "limit is not shared right now (see x-ratelimit-degraded)")
        elif not out["shared"]:
            out["warning"] = ("store=memory: every worker process keeps its own budget, "
                              "so --workers N multiplies the configured limit. Use "
                              "store: sqlite (one host) or store: redis (several hosts).")
        return out

    def _websocket_status(self) -> dict[str, Any]:
        """Live socket capacity — the limit, how much of it is in use, and where it is kept.

        A WebSocket is not covered by the per-minute HTTP limits: it is one request
        that keeps costing CPU. This block exists so an operator can see the cap is
        real (and shared) instead of assuming it.
        """
        quota = getattr(self, "ws_quota", None)
        if quota is None:
            return {"enforced": False,
                    "reason": "no quota attached to this app (older boot path)"}
        out = {"enforced": True, **quota.status()}
        boot = dict(getattr(self, "ws_store_status", {}) or {})
        if boot.get("reason"):
            out["store_reason"] = boot["reason"]
        return out

    def _security_status(self) -> dict[str, Any]:
        """How the perimeter is configured right now — visible, not implied.

        Values are config, not secrets: an operator needs to see that TLS termination,
        the proxy list and the CORS allowlist are what they think they are. HSTS is
        reported as *possible* because it only applies to requests that arrive over
        HTTPS (see SecurityHeadersMiddleware).
        """
        sh = self.settings.security_headers
        origins = self.settings.cors_origins
        return {
            "require_auth": bool(self.settings.security.get("require_auth", True)),
            "jwt_secret_from_env": bool(os.environ.get("NO7_JWT_SECRET")),
            "cors": {"origins": origins, "wildcard": "*" in origins,
                     "cross_origin_allowed": bool(origins)},
            "trusted_proxies": self.settings.trusted_proxies,
            "csp_mode": sh.get("csp_mode", "enforce"),
            "hsts_when_https": bool(sh.get("hsts", True)),
        }

    def _feed_status(self) -> dict[str, Any]:
        describe = getattr(self.feed, "describe", None)
        if callable(describe):
            try:
                return describe()
            except Exception as exc:  # noqa: BLE001 - health must never raise
                return {"mode": getattr(self, "feed_mode", "?"), "error": str(exc)}
        return {"mode": getattr(self, "feed_mode", "simulate")}

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
