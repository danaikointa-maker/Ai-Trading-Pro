"""Candidate-only price normalization must round protective levels outward."""
from __future__ import annotations

import math

import pytest
import yaml

from packages.shared_schemas.models import (
    Direction,
    RiskSettings,
    SymbolSpec,
    Zone,
    ZoneKind,
    ZoneQuality,
    ZoneStatus,
)
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
        direction=direction, entry=2000.0, spec=SPEC,
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
    sl_raw = 2000.0 - sign * plan.sl_points * SPEC.point
    sl_ticks = sl_raw / SPEC.tick_size
    expected_sl = (math.ceil(sl_ticks - 1e-10) if sl_round == "up"
                   else math.floor(sl_ticks + 1e-10)) * SPEC.tick_size
    assert plan.sl == pytest.approx(round(expected_sl, SPEC.digits))
    for target, points in zip((plan.tp1, plan.tp2, plan.tp3), plan.tp_points):
        raw = 2000.0 + sign * points * SPEC.point
        ticks = raw / SPEC.tick_size
        expected_ticks = (math.ceil(ticks - 1e-10) if tp_round == "up"
                          else math.floor(ticks + 1e-10))
        assert target == pytest.approx(round(expected_ticks * SPEC.tick_size,
                                             SPEC.digits))


def test_candidate_rejects_minimum_lot_that_exceeds_risk_budget():
    result = PLANNER.build(PlanInputs(
        direction=Direction.up, entry=2000.0, spec=SPEC,
        atr_points=100.0, equity=100.0, risk_pct=0.5,
        spread_points=1.0, supports=[], resistances=[], swings=[],
        target_mode="fixed", fixed_points=[500, 750, 1000],
        min_points=500, max_points=1000, sl_atr_multiplier=1.5,
        sl_min_points=10, sl_max_points=1200, min_rr_net=0.1,
        respect_zones=False, closes_pct=[100, 0, 0],
        directional_tick_rounding=True,
    ))

    assert result.plan is None
    assert "risk_budget_min_lot" in result.blocker_codes


@pytest.mark.parametrize(("equity", "risk_pct"), [(0.0, 0.5), (100.0, 0.0), (float("nan"), 0.5)])
def test_candidate_rejects_invalid_risk_budget_before_lot_rounding(equity, risk_pct):
    result = PLANNER.build(PlanInputs(
        direction=Direction.up, entry=2000.0, spec=SPEC,
        atr_points=100.0, equity=equity, risk_pct=risk_pct,
        spread_points=1.0, supports=[], resistances=[], swings=[],
        target_mode="fixed", fixed_points=[500, 750, 1000],
        min_points=500, max_points=1000, sl_atr_multiplier=1.5,
        sl_min_points=10, sl_max_points=1200, min_rr_net=0.1,
        respect_zones=False, closes_pct=[100, 0, 0],
        directional_tick_rounding=True,
    ))

    assert result.plan is None
    assert "invalid_risk_budget" in result.blocker_codes


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


@pytest.mark.parametrize(("direction", "kind", "swing_price"), [
    (Direction.up, "low", 1997.5),
    (Direction.down, "high", 2002.5),
])
def test_atr_structure_candidate_uses_wider_recent_m5_swing(direction, kind, swing_price):
    result = PLANNER.build(PlanInputs(
        direction=direction, entry=2000.0, spec=SPEC,
        atr_points=100.0, equity=10_000.0, risk_pct=0.5,
        spread_points=1.0, supports=[], resistances=[],
        swings=[{"kind": kind, "price": 1900.0 if kind == "low" else 2100.0,
                 "idx": 89},
                {"kind": kind, "price": swing_price, "idx": 95}],
        sl_policy="atr_structure", sl_atr_multiplier=1.5,
        sl_structure_buffer_atr=0.2, swing_lookback_bars=10,
        m5_bar_count=100, sl_min_points=10, sl_max_points=1000,
        target_mode="fixed", fixed_points=[500, 750, 1000],
        min_points=500, max_points=1000, min_rr_net=0.1,
        respect_zones=False, closes_pct=[40, 30, 30],
        directional_tick_rounding=True,
    ))

    assert result.plan is not None, result.blockers
    # 250 points swing distance + 20 points (0.2 ATR) exceeds 1.5 ATR.
    assert result.plan.sl_points == pytest.approx(270)


def test_atr_structure_candidate_rejects_required_stop_above_maximum():
    result = PLANNER.build(PlanInputs(
        direction=Direction.up, entry=2000.0, spec=SPEC,
        atr_points=100.0, equity=10_000.0, risk_pct=0.5,
        spread_points=1.0, supports=[], resistances=[],
        swings=[{"kind": "low", "price": 1980.0, "idx": 95}],
        sl_policy="atr_structure", sl_atr_multiplier=1.5,
        sl_structure_buffer_atr=0.2, swing_lookback_bars=10,
        m5_bar_count=100, sl_min_points=10, sl_max_points=1000,
        min_rr_net=0.1,
    ))

    assert result.plan is None
    assert "stop_distance_max" in result.blocker_codes


@pytest.mark.parametrize("direction", [Direction.up, Direction.down])
def test_candidate_structure_buffer_converts_atr_points_to_price(direction):
    kind = "low" if direction == Direction.up else "high"
    swing_price = 1998.0 if direction == Direction.up else 2002.0
    points, _ = PLANNER._stop_from_structure(direction, 2000.0, PlanInputs(
        direction=direction, entry=2000.0, spec=SPEC, atr_points=100,
        equity=10_000, risk_pct=0.5, spread_points=1,
        supports=[], resistances=[], swings=[{"kind": kind, "price": swing_price}],
        sl_min_points=1, sl_max_points=1000,
    ))
    # 100 points * 0.35 ATR = 35 points = $0.35, not $35.
    assert points == pytest.approx(235)


def test_atr_structure_candidate_rejects_missing_atr_data():
    result = PLANNER.build(PlanInputs(
        direction=Direction.up, entry=2000.0, spec=SPEC,
        atr_points=0.0, equity=10_000.0, risk_pct=0.5,
        spread_points=1.0, supports=[], resistances=[],
        sl_policy="atr_structure", sl_atr_multiplier=1.5,
        sl_structure_buffer_atr=0.2, swing_lookback_bars=10,
        m5_bar_count=100, sl_min_points=10, sl_max_points=1000,
    ))

    assert result.plan is None
    assert "invalid_stop_policy" in result.blocker_codes


def test_atr_structure_candidate_rejects_missing_closed_m5_structure():
    result = PLANNER.build(PlanInputs(
        direction=Direction.up, entry=2000.0, spec=SPEC,
        atr_points=100.0, equity=10_000.0, risk_pct=0.5,
        spread_points=1.0, supports=[], resistances=[], swings=[],
        sl_policy="atr_structure", sl_atr_multiplier=1.5,
        sl_structure_buffer_atr=0.2, swing_lookback_bars=10,
        m5_bar_count=100, sl_min_points=10, sl_max_points=1000,
    ))

    assert result.plan is None
    assert "structure_missing" in result.blocker_codes


def test_zone_buffer_is_converted_from_points_to_price():
    zone = Zone(id="R1", kind=ZoneKind.resistance, low=2004.5, high=2005.1,
                mid=2004.8, strength=0.9, quality=ZoneQuality.high,
                status=ZoneStatus.confirmed)
    inputs = PlanInputs(
        direction=Direction.up, entry=2000.0, spec=SPEC,
        atr_points=100, equity=10_000, risk_pct=0.5, spread_points=1,
        supports=[], resistances=[zone], atr_target_multiplier=5,
        zone_buffer_atr=0.35, respect_zones=True,
        min_points=300, max_points=1000, fixed_points=[500, 750, 1000],
        target_mode="fixed",
    )

    ladder, notes, blockers = PLANNER._tp_ladder(Direction.up, 2000.0, inputs)

    assert blockers == []
    assert ladder[0] == pytest.approx(415)
    assert any("TP1 capped" in note for note in notes)


def test_obstructed_target_below_minimum_is_rejected():
    zone = Zone(id="R1", kind=ZoneKind.resistance, low=2004.5, high=2005.1,
                mid=2004.8, strength=0.9, quality=ZoneQuality.high,
                status=ZoneStatus.confirmed)
    inputs = PlanInputs(
        direction=Direction.up, entry=2000.0, spec=SPEC,
        atr_points=100, equity=10_000, risk_pct=0.5, spread_points=1,
        supports=[], resistances=[zone], zone_buffer_atr=0.35,
        respect_zones=True, min_points=500, max_points=1000,
        fixed_points=[500, 750, 1000], target_mode="fixed",
    )

    _, _, blockers = PLANNER._tp_ladder(Direction.up, 2000.0, inputs)

    assert blockers and "configured minimum target" in blockers[0]


@pytest.mark.parametrize(("direction", "kind", "swing_price"), [
    (Direction.up, "low", 1997.5),
    (Direction.down, "high", 2002.5),
])
def test_single_target_candidate_is_2r_and_has_no_partial_ladder(
        direction, kind, swing_price):
    result = PLANNER.build(PlanInputs(
        direction=direction, entry=2000.0, spec=SPEC,
        atr_points=100, equity=10_000, risk_pct=0.5, spread_points=1,
        supports=[], resistances=[], swings=[{"kind": kind, "price": swing_price, "idx": 95}],
        sl_policy="atr_structure", sl_atr_multiplier=1.5,
        sl_structure_buffer_atr=0.2, swing_lookback_bars=10, m5_bar_count=100,
        sl_min_points=10, sl_max_points=1000, min_points=500,
        max_points=1000, min_rr_net=1.5, target_mode="fixed",
        fixed_points=[500, 750, 1000], respect_zones=False,
        directional_tick_rounding=True, single_target_r=2.0,
    ))

    assert result.plan is not None, result.blockers
    plan = result.plan
    assert plan.target_mode == "single_2r"
    assert plan.tp_points == [540, 540, 540]
    assert len(plan.partials) == 1
    assert plan.partials[0].close_pct == 100
    assert plan.partials[0].price == plan.tp1
    assert plan.reward_risk_net >= 1.5


def test_single_2r_target_rejects_opposing_zone_before_target():
    zone = Zone(id="R1", kind=ZoneKind.resistance, low=2003.8, high=2004.4,
                mid=2004.1, strength=0.9, quality=ZoneQuality.high,
                status=ZoneStatus.confirmed)
    result = PLANNER.build(PlanInputs(
        direction=Direction.up, entry=2000.0, spec=SPEC,
        atr_points=100, equity=10_000, risk_pct=0.5, spread_points=1,
        supports=[], resistances=[zone], swings=[{"kind": "low", "price": 1997.5,
                                                   "idx": 95}],
        sl_policy="atr_structure", sl_atr_multiplier=1.5,
        sl_structure_buffer_atr=0.2, swing_lookback_bars=10, m5_bar_count=100,
        sl_min_points=10, sl_max_points=1000, min_points=500,
        max_points=1000, min_rr_net=1.5, single_target_r=2.0,
    ))

    assert result.plan is None
    assert "opposing_zone" in result.blocker_codes
