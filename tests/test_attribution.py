"""Every decision that does not become a trade must say why — in a countable form.

The measurement that motivated this file: on 20,000 simulated M1 bars the engine
analysed ~1,630 decision points and opened ~20 trades, and the report could only
say how many died at each stage, never which rule did the killing. These tests
pin the parts of that answer that are easy to break silently: the codes travel
with the prose, the buckets add up, an unregistered reason is visible instead of
absorbed, and the losing-streak limit cannot deadlock the system again.
"""
from __future__ import annotations

import time

from packages.shared_schemas.models import Health, SymbolSpec
from services.risk_engine.engine import default_risk_state
from services.strategy_engine.attribution import (
    BLOCKER_CODES,
    CODE_ORDER,
    BlockerTally,
    merge,
    normalise,
)

SPEC = SymbolSpec(
    symbol="XAUUSD", digits=2, point=0.01, tick_size=0.01, contract_size=100.0,
    min_lot=0.01, max_lot=50.0, lot_step=0.01, stops_level_points=0.0, spread_typical_points=25.0,
)
OK_QUALITY = {"ok": True, "reason": "", "staleness_seconds": 1.0}
NO_NEWS = {"active": False, "reason": ""}
NOW = time.time()


def _gate(runtime, **overrides):
    state = overrides.pop("state", default_risk_state(10_000))
    kwargs = dict(
        state=state, spec=SPEC, spread_points=25.0, data_quality=OK_QUALITY,
        news_lockout=NO_NEWS, atr_pct=0.6, requested_lot=0.10,
        broker_health=Health.connected, now=NOW,
    )
    kwargs.update(overrides)
    return runtime.risk.gate(**kwargs)


# --------------------------------------------------------------- the taxonomy
def test_codes_are_unique_and_ordered():
    codes = [c for c, _ in BLOCKER_CODES]
    assert len(codes) == len(set(codes)), "a duplicate code would merge two causes"
    assert list(CODE_ORDER) == codes


def test_unknown_code_is_flagged_not_merged():
    assert normalise("score_below_execute") == "score_below_execute"
    assert normalise("brand_new_rule") == "unregistered:brand_new_rule"
    assert normalise("") == "unregistered:empty"


# ------------------------------------------------------------------ the tally
def test_primary_buckets_sum_to_blocked_decisions():
    tally = BlockerTally()
    tally.add_signal(True)
    tally.add_signal(False, ["entry_conditions"], ["entry conditions are not all satisfied"])
    # one decision tripping three rules must still count as exactly one block
    tally.add_signal(False, ["score_below_execute", "reward_risk", "news_lockout"],
                     ["score 40 below 70", "rr 1.1 below 1.3", "CPI in 5 minutes"])
    summary = tally.summary()["signal"]

    assert summary == {**summary, "decisions": 3, "actionable": 1, "blocked": 2}
    assert sum(row["count"] for row in summary["primary"]) == summary["blocked"]
    # `fired` counts every objection, so it may exceed the number of decisions
    assert sum(row["count"] for row in summary["fired"]) == 4


def test_primary_picks_the_most_binding_reason():
    """A news lockout outranks a score threshold: tuning the score would not have
    helped, and that is the whole point of reporting a primary cause."""
    tally = BlockerTally()
    tally.add_signal(False, ["score_below_execute", "news_lockout"], ["score", "news"])
    primary = tally.summary()["signal"]["primary"]
    assert [row["code"] for row in primary] == ["news_lockout"]


def test_blocked_decision_without_any_reason_is_itself_reported():
    tally = BlockerTally()
    tally.add_signal(False, [], [])
    codes = [row["code"] for row in tally.summary()["signal"]["primary"]]
    assert codes == ["unregistered:no_reason_given"]
    assert "warning" in tally.summary()


def test_samples_keep_the_live_numbers_without_becoming_buckets():
    tally = BlockerTally()
    for score in (41, 42, 43):
        tally.add_signal(False, ["score_below_execute"], [f"signal score {score} is below 70"])
    rows = tally.summary()["signal"]["primary"]
    assert len(rows) == 1 and rows[0]["count"] == 3, "prose must not split the bucket"
    assert len(rows[0]["samples"]) == 2, "a couple of examples, not a log"


def test_gate_tally_uses_check_names_and_first_failure_wins():
    tally = BlockerTally()
    tally.add_gate(True, [{"name": "spread", "ok": True, "detail": ""}])
    tally.add_gate(False, [
        {"name": "kill_switch", "ok": True, "detail": ""},
        {"name": "cooldown", "ok": False, "detail": "cooldown until 06:20"},
        {"name": "consecutive_losses", "ok": False, "detail": "3 consecutive losses"},
    ])
    gate = tally.summary()["gate"]
    assert (gate["evaluated"], gate["allowed"], gate["blocked"]) == (2, 1, 1)
    assert [row["code"] for row in gate["primary"]] == ["cooldown"]
    assert {row["code"] for row in gate["fired"]} == {"cooldown", "consecutive_losses"}


def test_merge_preserves_totals():
    a, b = BlockerTally(), BlockerTally()
    a.add_signal(False, ["entry_conditions"], ["x"])
    a.add_signal(True)
    b.add_signal(False, ["entry_conditions"], ["y"])
    b.add_gate(False, [{"name": "spread", "ok": False, "detail": "wide"}])
    out = merge([a, b]).summary()
    assert out["signal"]["decisions"] == 3
    assert out["signal"]["primary"][0]["count"] == 2
    assert out["gate"]["blocked"] == 1


def test_empty_tally_says_so_instead_of_dividing_by_zero():
    summary = BlockerTally().summary()
    assert summary["signal"]["primary"] == [] and summary["gate"]["primary"] == []
    assert "nothing to attribute" in BlockerTally().note()


# ------------------------------------------------- codes at the point of origin
def test_strategy_blockers_carry_codes_one_for_one(runtime):
    """Prose and codes must stay parallel, or the report attributes the wrong rule."""
    seen = False
    for symbol in runtime.symbols()[:3]:
        ctx = runtime.analysis.snapshot(symbol)
        signal = runtime.strategy.generate(
            ctx, symbol, runtime.adapter.id, runtime.mode, runtime.market.ticker(symbol),
            Health.connected, None, 10_000.0, now=time.time())
        assert len(signal.blocker_codes) == len(signal.blockers), signal.blockers
        for code in signal.blocker_codes:
            assert not normalise(code).startswith("unregistered:"), f"{code} is not in the table"
        if signal.blockers:
            seen = True
    assert seen, "no symbol produced a blocker, so nothing was actually checked"


def test_planner_blockers_carry_codes(runtime):
    from packages.shared_schemas.models import Direction

    spec = runtime.adapter.symbol_spec("XAUUSD")
    from services.risk_engine.planner import PlanInputs

    result = runtime.planner.build(PlanInputs(
        spec=spec, direction=Direction.up, entry=2000.0, atr_points=100.0,
        spread_points=25.0, equity=10_000.0, risk_pct=0.5,
        supports=[], resistances=[],
        # a reward/risk floor nothing can satisfy, so the planner must refuse
        min_rr_net=99.0, sl_min_points=50.0, sl_max_points=400.0,
    ))
    assert result.plan is None and result.blockers
    assert len(result.blocker_codes) == len(result.blockers)
    assert "reward_risk" in result.blocker_codes


# ------------------------------------------------------- the deadlock, pinned
def test_losing_streak_stops_blocking_once_the_cooldown_expires(runtime):
    """`max_consecutive_losses` starts a cooldown (risk.yaml: "then cooldown").

    As an independent hard check it deadlocked the engine: the streak only clears
    on a winning trade and no trade can open while it blocks, so three losses
    ended trading permanently. Measured on identical 20k-bar samples, that cost
    4 of 23 actionable signals and turned the run into a smaller, worse sample.
    """
    limits = runtime.risk.limits()
    state = default_risk_state(10_000)
    state.consecutive_losses = limits.max_consecutive_losses + 2

    state.cooldown_until = NOW + limits.cooldown_minutes * 60
    during = _gate(runtime, state=state, now=NOW)
    assert not during.allow, "a fresh losing streak must pause trading"
    assert any("consecutive losses" in b for b in during.blockers)

    after = _gate(runtime, state=state, now=state.cooldown_until + 1)
    assert after.allow, "the pause must end when the cooldown ends, not on a win"
    # the streak is still true and still worth seeing — as a warning, not a veto
    assert any("consecutive losses" in w for w in after.warnings)
    assert any(c["name"] == "consecutive_losses" and not c["ok"] for c in after.checks)


def test_streak_without_cooldown_does_not_veto(runtime):
    """No cooldown timestamp means no active pause — the counter alone must not
    hold the system down."""
    state = default_risk_state(10_000)
    state.consecutive_losses = runtime.risk.limits().max_consecutive_losses + 5
    state.cooldown_until = None
    gate = _gate(runtime, state=state)
    assert gate.allow, gate.blockers


# ------------------------------------------------------------- the live surface
def test_live_attribution_endpoint_reports_reasons(client, auth, runtime):
    runtime.reset_attribution()
    for symbol in runtime.symbols()[:2]:
        runtime._decide_symbol(symbol, 10_000.0, Health.connected,
                               runtime.risk.state(runtime.adapter), time.time())

    res = client.get("/api/system/attribution", headers=auth)
    assert res.status_code == 200
    body = res.json()
    assert body["overall"]["signal"]["decisions"] >= 1
    assert body["headline"]
    assert set(body["per_symbol"]) == set(body["symbols"])
    blocked = body["overall"]["signal"]["blocked"]
    assert sum(r["count"] for r in body["overall"]["signal"]["primary"]) == blocked


def test_attribution_reset_starts_a_new_window(client, auth, runtime):
    runtime._decide_symbol(runtime.symbols()[0], 10_000.0, Health.connected,
                           runtime.risk.state(runtime.adapter), time.time())
    assert runtime.attribution_summary()["overall"]["signal"]["decisions"] >= 1

    res = client.post("/api/system/attribution/reset", headers=auth)
    assert res.status_code == 200
    assert res.json()["overall"]["signal"]["decisions"] == 0
    assert runtime.attribution_summary()["window_seconds"] < 5


def test_attribution_requires_authentication(client):
    assert client.get("/api/system/attribution").status_code == 401
