from types import SimpleNamespace

import pytest

from packages.shared_schemas.models import Direction, Position, SymbolSpec
from services.risk_engine.manager import PositionManager
from services.risk_engine.protection_profile import migration_manifest, validate_v1_1_profile


@pytest.fixture
def profile():
    return {
        "id": "position-protection-v1.1", "version": "1.1", "status": "staged",
        "default_mode": "MANUAL",
        "automation": {"enabled": False, "allowed_account_types": ["demo"], "live_allowed": False},
        "break_even": {"enabled": True, "activation_r": 1.0, "extra_lock_points": 0.0,
                        "estimated_swap_cost_per_lot": 0.0, "slippage_allowance_points": 15},
        "trailing": {"enabled": True, "activation_r": 1.5, "atr_multiplier": 1.0,
                     "step_atr": 0.2, "max_atr_age_seconds": 90,
                     "require_break_even_confirmed": True},
        "partial_close": {"enabled": False},
        "protection": {"sl_required": True, "tp_required": True,
                       "never_widen_stop_loss": True, "never_increase_risk_after_entry": True,
                       "reject_invalid_stop_levels": True, "reject_unknown_position_identity": True},
    }


@pytest.fixture
def manager():
    return PositionManager.__new__(PositionManager)


def plan(direction=Direction.up, entry=2000.0, sl=1999.0):
    return SimpleNamespace(
        broker_id="demo", symbol="XAUUSD",
        plan=SimpleNamespace(direction=direction, entry=entry, sl=sl),
    )


def pos(direction=Direction.up, *, sl=1999.0, points=300, current=2003.0):
    return Position(ticket="42", symbol="XAUUSD", direction=direction, volume=0.1,
                    entry=2000.0, sl=sl, tp=2005.0, open_time=1,
                    current_price=current, points=points, broker_id="demo", signal_id="sig")


def test_v1_1_buy_break_even_uses_original_r_and_cost_buffer(manager, profile):
    spec = SymbolSpec(symbol="XAUUSD", point=0.01, tick_size=0.01, contract_size=100,
                      commission_per_lot_round_turn=7)
    action, blockers = manager.protection_candidate(
        pos(), spec, plan(), profile, close_price=2003.0)
    assert any("closed-bar ATR" in reason for reason in blockers)
    assert action.reason == "break_even_v1_1"
    assert action.new_sl == pytest.approx(2000.22)
    assert action.metadata["initial_r_price"] == pytest.approx(1.0)


def test_v1_1_sell_break_even_is_directional_and_never_widens(manager, profile):
    spec = SymbolSpec(symbol="XAUUSD", point=0.01, tick_size=0.01, contract_size=100,
                      commission_per_lot_round_turn=7)
    action, blockers = manager.protection_candidate(
        pos(Direction.down, sl=2001.0, current=1997.0), spec,
        plan(Direction.down, sl=2001.0), profile, close_price=1997.0)
    assert any("closed-bar ATR" in reason for reason in blockers)
    assert action.new_sl == pytest.approx(1999.78)
    assert action.new_sl < 2001.0


def test_v1_1_refuses_to_widen_or_cross_current_price(manager, profile):
    spec = SymbolSpec(symbol="XAUUSD", point=0.01, tick_size=0.01, contract_size=100)
    losing = pos(sl=2000.5, points=200, current=2002.0)
    action, blockers = manager.protection_candidate(losing, spec, plan(), profile,
                                                     close_price=2002.0)
    assert action is None
    assert any("widen" in reason for reason in blockers)


def test_v1_1_trailing_requires_closed_atr_and_confirmed_break_even(manager, profile):
    spec = SymbolSpec(symbol="XAUUSD", point=0.01, tick_size=0.01, contract_size=100)
    not_confirmed = pos(sl=1999.0, points=300)
    action, blockers = manager.protection_candidate(
        not_confirmed, spec, plan(), profile, close_price=2003.0,
        atr_points=10, atr_is_closed=False, atr_age_seconds=1)
    assert action is not None and action.reason == "break_even_v1_1"
    assert any("closed-bar ATR" in reason for reason in blockers)
    confirmed = pos(sl=2000.15, points=300)
    trailing, _ = manager.protection_candidate(
        confirmed, spec, plan(), profile, close_price=2003.0,
        atr_points=10, atr_is_closed=True, atr_age_seconds=5)
    assert trailing is not None and trailing.reason == "trailing_v1_1"
    assert trailing.new_sl == pytest.approx(2002.9)


def test_v1_1_refuses_missing_initial_plan_and_bad_broker_stop_distance(manager, profile):
    spec = SymbolSpec(symbol="XAUUSD", point=0.01, tick_size=0.01, contract_size=100,
                      stops_level_points=30)
    action, blockers = manager.protection_candidate(
        pos(), spec, None, profile, close_price=2003.0)
    assert action is None and "initial plan" in blockers[0]
    close_to_price = pos(points=300, current=2000.3)
    action, blockers = manager.protection_candidate(
        close_to_price, spec, plan(), profile, close_price=2000.3)
    assert action is None
    assert any("stops/freeze" in reason for reason in blockers)


@pytest.mark.parametrize("mode,account_type", [
    ("MANUAL", "demo"), ("SEMI_AUTO", "demo"), ("FULL_AUTO", "demo"),
    ("HYBRID", "demo"), ("FULL_AUTO", "live"), ("HYBRID", "live"),
])
def test_v1_1_auto_modify_never_activates_from_staged_profile(manager, profile, mode, account_type):
    assert manager.automatic_protection_actions(
        [pos()], {"XAUUSD": SymbolSpec(symbol="XAUUSD")}, {"sig": plan()},
        profile, mode=mode, account_type=account_type,
        explicit_authorization=True, atr_points_by_symbol={"XAUUSD": 10},
        closed_atr_symbols={"XAUUSD"}) == []


def test_profile_and_migration_are_additive_and_fail_closed(profile):
    validate_v1_1_profile(profile)
    current = {"management": {"break_even": {"enabled": True, "trigger_points": 250},
                              "partials": {"enabled": True}}}
    before = repr(current)
    migration = migration_manifest(current, profile)
    assert repr(current) == before
    assert migration["active_config_changed"] is False
    assert migration["activation_required"] is True
    assert migration["legacy_management_preserved"] == current["management"]
    profile["automation"]["enabled"] = True
    with pytest.raises(ValueError, match="disabled"):
        validate_v1_1_profile(profile)
