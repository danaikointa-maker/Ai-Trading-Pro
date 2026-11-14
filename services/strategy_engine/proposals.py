"""Read-only alternatives near confirmed zones; never an order permission.

The existing signal and RiskGate remain the *only* admission path. Proposals
are hypothetical limit-entry scenarios with each lot sized by TradePlanner;
the sum of all shown alternatives is bounded by shared risk and lot caps.
No account-currency notional estimate is inferred without verified FX conversion;
each proposed entry still requires a fresh independent execution risk check.
"""
from __future__ import annotations

import math
from typing import Any

from packages.shared_schemas.models import (AnalysisSnapshot, Direction, RiskLimits,
                                            RiskState, Signal, SignalAction, ZoneStatus)
from services.risk_engine.planner import PlanInputs, TradePlanner


def entry_proposals(signal: Signal, analysis: AnalysisSnapshot, planner: TradePlanner,
                    limits: RiskLimits, risk_state: RiskState, equity: float,
                    spread_points: float, *, gate_allow: bool) -> dict[str, Any]:
    """Return 0–3 budgeted proposals. All outputs are non-executable evidence."""
    response: dict[str, Any] = {"signal_id": signal.id, "proposals": [],
                                "executable": False, "source": "read_only_plan_scenarios",
                                "reasons": [], "risk_budget": 0.0, "aggregate_risk": 0.0,
                                "aggregate_lots": 0.0}
    if (not gate_allow or signal.action not in (SignalAction.buy, SignalAction.sell)
            or signal.plan is None or signal.broker_id != analysis.broker_id
            or signal.symbol != analysis.symbol or risk_state.kill_switch_active):
        response["reasons"].append("signal or independent RiskGate blocks proposals")
        return response
    if (not math.isfinite(equity) or equity <= 0 or not math.isfinite(spread_points)
            or spread_points < 0 or analysis.spec.sizing_blocked
            or not math.isfinite(risk_state.exposure_pct)
            or risk_state.exposure_pct >= limits.max_leverage_notional_x_equity * 100):
        response["reasons"].append("account equity, costs or contract specification unavailable")
        return response

    # Assume every existing position might share the symbol unless broker
    # position-level evidence proves otherwise. Conservative by construction.
    slots = max(0, min(3, limits.max_open_trades - risk_state.open_trades,
                       limits.max_open_per_symbol - risk_state.open_trades))
    remaining_lots = max(0.0, limits.max_exposure_lots - risk_state.open_lots)
    budget = equity * limits.risk_per_trade_pct / 100.0
    response["risk_budget"] = round(budget, 2)
    if slots <= 0 or remaining_lots < analysis.spec.min_lot:
        response["reasons"].append("no remaining position slots or lot exposure")
        return response

    direction = Direction.up if signal.action == SignalAction.buy else Direction.down
    aligned_zones = analysis.supports if direction == Direction.up else analysis.resistances
    price_cap = max(analysis.spec.point, analysis.indicators.atr14 * 2.0)
    candidates = [(signal.plan.entry, "market_reference", None)]
    for zone in aligned_zones:
        if zone.status != ZoneStatus.confirmed:
            continue
        entry = analysis.spec.round_price(zone.mid)
        if (abs(entry - signal.plan.entry) <= price_cap
                and all(abs(entry - price) >= analysis.spec.point * 4 for price, _, _ in candidates)):
            candidates.append((entry, "confirmed_zone_pullback", zone.id))
        if len(candidates) >= 3:
            break

    remaining_risk = budget
    risk_cfg = planner.cfg
    stops = risk_cfg.get("stops", {})
    targets = risk_cfg.get("targets", {})
    for entry, scenario, zone_id in candidates[:slots]:
        remaining_slots = slots - len(response["proposals"])
        allocation = min(budget / slots, remaining_risk / max(1, remaining_slots))
        if allocation <= 0:
            break
        result = planner.build(PlanInputs(
            direction=direction, entry=entry, spec=analysis.spec,
            atr_points=max(1.0, analysis.indicators.atr_points), equity=equity,
            risk_pct=allocation / equity * 100.0, spread_points=spread_points,
            supports=analysis.supports, resistances=analysis.resistances,
            swings=[{"kind": s.kind, "price": s.price} for s in analysis.swings if s.confirmed],
            target_mode=targets.get("mode", "adaptive"),
            fixed_points=targets.get("fixed_points"),
            min_points=float(targets.get("min_points", 500)),
            max_points=float(targets.get("max_points", 1000)),
            sl_atr_multiplier=float(stops.get("sl_atr_multiplier", 1.0)),
            sl_min_points=float(stops.get("sl_min_points", 150)),
            sl_max_points=float(stops.get("sl_max_points", 1200)),
            min_rr_net=limits.min_reward_risk,
            atr_target_multiplier=float(targets.get("adaptive", {}).get("atr_multiplier", 2.2)),
            zone_buffer_atr=float(targets.get("adaptive", {}).get("zone_buffer_atr", 0.35)),
            respect_zones=bool(targets.get("adaptive", {}).get("respect_zones", True)),
            closes_pct=targets.get("ladder", {}).get("closes_pct"),
        ))
        plan = result.plan
        if plan is None:
            response["reasons"].append(f"{scenario}: {', '.join(result.blockers[:2])}")
            continue
        if (not math.isfinite(plan.risk_amount) or plan.risk_amount <= 0
                or plan.risk_amount > remaining_risk + 1e-6
                or plan.lot > remaining_lots + 1e-9):
            response["reasons"].append(f"{scenario}: aggregate risk or lot cap exceeded")
            continue
        response["proposals"].append({
            "proposal_id": f"{signal.id}-P{len(response['proposals']) + 1}",
            "scenario": scenario, "zone_id": zone_id,
            "plan": plan.model_dump(mode="json"), "executable": False,
            "note": "hypothetical entry; requires a fresh signal and full independent risk gate",
        })
        remaining_risk -= plan.risk_amount
        remaining_lots -= plan.lot

    response["aggregate_risk"] = round(budget - remaining_risk, 2)
    response["aggregate_lots"] = round(sum(row["plan"]["lot"] for row in response["proposals"]), 4)
    return response
