"""`generate()` must survive the path that actually builds a trade plan.

`PlanInputs` was constructed with a name (`atr_points`) that only existed inside
`_evaluate_entry`, where it was never used. The moment the market produced a
direction — the only path that reaches `planner.build()` — `generate()` died with
NameError, so the platform could analyse all day and never hand a plan to the
risk engine. Analysis cycles that stay `sideways` never touched it, which is why
the suite was green.
"""
from __future__ import annotations

from packages.shared_schemas.models import Direction, Health, TradeMode


def test_plan_path_runs_and_receives_a_real_atr(runtime, monkeypatch):
    seen: dict[str, float] = {}
    real_build = runtime.strategy.planner.build

    def spy(inputs):
        seen["atr_points"] = inputs.atr_points
        return real_build(inputs)

    monkeypatch.setattr(runtime.strategy, "_candidate_direction",
                        lambda ctx: (Direction.up, ["forced direction for the test"]))
    monkeypatch.setattr(runtime.strategy.planner, "build", spy)

    ctx = runtime.analysis.snapshot("XAUUSD")
    tick = runtime.market.ticker("XAUUSD")
    equity = float(runtime.adapter.account_info().equity)

    signal = runtime.strategy.generate(
        ctx, "XAUUSD", runtime.adapter.id, TradeMode.manual, tick, Health.connected,
        None, equity, now=None,
    )

    assert signal.symbol == "XAUUSD"
    assert seen, "planner.build() was never reached — the plan path did not run"
    assert seen["atr_points"] >= 1.0
    if signal.plan is not None:
        assert signal.plan.sl_points > 0
        assert signal.plan.lot > 0


def test_satisfied_entry_still_gets_plan_settings(runtime, monkeypatch):
    """When entry conditions *are* met the plan must still be built.

    `risk_settings` was assigned only inside `if not entry.ok:`, so the moment a
    setup actually qualified, generate() raised UnboundLocalError and the symbol
    was logged as a decision error instead of producing a signal.
    """
    from services.strategy_engine.engine import EntryEvaluation

    seen: list[float] = []
    real_build = runtime.strategy.planner.build

    def spy(inputs):
        seen.append(inputs.entry)
        return real_build(inputs)

    monkeypatch.setattr(runtime.strategy, "_candidate_direction",
                        lambda ctx: (Direction.up, ["forced"]))
    monkeypatch.setattr(runtime.strategy, "_evaluate_entry",
                        lambda ctx, direction, spec: EntryEvaluation(True, "trend_pullback"))
    monkeypatch.setattr(runtime.strategy.planner, "build", spy)

    ctx = runtime.analysis.snapshot("XAUUSD")
    tick = runtime.market.ticker("XAUUSD")
    equity = float(runtime.adapter.account_info().equity)

    signal = runtime.strategy.generate(
        ctx, "XAUUSD", runtime.adapter.id, TradeMode.manual, tick, Health.connected,
        None, equity, now=None,
    )

    assert seen, "planner.build() never ran with a satisfied entry"
    assert "entry conditions are not all satisfied" not in signal.blockers
