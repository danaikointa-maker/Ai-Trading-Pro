"""A single-TP candidate must never trigger a local partial close."""
from __future__ import annotations

from types import SimpleNamespace
from typing import ClassVar

from integrations.brokers.paper import PaperBroker
from packages.persistence.db import Database
from packages.shared_schemas.models import (
    Direction,
    OrderRequest,
    OrderSide,
    PartialTarget,
    Position,
    SymbolSpec,
    Tick,
)
from services.execution_gateway.gateway import ExecutionGateway
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
            def risk_cfg(trail_step=step_points):
                return {"management": {
                    "break_even": {"enabled": False},
                    "trailing": {"enabled": True, "start_after_points": 500,
                                 "mode": "fixed", "distance_points": 100,
                                 "step_points": trail_step},
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


def test_paper_protection_action_uses_gateway_and_confirms_broker_readback(tmp_path):
    clock = [1000.0]

    class Feed:
        bid = 2000.0
        ask = 2000.2

        def ticker(self, _symbol):
            return Tick(t=clock[0], bid=self.bid, ask=self.ask,
                        spread_points=20, last=(self.bid + self.ask) / 2)

    class RuntimeSettings:
        execution: ClassVar[dict[str, int]] = {"position_modify_max_quote_age_seconds": 10}

    spec = _spec()
    profile = {"id": "paper-protection", "symbols": {
        "XAUUSD": {name: getattr(spec, name) for name in (
            "digits", "point", "tick_size", "contract_size", "min_lot", "max_lot",
            "lot_step", "stops_level_points", "freeze_level_points", "profit_currency",
            "account_currency", "spec_complete")}}}
    feed = Feed()
    adapter = PaperBroker(profile, feed, starting_balance=10_000, clock=lambda: clock[0])
    db = Database(tmp_path / "paper-protection.sqlite3")
    try:
        opened = ExecutionGateway(RuntimeSettings(), db).submit(adapter, OrderRequest(
            symbol="XAUUSD", side=OrderSide.buy, volume=0.1, sl=1990, tp=2020,
            signal_id="paper-protection-1"))
        assert opened.status.value == "filled"
        assert opened.verified is True

        feed.bid, feed.ask = 2008.0, 2008.2
        positions = adapter.positions()
        actions = _protection_manager().evaluate(
            positions, {"XAUUSD": adapter.symbol_spec("XAUUSD")}, {}, None,
            now=clock[0], atr_points=100)
        modify = next(action for action in actions if action.kind == "modify")
        assert modify.new_sl > positions[0].sl

        assert ExecutionGateway(RuntimeSettings(), db).modify(
            adapter, modify.ticket, sl=modify.new_sl, reason=modify.reason)
        updated = adapter.positions()[0]
        assert updated.sl == modify.new_sl
        assert updated.tp == 2020
        assert db.query_one(
            "SELECT state FROM position_modify_intents WHERE broker_id=? AND ticket=?",
            (adapter.id, modify.ticket))["state"] == "confirmed"
    finally:
        db.close()
