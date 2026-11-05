"""Risk engine: the layer that is allowed to say no.

The gate is deliberately boring and explicit: every blocker is a named rule with
a number attached so the dashboard can show *why* a trade was rejected instead
of a vague "AI says wait".
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from integrations.brokers.base import BrokerAdapter
from packages.persistence.db import Database
from packages.shared_schemas.models import (
    AccountInfo,
    Direction,
    Health,
    RiskLimits,
    RiskSettings,
    RiskState,
    SymbolSpec,
    TradeMode,
)
from packages.shared_schemas.settings import Settings


@dataclass
class RiskGate:
    allow: bool
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str, blocker: bool = True) -> None:
        self.checks.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            if blocker:
                self.blockers.append(detail)
            else:
                self.warnings.append(detail)
        if not ok and blocker:
            self.allow = False


class RiskEngine:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.tz = ZoneInfo(settings.risk_cfg().get("limits", {}).get("daily_reset_timezone", "Asia/Bangkok"))
        self._cached_limits: RiskLimits | None = None

    # --------------------------------------------------------------- config
    def limits(self) -> RiskLimits:
        if self._cached_limits is not None:
            return self._cached_limits
        raw = self.settings.risk_cfg().get("limits", {})
        base = RiskLimits(**{k: v for k, v in raw.items() if k in RiskLimits.model_fields})
        override = self.db.kv_get("risk_limits_override", {})
        if override:
            merged = base.model_dump()
            merged.update({k: v for k, v in override.items() if k in merged})
            base = RiskLimits(**merged)
        self._cached_limits = base
        return base

    def update_limits(self, patch: dict[str, Any], actor: str = "user") -> RiskLimits:
        current = self.limits().model_dump()
        for key, value in patch.items():
            if key not in current:
                continue
            if isinstance(current[key], int) and not isinstance(value, bool):
                value = int(value)
            elif isinstance(current[key], float):
                value = float(value)
            current[key] = value
        self.db.kv_set("risk_limits_override", current)
        self.db.audit(actor, "risk.limits.update", patch)
        self._cached_limits = RiskLimits(**current)
        return self._cached_limits

    def settings_view(self) -> RiskSettings:
        cfg = self.settings.risk_cfg()
        target_cfg = cfg.get("targets", {})
        lim = self.limits()
        return RiskSettings(
            limits=lim,
            targets_mode=target_cfg.get("mode", "adaptive"),
            fixed_points=list(target_cfg.get("fixed_points", [500, 750, 1000])),
            min_points=float(target_cfg.get("min_points", 500)),
            max_points=float(target_cfg.get("max_points", 1000)),
            sl_atr_multiplier=float(cfg.get("stops", {}).get("sl_atr_multiplier", 1.5)),
            full_auto_enabled=bool(self.db.kv_get("full_auto_enabled", False)),
            news_lockout_enabled=lim.news_lockout_enabled,
        )

    # ----------------------------------------------------------------- state
    def _day_start(self, now: float) -> int:
        dt = datetime.fromtimestamp(now, tz=self.tz).replace(hour=0, minute=0, second=0, microsecond=0)
        return int(dt.timestamp())

    def _week_start(self, now: float) -> int:
        dt = datetime.fromtimestamp(now, tz=self.tz)
        monday = dt - timedelta(days=dt.weekday())
        return int(monday.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())

    def state(self, adapter: BrokerAdapter, now: float | None = None) -> RiskState:
        now = now or time.time()
        info: AccountInfo = adapter.account_info()
        day_start, week_start = self._day_start(now), self._week_start(now)
        rows = self.db.query(
            "SELECT closed_at, pnl, exit_reason, opened_at FROM trades WHERE closed_at >= ? ORDER BY closed_at",
            (week_start,),
        )
        daily = [r for r in rows if r["closed_at"] >= day_start]
        daily_pnl = sum(float(r["pnl"] or 0) for r in daily)
        weekly_pnl = sum(float(r["pnl"] or 0) for r in rows)
        base_equity = info.equity - daily_pnl - sum(self._open_floating(adapter))
        daily_pct = (daily_pnl / base_equity * 100) if base_equity else 0.0
        weekly_pct = (weekly_pnl / base_equity * 100) if base_equity else 0.0

        peak = max(float(self.db.kv_get("peak_equity", info.equity) or info.equity), info.equity)
        self.db.kv_set("peak_equity", peak)
        drawdown = ((info.equity - peak) / peak * 100) if peak else 0.0

        closed = self.db.query(
            "SELECT pnl, closed_at FROM trades ORDER BY closed_at DESC LIMIT 12")
        consecutive = 0
        for row in closed:
            if float(row["pnl"] or 0) < 0:
                consecutive += 1
            else:
                break
        cooldown_until = None
        if (closed and float(closed[0]["pnl"] or 0) < 0
                and consecutive >= self.limits().max_consecutive_losses):
            cooldown_until = int(closed[0]["closed_at"] + self.limits().cooldown_minutes * 60)

        positions = adapter.positions()
        open_lots = sum(p.volume for p in positions)
        kill = self.db.kv_get("kill_switch", {"active": False, "reason": "", "since": 0})
        mode = TradeMode(self.db.kv_get("trade_mode", TradeMode.manual.value))

        state = RiskState(
            balance=info.balance,
            equity=info.equity,
            peak_equity=round(peak, 2),
            daily_pnl=round(daily_pnl, 2),
            daily_pnl_pct=round(daily_pct, 3),
            weekly_pnl=round(weekly_pnl, 2),
            weekly_pnl_pct=round(weekly_pct, 3),
            drawdown_pct=round(drawdown, 2),
            open_trades=len(positions),
            open_lots=round(open_lots, 2),
            exposure_pct=round(open_lots * 100000 / info.equity, 2) if info.equity else 0.0,
            consecutive_losses=consecutive,
            trades_today=len(daily),
            trades_this_week=len(rows),
            cooldown_until=cooldown_until,
            kill_switch_active=bool(kill.get("active")),
            kill_switch_reason=kill.get("reason", ""),
            max_trades_allowed=self.limits().max_open_trades,
            mode=mode,
            updated_at_virtual=now,
        )
        # Breach detection -> persistent kill switch (manual reset required).
        limits = self.limits()
        reason = ""
        if daily_pct <= -limits.max_daily_loss_pct:
            reason = f"daily loss {daily_pct:.2f}% breached the {limits.max_daily_loss_pct:.2f}% limit"
        elif drawdown <= -limits.max_drawdown_pct:
            reason = f"drawdown {drawdown:.2f}% breached the {limits.max_drawdown_pct:.2f}% limit"
        elif weekly_pct <= -limits.max_weekly_loss_pct:
            reason = f"weekly loss {weekly_pct:.2f}% breached the {limits.max_weekly_loss_pct:.2f}% limit"
        if reason and not state.kill_switch_active:
            self.engage_kill_switch(reason, now)
            state.kill_switch_active = True
            state.kill_switch_reason = reason
        return state

    def _open_floating(self, adapter: BrokerAdapter) -> list[float]:
        try:
            return [p.unrealized for p in adapter.positions()]
        except Exception:  # noqa: BLE001
            return []

    # ------------------------------------------------------------ kill switch
    def engage_kill_switch(self, reason: str, now: float | None = None) -> None:
        self.db.kv_set("kill_switch", {"active": True, "reason": reason, "since": now or time.time()})
        self.db.audit("risk-engine", "kill_switch.engage", {"reason": reason})

    def reset_kill_switch(self, actor: str = "user") -> None:
        self.db.kv_set("kill_switch", {"active": False, "reason": "", "since": 0})
        self.db.kv_set("peak_equity", None)
        self.db.audit(actor, "kill_switch.reset", {})

    def set_mode(self, mode: TradeMode, actor: str = "user") -> TradeMode:
        if mode == TradeMode.full_auto:
            allowed = (self.settings.security.get("allow_full_auto")
                       and self.db.kv_get("full_auto_enabled", False))
            if not allowed:
                raise PermissionError("full auto is locked: enable it in Risk settings and set "
                                      "NO7_ALLOW_FULL_AUTO=true on a demo account")
        self.db.kv_set("trade_mode", mode.value)
        self.db.audit(actor, "mode.change", {"mode": mode.value})
        return mode

    # ------------------------------------------------------------------ gate
    def gate(self, state: RiskState, spec: SymbolSpec, spread_points: float,
             data_quality: dict[str, Any], news_lockout: dict[str, Any], atr_pct: float,
             requested_lot: float = 0.0, broker_health: Health = Health.connected,
             now: float | None = None, is_full_auto: bool = False,
             signal_score: float = 0.0, calibrated_probability: float | None = None,
             model_approved: bool = False) -> RiskGate:
        now = now or time.time()
        limits = self.limits()
        gate = RiskGate(allow=True)

        gate.add("kill_switch", not state.kill_switch_active,
                 f"Kill switch active: {state.kill_switch_reason}" if state.kill_switch_active else "kill switch clear")
        gate.add("broker_health", broker_health in (Health.connected, Health.degraded),
                 f"broker is {broker_health.value}")
        gate.add("data_quality", bool(data_quality.get("ok")),
                 data_quality.get("reason") or f"feed ok (lag {data_quality.get('staleness_seconds')}s)")
        gate.add("spread", spread_points <= limits.max_spread_points,
                 f"spread {spread_points:.0f} pts exceeds max {limits.max_spread_points:.0f} pts")
        gate.add("max_open_trades", state.open_trades < limits.max_open_trades,
                 f"{state.open_trades} open trade(s); limit is {limits.max_open_trades}")
        gate.add("daily_loss", state.daily_pnl_pct > -limits.max_daily_loss_pct,
                 f"daily P&L {state.daily_pnl_pct:.2f}% has reached the -{limits.max_daily_loss_pct:.2f}% limit")
        gate.add("drawdown", state.drawdown_pct > -limits.max_drawdown_pct,
                 f"drawdown {state.drawdown_pct:.2f}% has reached the -{limits.max_drawdown_pct:.2f}% limit")
        gate.add("weekly_loss", state.weekly_pnl_pct > -limits.max_weekly_loss_pct,
                 f"weekly P&L {state.weekly_pnl_pct:.2f}% has reached the -{limits.max_weekly_loss_pct:.2f}% limit")
        cooldown_ok = not state.cooldown_until or now >= state.cooldown_until
        gate.add("cooldown", cooldown_ok,
                 f"cooldown after {state.consecutive_losses} consecutive losses until "
                 f"{datetime.fromtimestamp(state.cooldown_until, tz=self.tz).strftime('%H:%M')}"
                 if not cooldown_ok else "no cooldown")
        gate.add("consecutive_losses", state.consecutive_losses < limits.max_consecutive_losses,
                 f"{state.consecutive_losses} consecutive losses (limit {limits.max_consecutive_losses})")
        gate.add("exposure", state.open_lots + requested_lot <= limits.max_exposure_lots + 1e-9,
                 f"exposure {state.open_lots + requested_lot:.2f} lots exceeds {limits.max_exposure_lots:.2f}")
        gate.add("trades_per_week", state.trades_this_week < limits.max_weekly_trades,
                 f"{state.trades_this_week} trades this week (limit {limits.max_weekly_trades})")
        gate.add("volatility", atr_pct <= limits.abnormal_volatility_atr_pct,
                 f"ATR {atr_pct:.2f}% of price exceeds the {limits.abnormal_volatility_atr_pct:.2f}% "
                 f"abnormal-volatility threshold")
        news_ok = (not limits.news_lockout_enabled) or (not news_lockout.get("active"))
        gate.add("news_lockout", news_ok,
                 f"news lockout: {news_lockout.get('reason') or 'high-impact event window'}")
        if is_full_auto:
            gate.add("full_auto_lock", bool(self.settings.security.get("allow_full_auto")),
                     "full auto is disabled by the deployment switch")
            gate.add("full_auto_score", signal_score >= 85, f"full auto needs score >= 85 (got {signal_score:.0f})")
            gate.add("full_auto_model", model_approved,
                     "full auto requires a model that passed its out-of-sample gates")
            if calibrated_probability is not None:
                gate.add("full_auto_probability", calibrated_probability >= 0.55,
                         f"calibrated TP-before-SL probability {calibrated_probability:.0%} below 55%")
        return gate

    # -------------------------------------------------------------- helpers
    def record_mode(self) -> TradeMode:
        return TradeMode(self.db.kv_get("trade_mode", TradeMode.manual.value))

    def daily_report(self, now: float | None = None) -> dict[str, Any]:
        now = now or time.time()
        day_start = self._day_start(now)
        rows = self.db.query("SELECT * FROM trades WHERE closed_at >= ? ORDER BY closed_at", (day_start,))
        wins = [r for r in rows if float(r["pnl"] or 0) > 0]
        losses = [r for r in rows if float(r["pnl"] or 0) < 0]
        pnl = sum(float(r["pnl"] or 0) for r in rows)
        return {
            "trades": len(rows),
            "wins": len(wins),
            "losses": len(losses),
            "pnl": round(pnl, 2),
            "win_rate": round(len(wins) / len(rows) * 100, 1) if rows else 0.0,
            "avg_win": round(sum(float(r["pnl"]) for r in wins) / len(wins), 2) if wins else 0.0,
            "avg_loss": round(sum(float(r["pnl"]) for r in losses) / len(losses), 2) if losses else 0.0,
            "since": datetime.fromtimestamp(day_start, tz=self.tz).isoformat(),
        }


def default_risk_state(equity: float) -> RiskState:
    return RiskState(balance=equity, equity=equity, peak_equity=equity, daily_pnl=0.0, daily_pnl_pct=0.0,
                     weekly_pnl=0.0, weekly_pnl_pct=0.0, drawdown_pct=0.0, open_trades=0, open_lots=0.0,
                     exposure_pct=0.0, consecutive_losses=0, trades_today=0, trades_this_week=0)


def direction_from_side(side: str) -> Direction:
    return Direction.up if side.lower() == "buy" else Direction.down


__all__ = ["RiskEngine", "RiskGate", "default_risk_state", "direction_from_side", "json"]
