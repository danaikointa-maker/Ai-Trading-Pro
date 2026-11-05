"""Performance metrics used by the backtester and the live evaluation page."""
from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np

from packages.shared_schemas.models import BacktestMetrics, EquityPoint, TradeRecord


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def compute_metrics(trades: list[TradeRecord], equity_curve: list[EquityPoint],
                    decisions: int, starting_balance: float,
                    hold_minutes: Iterable[float] | None = None) -> BacktestMetrics:
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    net = sum(t.pnl for t in trades)
    costs = sum(t.costs for t in trades)

    eq = np.array([p.equity for p in equity_curve]) if equity_curve else np.array([starting_balance])
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / np.where(peak == 0, 1, peak)
    max_dd = float(abs(dd.min()) * 100) if len(dd) else 0.0

    returns = np.diff(eq) / np.where(eq[:-1] == 0, 1, eq[:-1]) if len(eq) > 1 else np.array([])
    # Bars are ~5 minutes of market time; annualise on that basis for comparability.
    periods_per_year = 252 * 288
    sharpe = float(_safe_div(returns.mean(), returns.std(ddof=0)) * math.sqrt(periods_per_year)) if len(returns) > 2 and returns.std(ddof=0) > 0 else 0.0
    downside = returns[returns < 0]
    sortino = float(_safe_div(returns.mean(), downside.std(ddof=0)) * math.sqrt(periods_per_year)) if len(downside) > 2 and downside.std(ddof=0) > 0 else 0.0

    tp_first = sum(1 for t in trades if t.exit_reason in ("take profit", "partial_tp3", "partial_tp2"))
    avg_hold = float(np.mean(list(hold_minutes))) if hold_minutes else 0.0

    streak = worst_streak = 0
    for t in trades:
        if t.pnl <= 0:
            streak += 1
            worst_streak = max(worst_streak, streak)
        else:
            streak = 0

    total_return_pct = (eq[-1] - starting_balance) / starting_balance * 100 if starting_balance else 0.0
    return BacktestMetrics(
        trades=len(trades),
        wins=len(wins),
        losses=len(losses),
        win_rate=round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        gross_profit=round(gross_profit, 2),
        gross_loss=round(gross_loss, 2),
        net_profit=round(net, 2),
        profit_factor=round(gross_profit / gross_loss, 3) if gross_loss else (round(gross_profit, 2) if gross_profit else 0.0),
        expectancy=round(net / len(trades), 2) if trades else 0.0,
        expectancy_r=round(float(np.mean([t.r_multiple for t in trades])), 3) if trades else 0.0,
        avg_win=round(gross_profit / len(wins), 2) if wins else 0.0,
        avg_loss=round(-gross_loss / len(losses), 2) if losses else 0.0,
        max_drawdown_pct=round(max_dd, 2),
        sharpe=round(min(10.0, max(-10.0, sharpe)), 2),
        sortino=round(min(10.0, max(-10.0, sortino)), 2),
        tp_before_sl_rate=round(tp_first / len(trades) * 100, 2) if trades else 0.0,
        directional_accuracy=round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        no_trade_rate=round(max(0.0, 1 - len(trades) / decisions) * 100, 2) if decisions else 0.0,
        avg_hold_minutes=round(avg_hold, 1),
        total_costs=round(costs, 2),
        best_trade=round(max((t.pnl for t in trades), default=0.0), 2),
        worst_trade=round(min((t.pnl for t in trades), default=0.0), 2),
        return_pct=round(total_return_pct, 3),
        recovery_factor=round(_safe_div(net, max(1e-9, max_dd / 100 * starting_balance)), 3),
        max_consecutive_losses=worst_streak,
    )


def verdict(metrics: BacktestMetrics, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """The pre-registered pass/fail bar from docs/accuracy.md."""
    cfg = cfg or {}
    min_pf = float(cfg.get("min_profit_factor", 1.3))
    min_trades = int(cfg.get("min_trades", 30))
    max_dd = float(cfg.get("max_drawdown_pct", 15.0))
    checks = [
        {"name": "Profit factor > 1.3", "value": metrics.profit_factor, "pass": metrics.profit_factor > min_pf},
        {"name": "Positive expectancy", "value": metrics.expectancy, "pass": metrics.expectancy > 0},
        {"name": "Enough trades to judge", "value": metrics.trades, "pass": metrics.trades >= min_trades},
        {"name": "Drawdown within budget", "value": metrics.max_drawdown_pct, "pass": metrics.max_drawdown_pct <= max_dd},
        {"name": "Not dependent on a few trades",
         "value": round(metrics.best_trade / max(1e-9, metrics.net_profit) * 100, 1) if metrics.net_profit > 0 else None,
         "pass": metrics.net_profit <= 0 or (metrics.best_trade / max(1e-9, metrics.net_profit)) < 0.5},
    ]
    return {"passed": all(c["pass"] for c in checks), "checks": checks,
            "summary": ("PASS — the rules clear the pre-registered bar on this sample; forward-test on demo next."
                        if all(c["pass"] for c in checks) else
                        "FAIL — do not promote these rules to live trading based on this sample.")}
