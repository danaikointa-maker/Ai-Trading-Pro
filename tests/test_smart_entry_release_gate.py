"""Release checks never promote simulated performance or skip broker evidence."""
from __future__ import annotations

from copy import deepcopy

from services.backtest_engine.release_gate import assess_release


def report(spread=20, slip=2):
    return {"symbol": "XAUUSD", "broker_id": "demo", "bars": 8000,
            "from_t": 100, "to_t": 500,
            "dataset": {"sha256": "a" * 64, "source": "imported broker candles",
                        "reproducible": True},
            "metrics": {"trades": 50, "profit_factor": 1.5, "expectancy": 3.0,
                        "max_drawdown_pct": 4.0},
            "walk_forward": [{"trades": 12, "expectancy": 2.0} for _ in range(4)],
            "diagnostics": {"cost_assumptions": {"spread_points": spread,
                                                   "slippage_points": slip},
                            "intra_bar": {"mode": "ticks", "available": True}}}


def demo_evidence():
    return {"account_type": "demo", "broker_id": "demo", "forward_days": 21,
            "closed_trades": 40, "account_identity_verified": True,
            "all_fills_verified": True, "partial_fills_reconciled": True,
            "restarts_reconciled": True, "disconnects_reconciled": True,
            "manual_changes_reconciled": True, "unresolved_orders": 0}


def test_readiness_requires_evidence_and_never_enables_live():
    outcome = assess_release(report(), [report(40, 4), report(60, 10)], demo_evidence())
    assert outcome["passed"] is True
    assert outcome["state"] == "ready_for_operator_review"
    assert outcome["operator_review_required"] is True
    assert outcome["live_auto_enabled"] is False


def test_simulated_bars_or_no_demo_block_release():
    sample = report()
    sample["dataset"]["source"] = "simulated GBM feed"
    outcome = assess_release(sample, [report(40, 4), report(60, 10)], None)
    assert outcome["passed"] is False
    assert any("simulated" in reason for reason in outcome["failures"])
    assert any("Demo" in reason for reason in outcome["failures"])


def test_stress_must_use_same_dataset_and_be_more_expensive():
    stress = [report(20, 2), report(60, 10)]
    stress[1]["dataset"]["sha256"] = "b" * 64
    outcome = assess_release(report(), stress, demo_evidence())
    assert not outcome["passed"]
    assert any("strictly more adverse" in reason for reason in outcome["failures"])
    assert any("same immutable dataset" in reason for reason in outcome["failures"])


def test_missing_tick_evidence_blocks_even_good_metrics():
    sample = deepcopy(report())
    sample["diagnostics"]["intra_bar"] = {"mode": "conservative"}
    assert not assess_release(sample, [report(40, 4), report(60, 10)], demo_evidence())["passed"]


def test_malformed_nested_evidence_and_boolean_counts_fail_closed():
    malformed = report()
    malformed["walk_forward"] = [None]
    malformed["diagnostics"]["cost_assumptions"] = "unknown"
    blocked = assess_release(malformed, [report(40, 4), report(60, 10)], demo_evidence())
    assert blocked["state"] == "blocked"
    assert blocked["live_auto_enabled"] is False
    sample = report()
    sample["bars"] = True
    sample["metrics"]["trades"] = True
    assert not assess_release(sample, [report(40, 4), report(60, 10)], demo_evidence())["passed"]
