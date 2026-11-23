"""A single-TP candidate must never trigger a local partial close."""
from __future__ import annotations

from types import SimpleNamespace

from packages.shared_schemas.models import (
    Direction,
    PartialTarget,
    Position,
    SymbolSpec,
)
from services.risk_engine.manager import PositionManager


class _Settings:
    @staticmethod
    def risk_cfg():
        return {"management": {
            "break_even": {"enabled": False},
            "trailing": {"enabled": False},
            "time_exit": {"enabled": False},
            "smart_exit": {"enabled": False},
            "partials": {"enabled": True},
        }}


def test_single_2r_plan_skips_partial_even_when_legacy_switch_is_on():
    manager = PositionManager(_Settings())
    target = PartialTarget(level=1, price=2010, points=10, close_pct=100,
                           volume=0.1, feasible=True)
    plan = SimpleNamespace(plan=SimpleNamespace(
        target_mode="single_2r", partials=[target], tp_points=[10]))
    position = Position(
        ticket="42", symbol="XAUUSD", direction=Direction.up, volume=0.1,
        entry=2000, sl=1990, tp=2010, open_time=1, current_price=2000.2,
        points=20, signal_id="candidate-42",
    )
    spec = SymbolSpec(symbol="XAUUSD", digits=2, point=0.01, tick_size=0.01,
                      contract_size=100, min_lot=0.01, lot_step=0.01)

    actions = manager.evaluate(
        [position], {"XAUUSD": spec}, {"candidate-42": plan}, None, now=2)

    assert actions == []


def test_legacy_ladder_still_allows_configured_partial_close():
    manager = PositionManager(_Settings())
    target = PartialTarget(level=1, price=2010, points=10, close_pct=40,
                           volume=0.04, feasible=True)
    plan = SimpleNamespace(plan=SimpleNamespace(
        target_mode="adaptive", partials=[target], tp_points=[10]))
    position = Position(
        ticket="43", symbol="XAUUSD", direction=Direction.up, volume=0.1,
        entry=2000, sl=1990, tp=2010, open_time=1, current_price=2000.2,
        points=20, signal_id="legacy-43",
    )
    spec = SymbolSpec(symbol="XAUUSD", digits=2, point=0.01, tick_size=0.01,
                      contract_size=100, min_lot=0.01, lot_step=0.01)

    actions = manager.evaluate([position], {"XAUUSD": spec},
                               {"legacy-43": plan}, None, now=2)

    assert len(actions) == 1
    assert actions[0].kind == "partial_close"
    assert actions[0].volume == 0.04


def _protection_manager():
    class Settings:
        @staticmethod
        def risk_cfg():
            return {"management": {
                "break_even": {"enabled": True, "trigger_points": 250, "lock_points": 30},
                "trailing": {"enabled": True, "start_after_points": 500,
                             "mode": "atr", "atr_multiplier": 1.0,
                             "step_points": 50},
                "time_exit": {"enabled": False},
                "smart_exit": {"enabled": False},
                "partials": {"enabled": False},
            }}

    return PositionManager(Settings())


def _spec():
    return SymbolSpec(symbol="XAUUSD", digits=2, point=0.01, tick_size=0.01,
                      contract_size=100, min_lot=0.01, lot_step=0.01,
                      spread_typical_points=2)


def test_be_and_trailing_reduce_to_one_safest_buy_modify():
    position = Position(
        ticket="buy-1", symbol="XAUUSD", direction=Direction.up, volume=0.1,
        entry=2000, sl=1990, tp=2020, open_time=1, current_price=2008,
        points=800,
    )

    actions = _protection_manager().evaluate(
        [position], {"XAUUSD": _spec()}, {}, None, now=2, atr_points=100)

    modifications = [action for action in actions if action.kind == "modify"]
    assert len(modifications) == 1
    assert modifications[0].reason == "trailing_stop"
    assert modifications[0].new_sl == 2007


def test_be_and_trailing_reduce_to_one_safest_sell_modify():
    position = Position(
        ticket="sell-1", symbol="XAUUSD", direction=Direction.down, volume=0.1,
        entry=2000, sl=2010, tp=1980, open_time=1, current_price=1992,
        points=800,
    )

    actions = _protection_manager().evaluate(
        [position], {"XAUUSD": _spec()}, {}, None, now=2, atr_points=100)

    modifications = [action for action in actions if action.kind == "modify"]
    assert len(modifications) == 1
    assert modifications[0].reason == "trailing_stop"
    assert modifications[0].new_sl == 1993


def test_protection_does_not_widen_or_remove_existing_stop():
    manager = _protection_manager()
    positions = [
        Position(ticket="buy-2", symbol="XAUUSD", direction=Direction.up,
                 volume=0.1, entry=2000, sl=2007.5, tp=2020, open_time=1,
                 current_price=2008, points=800),
        Position(ticket="sell-2", symbol="XAUUSD", direction=Direction.down,
                 volume=0.1, entry=2000, sl=1992.5, tp=1980, open_time=1,
                 current_price=1992, points=800),
    ]

    actions = manager.evaluate(positions, {"XAUUSD": _spec()}, {}, None,
                               now=2, atr_points=100)

    assert not [action for action in actions if action.kind == "modify"]


def test_protection_fails_closed_when_current_stop_is_missing():
    position = Position(
        ticket="unknown-sl", symbol="XAUUSD", direction=Direction.up,
        volume=0.1, entry=2000, sl=0, tp=2020, open_time=1,
        current_price=2008, points=800,
    )

    actions = _protection_manager().evaluate(
        [position], {"XAUUSD": _spec()}, {}, None, now=2, atr_points=100)

    assert not [action for action in actions if action.kind == "modify"]


def test_trailing_requires_strict_improvement_even_with_zero_or_negative_step():
    for step_points in (0, -10):
        class Settings:
            @staticmethod
            def risk_cfg():
                return {"management": {
                    "break_even": {"enabled": False},
                    "trailing": {"enabled": True, "start_after_points": 500,
                                 "mode": "fixed", "distance_points": 100,
                                 "step_points": step_points},
                    "time_exit": {"enabled": False},
                    "smart_exit": {"enabled": False},
                    "partials": {"enabled": False},
                }}

        manager = PositionManager(Settings())
        position = Position(
            ticket=f"same-sl-{step_points}", symbol="XAUUSD",
            direction=Direction.up, volume=0.1, entry=2000, sl=2007,
            tp=2020, open_time=1, current_price=2008, points=800,
        )

        actions = manager.evaluate([position], {"XAUUSD": _spec()}, {}, None,
                                   now=2, atr_points=100)

        assert not [action for action in actions if action.kind == "modify"]
