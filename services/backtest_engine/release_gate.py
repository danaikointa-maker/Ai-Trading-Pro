"""Offline release evidence gate for Smart Entry V2. NEVER enables live trading.

Reports are operator-provided data, not cryptographically attested broker facts.
Passing this gate only nominates the build for independent human review.
"""
from __future__ import annotations

import math
import re
from typing import Any


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def assess_release(baseline: dict, stress: list[dict], demo: dict | None) -> dict[str, Any]:
    failures: list[str] = []

    def require(ok: bool, reason: str) -> None:
        if not ok:
            failures.append(reason)

    # Reject malformed nested reports as data gaps rather than crashing the
    # operator CLI or mistakenly interpreting booleans as counts/costs.
    for label, report in [("baseline", baseline),
                          *((f"stress {i + 1}", report) for i, report in enumerate(stress)),
                          ("demo", demo or {})]:
        if not isinstance(report, dict):
            failures.append(f"{label}: report must be a JSON object")
            continue
        fields = (("dataset", "metrics", "diagnostics") if label != "demo" else ())
        for field in fields:
            if not isinstance(report.get(field), dict):
                failures.append(f"{label}: {field} must be an object")
        if label != "demo":
            diagnostics = report.get("diagnostics")
            if isinstance(diagnostics, dict):
                for field in ("cost_assumptions", "intra_bar"):
                    if not isinstance(diagnostics.get(field), dict):
                        failures.append(f"{label}: diagnostics.{field} must be an object")
    folds_value = baseline.get("walk_forward") if isinstance(baseline, dict) else None
    if not isinstance(folds_value, list) or not all(isinstance(f, dict) for f in folds_value):
        failures.append("baseline: walk_forward must be an array of fold objects")
    if failures:
        return {"state": "blocked", "passed": False, "failures": failures,
                "operator_review_required": True, "live_auto_enabled": False,
                "note": "Malformed evidence is not operator authorization."}

    dataset = baseline.get("dataset") or {}
    source = str(dataset.get("source") or "").lower()
    sha = str(dataset.get("sha256") or "")
    require(bool(re.fullmatch(r"[0-9a-f]{64}", sha)), "baseline must contain an immutable dataset sha256")
    require(bool(dataset.get("reproducible")), "baseline dataset must be reproducible")
    require(any(word in source for word in ("imported", "mt5")) and "simulat" not in source,
            "baseline must use real imported/broker history, not simulated bars")
    require((_finite(baseline.get("bars")) or 0) >= 6000, "baseline needs >=6000 M1 bars")
    start, stop = _finite(baseline.get("from_t")), _finite(baseline.get("to_t"))
    require(start is not None and stop is not None and start < stop,
            "baseline time range is invalid")
    m = baseline.get("metrics") or {}
    require((_finite(m.get("trades")) or 0) >= 30, "baseline needs >=30 closed trades")
    require((_finite(m.get("profit_factor")) or 0) >= 1.3, "baseline profit factor below 1.30")
    require((_finite(m.get("expectancy")) or 0) > 0, "baseline expectancy must be positive")
    drawdown = _finite(m.get("max_drawdown_pct"))
    require(drawdown is not None and 0 <= drawdown <= 10, "baseline drawdown exceeds 10% or is invalid")
    folds = baseline.get("walk_forward") or []
    require(len(folds) >= 4, "four walk-forward folds are required")
    qualifying = sum((_finite(f.get("trades")) or 0) >= 5
                     and (_finite(f.get("expectancy")) or 0) > 0 for f in folds)
    require(qualifying >= 3, "at least three folds must show positive expectancy with >=5 trades")

    costs = (baseline.get("diagnostics") or {}).get("cost_assumptions") or {}
    base_spread = _finite(costs.get("spread_points"))
    base_slippage = _finite(costs.get("slippage_points"))
    require(base_spread is not None and base_spread > 0 and base_slippage is not None,
            "baseline must record structured spread/slippage assumptions")
    intra_bar = (baseline.get("diagnostics") or {}).get("intra_bar") or {}
    require(intra_bar.get("mode") not in (None, "conservative") and intra_bar.get("available") is not False,
            "baseline needs verified tick-level ordering; bar-only fills are insufficient")
    require(len(stress) >= 2, "two independent higher-cost stress replays are required")
    seen_costs = set()
    for index, report in enumerate(stress):
        tag = f"stress {index + 1}"
        ds = report.get("dataset") or {}
        require(ds.get("sha256") == sha and bool(ds.get("reproducible")),
                f"{tag}: must replay the same immutable dataset")
        cc = (report.get("diagnostics") or {}).get("cost_assumptions") or {}
        spread, slippage = _finite(cc.get("spread_points")), _finite(cc.get("slippage_points"))
        require(spread is not None and slippage is not None
                and base_spread is not None and base_slippage is not None
                and spread >= base_spread and slippage >= base_slippage
                and (spread > base_spread or slippage > base_slippage),
                f"{tag}: costs must be strictly more adverse than baseline")
        seen_costs.add((spread, slippage))
        metrics = report.get("metrics") or {}
        require((_finite(metrics.get("profit_factor")) or 0) >= 1.0
                and (_finite(metrics.get("expectancy")) or 0) > 0,
                f"{tag}: stress profitability is not robust")
        stressed_dd = _finite(metrics.get("max_drawdown_pct"))
        require(stressed_dd is not None and 0 <= stressed_dd <= 10,
                f"{tag}: drawdown limit failed")
    require(len(seen_costs) >= 2, "stress scenarios must have distinct cost assumptions")

    demo = demo or {}
    require(demo.get("account_type") == "demo" and demo.get("broker_id") == baseline.get("broker_id"),
            "a matching MT5 Demo broker/account report is required")
    require((_finite(demo.get("forward_days")) or 0) >= 14
            and (_finite(demo.get("closed_trades")) or 0) >= 30,
            "demo forward observation needs >=14 days and >=30 closed trades")
    for key in ("account_identity_verified", "all_fills_verified", "partial_fills_reconciled",
                "restarts_reconciled", "disconnects_reconciled", "manual_changes_reconciled"):
        require(demo.get(key) is True, f"demo evidence missing: {key}")
    require(demo.get("unresolved_orders") == 0, "demo has unresolved broker orders")

    return {"state": "blocked" if failures else "ready_for_operator_review",
            "passed": not failures, "failures": failures,
            "operator_review_required": True, "live_auto_enabled": False,
            "note": "This is an offline evidence check, not proof of profitability or permission for LIVE trading."}
