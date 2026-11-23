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
