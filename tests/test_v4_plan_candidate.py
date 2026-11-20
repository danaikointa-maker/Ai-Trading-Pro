"""Candidate-only price normalization must round protective levels outward."""
from __future__ import annotations

import math

import pytest
import yaml

from packages.shared_schemas.models import Direction, RiskSettings, SymbolSpec
from services.risk_engine.planner import (
    PlanInputs,
    TradePlanner,
    build_plan_inputs,
)

SPEC = SymbolSpec(
    symbol="XAUUSD", digits=2, point=0.01, tick_size=0.05,
    contract_size=100.0, min_lot=0.01, max_lot=50.0, lot_step=0.01,
)
PLANNER = TradePlanner(yaml.safe_load(open("config/risk.yaml", encoding="utf-8")))


@pytest.mark.parametrize(("direction", "sl_round", "tp_round"), [
    (Direction.up, "down", "up"),
    (Direction.down, "up", "down"),
])
def test_v4_candidate_rounds_sl_and_tp_outward(direction, sl_round, tp_round):
    sign = 1 if direction == Direction.up else -1
    result = PLANNER.build(PlanInputs(
        direction=direction, entry=2000.02, spec=SPEC,
        atr_points=100.0, equity=10_000.0, risk_pct=0.5,
        spread_points=1.0, supports=[], resistances=[], swings=[],
        target_mode="fixed", fixed_points=[500, 750, 1000],
        min_points=500, max_points=1000, sl_atr_multiplier=1.5,
        sl_min_points=10, sl_max_points=1200, min_rr_net=0.1,
        respect_zones=False, closes_pct=[100, 0, 0],
        directional_tick_rounding=True,
    ))
    assert result.plan is not None, result.blockers
    plan = result.plan
    assert plan.sl == pytest.approx(SPEC.round_price(plan.sl))
    assert all(price == pytest.approx(SPEC.round_price(price))
               for price in (plan.tp1, plan.tp2, plan.tp3))
    assert (plan.sl - plan.entry) * sign < 0
    assert (plan.tp1 - plan.entry) * sign > 0
    sl_raw = 2000.02 - sign * plan.sl_points * SPEC.point
    sl_ticks = sl_raw / SPEC.tick_size
    expected_sl = (math.ceil(sl_ticks - 1e-10) if sl_round == "up"
                   else math.floor(sl_ticks + 1e-10)) * SPEC.tick_size
    assert plan.sl == pytest.approx(round(expected_sl, SPEC.digits))
    for target, points in zip((plan.tp1, plan.tp2, plan.tp3), plan.tp_points):
        raw = 2000.02 + sign * points * SPEC.point
        ticks = raw / SPEC.tick_size
        expected_ticks = (math.ceil(ticks - 1e-10) if tp_round == "up"
                          else math.floor(ticks + 1e-10))
        assert target == pytest.approx(round(expected_ticks * SPEC.tick_size,
                                             SPEC.digits))


def test_legacy_plan_input_keeps_nearest_tick_behavior():
    legacy = PLANNER._round_level(
        SPEC, 2000.02, Direction.up, is_stop=True, directional=False)
    candidate = PLANNER._round_level(
        SPEC, 2000.02, Direction.up, is_stop=True, directional=True)

    assert legacy == SPEC.round_price(2000.02)
    assert candidate <= 2000.02


def test_shared_builder_uses_effective_legacy_settings_for_both_entry_modes():
    risk_cfg = yaml.safe_load(open("config/risk.yaml", encoding="utf-8"))
    effective = RiskSettings(
        limits={"risk_per_trade_pct": 0.5, "min_reward_risk": 1.3},
        targets_mode="adaptive", fixed_points=[500, 750, 1000],
        min_points=500, max_points=1000, sl_atr_multiplier=1.5,
    )
    inputs = build_plan_inputs(
        risk_cfg=risk_cfg, effective=effective,
        direction=Direction.up, entry=2000.0, spec=SPEC,
        atr_points=100.0, equity=10_000.0, spread_points=20.0,
        supports=[], resistances=[], swings=[],
    )

    assert inputs.risk_pct == 0.5
    assert inputs.min_rr_net == 1.3
    assert inputs.sl_atr_multiplier == 1.5
    assert inputs.atr_target_multiplier == 2.2
    assert inputs.closes_pct == [40, 30, 30]
    assert inputs.directional_tick_rounding is False
