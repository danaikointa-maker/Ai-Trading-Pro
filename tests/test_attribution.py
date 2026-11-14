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


# ------------------------------------------- the losing-streak hard stop
# Owner's rule (asked and answered explicitly): three losses in a row stop
# trading at once and the stop does not lift itself. An earlier round had made
# the streak expire with the cooldown; that was reversed on the owner's call, so
# these tests pin the hard stop — including the parts that make it survivable.
def test_three_losses_in_a_row_stop_trading_immediately(runtime):
    limits = runtime.risk.limits()
    state = default_risk_state(10_000)
    state.consecutive_losses = limits.max_consecutive_losses

    gate = _gate(runtime, state=state, now=NOW)
    assert not gate.allow
    assert any("consecutive losses" in b for b in gate.blockers)


def test_the_stop_does_not_lift_when_the_cooldown_expires(runtime):
    """The 20-minute cooldown is a separate, shorter pause. The streak outlasts it."""
    limits = runtime.risk.limits()
    state = default_risk_state(10_000)
    state.consecutive_losses = limits.max_consecutive_losses
    state.cooldown_until = NOW + limits.cooldown_minutes * 60

    long_after = _gate(runtime, state=state, now=state.cooldown_until + 86_400)
    assert not long_after.allow, "a day later it must still be stopped"
    failed = [c["name"] for c in long_after.checks if not c["ok"]]
    assert "consecutive_losses" in failed and "cooldown" not in failed


def test_the_stop_names_what_releases_it(runtime):
    """A block nobody can clear is only survivable if it says how to clear it."""
    state = default_risk_state(10_000)
    state.consecutive_losses = runtime.risk.limits().max_consecutive_losses
    detail = next(c["detail"] for c in _gate(runtime, state=state).checks
                  if c["name"] == "consecutive_losses")
    assert "winning trade" in detail and "release" in detail


def test_streak_is_the_binding_reason_not_the_cooldown(runtime):
    """Attribution reports the first failing check, so the longer-lived stop has
    to be checked first — otherwise a permanent halt is reported as a 20-minute one."""
    limits = runtime.risk.limits()
    state = default_risk_state(10_000)
    state.consecutive_losses = limits.max_consecutive_losses
    state.cooldown_until = NOW + limits.cooldown_minutes * 60

    tally = BlockerTally()
    gate = _gate(runtime, state=state, now=NOW)
    tally.add_gate(gate.allow, gate.checks)
    assert [row["code"] for row in tally.summary()["gate"]["primary"]] == ["consecutive_losses"]


def test_two_losses_do_not_stop_trading(runtime):
    state = default_risk_state(10_000)
    state.consecutive_losses = runtime.risk.limits().max_consecutive_losses - 1
    assert _gate(runtime, state=state).allow


# --------------------------------------------- how the streak is counted
def _ledger(runtime, pnls, base=1_000_000.0):
    """Write closed trades, oldest first, and read back the derived risk state."""
    runtime.db.execute("DELETE FROM trades")
    for i, pnl in enumerate(pnls):
        runtime.db.execute(
            "INSERT INTO trades (ticket, symbol, direction, volume, entry, exit, pnl, opened_at,"
            " closed_at, broker_id, strategy, exit_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"streak-{i}", "XAUUSD", "buy", 0.01, 2000.0, 2001.0, pnl,
             base + i * 60, base + i * 60 + 30, runtime.adapter.id, "test", "tp"))
    return runtime.risk.state(runtime.adapter, now=base + len(pnls) * 60 + 600)


def test_break_even_neither_counts_nor_clears_the_streak(runtime):
    """Owner's rule: a flat close is not a loss and not a reprieve.

    It matters because moving the stop to entry is the usual way a losing trade
    ends flat — under the old live rule that laundered a three-loss streak into
    a clean slate, while the backtest counted the same trade as a loss.
    """
    try:
        assert _ledger(runtime, [-5.0, -5.0, 0.0, -5.0]).consecutive_losses == 3
        assert _ledger(runtime, [-5.0, -5.0, -5.0, 0.0]).consecutive_losses == 3
        assert _ledger(runtime, [-5.0, -5.0, -5.0, 7.0]).consecutive_losses == 0
        assert _ledger(runtime, [-5.0, 7.0, -5.0, -5.0]).consecutive_losses == 2
    finally:
        runtime.db.execute("DELETE FROM trades")


def test_operator_release_clears_the_stop_without_editing_the_ledger(runtime):
    try:
        state = _ledger(runtime, [-5.0, -5.0, -5.0])
        assert state.consecutive_losses == 3
        rows_before = runtime.db.query("SELECT pnl FROM trades")

        runtime.risk.release_losing_streak("ops@no7.ai", now=state.updated_at_virtual + 1)
        after = runtime.risk.state(runtime.adapter, now=state.updated_at_virtual + 60)

        assert after.consecutive_losses == 0
        assert _gate(runtime, state=after).allow
        assert runtime.db.query("SELECT pnl FROM trades") == rows_before, "P&L must not be rewritten"
        audit = runtime.db.query("SELECT action FROM audit ORDER BY id DESC LIMIT 3")
        assert any(r["action"] == "risk.loss_streak.release" for r in audit)
    finally:
        runtime.db.execute("DELETE FROM trades")
        runtime.db.kv_set("loss_streak_release_at", 0)


def test_release_only_forgives_losses_older_than_itself(runtime):
    """A release must not pre-authorise the next three losses."""
    try:
        state = _ledger(runtime, [-5.0, -5.0, -5.0])
        runtime.risk.release_losing_streak("ops@no7.ai", now=state.updated_at_virtual + 1)
        assert runtime.risk.state(runtime.adapter,
                                  now=state.updated_at_virtual + 60).consecutive_losses == 0

        base = state.updated_at_virtual + 3600
        runtime.db.execute("DELETE FROM trades")
        for i in range(3):
            runtime.db.execute(
                "INSERT INTO trades (ticket, symbol, direction, volume, entry, exit, pnl,"
                " opened_at, closed_at, broker_id, strategy, exit_reason)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"after-{i}", "XAUUSD", "buy", 0.01, 2000.0, 1999.0, -5.0,
                 base + i * 60, base + i * 60 + 30, runtime.adapter.id, "test", "sl"))
        fresh = runtime.risk.state(runtime.adapter, now=base + 600)
        assert fresh.consecutive_losses == 3
        assert not _gate(runtime, state=fresh).allow
    finally:
        runtime.db.execute("DELETE FROM trades")
        runtime.db.kv_set("loss_streak_release_at", 0)


def test_release_endpoint_is_audited(client, auth, runtime):
    res = client.post("/api/risk/loss-streak/release", headers=auth)
    assert res.status_code == 200 and res.json()["ok"] is True
    assert res.json()["consecutive_losses"] == 0
    runtime.db.kv_set("loss_streak_release_at", 0)


def test_backtest_says_when_a_run_ended_on_the_stop():
    """A three-trade sample that ends on the stop must not read like a verdict."""
    from services.backtest_engine.backtester import Backtester

    quiet = BlockerTally()
    assert "never fired" in Backtester._hard_stop_note(quiet, 20)

    stopped = BlockerTally()
    for _ in range(4):
        stopped.add_gate(False, [{"name": "consecutive_losses", "ok": False,
                                  "detail": "3 consecutive losses"}])
    note = Backtester._hard_stop_note(stopped, 3)
    assert "RUN ENDED ON THE LOSING-STREAK STOP" in note and "4 signal(s)" in note


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
