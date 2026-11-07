"""A model must show its edge in *most* chronological blocks, not one lucky split.

Approval used to hinge on a single out-of-sample slice, so the flag flipped
between runs on the same kind of data. The rule is now stricter (a majority of
folds must clear the same bar), never looser.
"""
from __future__ import annotations

import pytest

from services.ai_forecast.trainer import ForecastTrainer, decide_approval, split_folds


def fold(dir_acc: float, improvement: float, passing: bool | None = None) -> dict:
    return {
        "n": 100,
        "directional_accuracy": dir_acc,
        "brier_improvement": improvement,
        "pass": (dir_acc >= 0.52 and improvement >= 0.02) if passing is None else passing,
    }


# ------------------------------------------------------------------ splitting
def test_folds_are_contiguous_and_cover_every_row():
    blocks = split_folds(103, 4)
    assert blocks[0][0] == 0
    assert blocks[-1][1] == 103
    for (lo, hi), (next_lo, _) in zip(blocks, blocks[1:]):
        assert hi == next_lo, "folds must not overlap or leave gaps"
    assert sum(hi - lo for lo, hi in blocks) == 103


def test_fold_count_is_bounded_by_rows():
    assert len(split_folds(3, 4)) == 3
    assert split_folds(0, 4) == []
    assert len(split_folds(100, 1)) == 1


# ------------------------------------------------------------------- approval
def test_all_folds_passing_is_approved():
    ok, summary = decide_approval([fold(0.58, 0.05)] * 4, 0.52, 0.02, 0.75)
    assert ok is True
    assert summary["fold_pass_rate"] == 1.0
    assert summary["folds_used"] == 4


def test_one_lucky_fold_is_not_enough():
    """The old rule approved this: overall numbers look fine, half the folds fail."""
    ok, summary = decide_approval([fold(0.70, 0.09), fold(0.50, 0.01),
                                   fold(0.49, -0.01), fold(0.51, 0.005)], 0.52, 0.02, 0.75)
    assert ok is False
    assert summary["fold_pass_rate"] == 0.25


def test_median_fold_must_clear_the_bar():
    # 3 of 4 pass, but the median improvement is below the threshold.
    ok, _ = decide_approval([fold(0.60, 0.05), fold(0.58, 0.04),
                             fold(0.53, 0.005), fold(0.54, 0.01)], 0.52, 0.02, 0.75)
    assert ok is False


def test_no_folds_is_never_approved():
    ok, summary = decide_approval([], 0.52, 0.02, 0.75)
    assert ok is False
    assert summary["folds_used"] == 0


# ------------------------------------------------------------- real training run
@pytest.fixture(scope="module")
def trained(settings):
    from services.market_data.simulator import SyntheticFeed

    feed = SyntheticFeed({"XAUUSD": {"digits": 2, "point": 0.01, "contract_size": 100}},
                         history_bars=20000, seed=7)
    trainer = ForecastTrainer(settings)
    trainer.horizons = [5]      # one horizon keeps this test at ~1s
    trainer.max_rows = 12000
    return trainer.train(feed.warm_history("XAUUSD", 20000), "TEST-FOLDS")


def test_training_reports_chronological_folds(trained):
    metrics = trained.metrics["horizons"]["5"]
    folds = metrics["validation_folds"]
    assert len(folds) == 4
    assert all({"n", "directional_accuracy", "brier_improvement", "pass"} <= set(f) for f in folds)
    assert metrics["folds_used"] == 4
    assert 0.0 <= metrics["fold_pass_rate"] <= 1.0


def test_approval_matches_the_fold_summary(trained):
    metrics = trained.metrics["horizons"]["5"]
    expected = (metrics["fold_pass_rate"] >= 0.75
                and metrics["fold_directional_median"] >= 0.52
                and metrics["fold_brier_improvement_median"] >= 0.02
                and metrics["directional_accuracy"] >= 0.52
                and metrics["brier_improvement"] >= 0.02)
    assert metrics["approved"] is bool(expected)


def test_overall_result_states_the_method_honestly(trained):
    assert "NOT retrained per fold" in trained.metrics["validation"]
    assert trained.metrics["validation_folds"] == 4
