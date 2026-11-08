"""The backtest may use the trained model — but never a model that saw the answer.

These tests pin the three things that make a model-driven backtest meaningful:
the training window stops a full label horizon before the bars it predicts, the
model's numbers really reach the decision loop, and the report says which forecast
made each decision instead of implying the model everywhere.

They also pin the risk bookkeeping the simulation shares with the live engine:
day and week boundaries, the weekly trade cap, and the cooldown clock.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from packages.shared_schemas.models import BacktestRequest
from services.backtest_engine.backtester import Backtester
from services.backtest_engine.model_edge import Prediction, WalkForwardEdge
from services.market_data.simulator import SyntheticFeed

BARS = 6000


@pytest.fixture(scope="module")
def engine(runtime, settings):
    feed = SyntheticFeed({"XAUUSD": {"digits": 2, "point": 0.01, "contract_size": 100}},
                         history_bars=BARS, seed=11)
    candles = feed.warm_history("XAUUSD", BARS)
    spec = runtime.adapter.symbol_spec("XAUUSD")
    return Backtester(settings, runtime.risk, runtime.planner), candles, spec


@pytest.fixture(scope="module")
def proxy_report(engine):
    """One rule-proxy run, shared: each full backtest costs ~17 seconds."""
    backtester, candles, spec = engine
    return backtester.run(candles, spec, BacktestRequest(symbol="XAUUSD", bars=BARS))


@pytest.fixture(scope="module")
def model_report(engine):
    backtester, candles, spec = engine
    return backtester.run(candles, spec,
                          BacktestRequest(symbol="XAUUSD", bars=BARS, forecast_source="model"))


@pytest.fixture(scope="module")
def m5_frame(engine):
    from packages.indicators.pipeline import enrich
    from services.market_data.simulator import resample

    _, candles, _ = engine
    return enrich(resample(candles, "M5"))


@pytest.fixture(scope="module")
def prepared_edge(settings, m5_frame):
    edge = WalkForwardEdge(settings, horizon_minutes=30, segments=4)
    edge.prepare(m5_frame, first_bar=320)
    return edge


# --------------------------------------------------------------- no look-ahead
def test_training_stops_a_full_label_horizon_before_the_segment(prepared_edge):
    """Row j's label reads bar j+hb, so training on j >= start-hb leaks the answer."""
    hb = prepared_edge.horizon_bars
    assert hb == 6, "30 minutes of M5 bars"
    for seg in prepared_edge._segments:
        rows = prepared_edge._training_slice(seg.start_bar)
        if rows.size == 0:
            continue
        last_label_bar = int(rows.max()) + hb
        assert last_label_bar < seg.start_bar, (
            f"segment {seg.index} trained on a row whose label extends to bar "
            f"{last_label_bar}, inside the block it must predict")


def test_a_model_never_scores_a_bar_it_was_fitted_on(prepared_edge):
    for seg in prepared_edge._segments:
        rows = prepared_edge._training_slice(seg.start_bar)
        if rows.size:
            assert int(rows.max()) < seg.start_bar


def test_missing_features_are_filled_from_the_training_window_not_the_future(settings, m5_frame):
    """The whole frame's median is a summary of bars the model has not earned yet."""
    edge = WalkForwardEdge(settings, horizon_minutes=30, segments=2, min_train_rows=50)
    edge.prepare(m5_frame, first_bar=320)
    seg = edge._segments[-1]
    edge._fit(seg)
    assert seg.trained, seg.reason

    from services.ai_forecast.features import FEATURE_COLUMNS

    rows = edge._training_slice(seg.start_bar)
    train_X = edge._features[FEATURE_COLUMNS].to_numpy(float)[rows]
    assert np.allclose(seg.median, np.nanmedian(train_X, axis=0), equal_nan=True)

    whole_frame = np.nanmedian(edge._features[FEATURE_COLUMNS].to_numpy(float), axis=0)
    assert not np.allclose(seg.median, whole_frame), (
        "training median equals the full-frame median — the test cannot tell them apart")


def test_the_first_segment_runs_without_approval(prepared_edge, m5_frame):
    """Nothing has validated it yet, so it must behave like an unapproved model."""
    first = prepared_edge._segments[0]
    assert first.approved is False


def test_approval_is_earned_on_folds_that_already_finished(settings, m5_frame):
    edge = WalkForwardEdge(settings, horizon_minutes=30, segments=3, min_train_rows=50)
    edge.prepare(m5_frame, first_bar=320)
    labels = edge._labels
    # Feed it a perfect track record on bars whose labels completed long ago.
    scored = 0
    for bar in range(320, 500):
        truth = labels[bar]
        if not np.isfinite(truth) or truth == 0.0:
            continue
        edge.observe(bar, p_up=1.0 if truth > 0 else 0.0, p_down=0.0 if truth > 0 else 1.0,
                     source="model", proxy_p_up=0.5, proxy_p_down=0.5)
        scored += 1
    assert scored >= 30, "not enough non-sideways bars to judge approval"
    acc, n = edge._known_accuracy(before_bar=900)
    assert n == scored and acc == 1.0

    later = [s for s in edge._segments if s.start_bar >= 900]
    if later:
        seg = later[0]
        edge.predict(seg.start_bar)
        assert seg.approved is True, "a perfect past record should promote the next segment"


def test_a_bad_track_record_does_not_promote_the_next_segment(settings, m5_frame):
    edge = WalkForwardEdge(settings, horizon_minutes=30, segments=3, min_train_rows=50)
    edge.prepare(m5_frame, first_bar=320)
    labels = edge._labels
    for bar in range(320, 500):
        truth = labels[bar]
        if not np.isfinite(truth) or truth == 0.0:
            continue
        # Always wrong.
        edge.observe(bar, p_up=0.0 if truth > 0 else 1.0, p_down=1.0 if truth > 0 else 0.0,
                     source="model", proxy_p_up=0.5, proxy_p_down=0.5)
    later = [s for s in edge._segments if s.start_bar >= 900]
    if later:
        seg = later[0]
        edge.predict(seg.start_bar)
        assert seg.approved is False


def test_probabilities_are_a_distribution(prepared_edge):
    hits = 0
    for seg in prepared_edge._segments:
        for bar in range(seg.start_bar, min(seg.start_bar + 8, seg.end_bar)):
            got = prepared_edge.predict(bar)
            if got is None:
                continue
            hits += 1
            assert 0.0 <= got.p_up <= 1.0 and 0.0 <= got.p_down <= 1.0 and 0.0 <= got.p_side <= 1.0
            assert got.p_up + got.p_down + got.p_side == pytest.approx(1.0, abs=1e-9)
    assert hits, "no segment produced a prediction — the fixture trained nothing"


def test_a_segment_without_enough_history_degrades_to_the_proxy(settings, m5_frame):
    edge = WalkForwardEdge(settings, horizon_minutes=30, segments=4, min_train_rows=10_000)
    edge.prepare(m5_frame, first_bar=320)
    assert edge.predict(400) is None, "an unfittable segment must not answer"
    seg = edge._segments[0]
    assert seg.trained is False and "need 10000" in seg.reason


# -------------------------------------------------------- reaches the decision
def test_the_model_forecast_changes_what_the_engine_does(engine, proxy_report, monkeypatch):
    """If swapping the forecast changed nothing, the whole exercise would be theatre."""
    backtester, candles, spec = engine
    base = proxy_report

    def confident_bull(self, i):
        seg = self._segment_for(i)
        if seg is None:
            return None
        seg.decisions += 1
        return Prediction(p_up=0.93, p_side=0.04, p_down=0.03, approved=True, segment=seg.index)

    monkeypatch.setattr(WalkForwardEdge, "predict", confident_bull)
    forced = backtester.run(candles, spec,
                            BacktestRequest(symbol="XAUUSD", bars=BARS, forecast_source="model"))
    assert (forced.metrics.trades, forced.diagnostics["actionable"]) != \
           (base.metrics.trades, base.diagnostics["actionable"]), \
        "the forecast fed to the strategy did not affect a single decision"


def test_the_report_says_which_forecast_made_the_decisions(model_report):
    report = model_report
    edge = report.diagnostics["model_edge"]
    assert report.diagnostics["forecast_source"] == "model"
    assert edge["available"] is True
    assert edge["label_purge_bars"] == 6

    counted = sum(s["decisions"] for s in edge["segments"])
    assert counted == edge["decisions_from_model"], "segment counts must add up to the total"
    assert edge["decisions_from_model"] + edge["decisions_from_proxy"] == \
           report.diagnostics["analysed"]

    text = " ".join(report.assumptions)
    assert "walk-forward model" in text
    assert "no model scored a bar it had seen" in text
    if edge["scored_decisions"]:
        assert "rule proxy" in text, "the comparison baseline must be named"


def test_the_default_run_still_admits_the_model_is_not_used(proxy_report):
    report = proxy_report
    text = " ".join(report.assumptions)
    assert "NOT used" in text and "rule proxy" in text
    assert report.diagnostics["model_edge"] == {"available": False,
                                                "reason": "forecast_source=rule-proxy"}


def test_accuracies_only_score_bars_where_direction_was_the_question(settings, m5_frame):
    edge = WalkForwardEdge(settings, horizon_minutes=30, segments=2, min_train_rows=50)
    edge.prepare(m5_frame, first_bar=320)
    edge._labels = np.array([0.0] * len(m5_frame))  # every bar sideways
    edge.observe(400, p_up=0.9, p_down=0.1, source="model", proxy_p_up=0.1, proxy_p_down=0.9)
    summary = edge.summary()
    assert summary["scored_decisions"] == 0
    assert summary["model_dir_accuracy"] == 0.0
    assert summary["decisions_from_model"] == 1


# ------------------------------------------------- risk bookkeeping (bug fixes)
def test_a_day_rollover_does_not_forgive_the_week(engine):
    """trades_week used to be dead state while the gate was fed trades_today."""
    backtester, _, _ = engine
    sim = backtester._fresh_sim(10000.0)
    monday = backtester.risk.week_start(1767571200)  # 2026-01-05, a Monday

    backtester._roll_periods(sim, monday + 3600, 10000.0)
    sim["trades_today"] += 2
    sim["trades_week"] += 2
    # next day, same week
    backtester._roll_periods(sim, monday + 30 * 3600, 10050.0)
    assert sim["trades_today"] == 0, "a new day resets the daily count"
    assert sim["trades_week"] == 2, "the week's trades must survive a day rollover"
    sim["trades_today"] += 1
    sim["trades_week"] += 1

    state = backtester._risk_state(sim, balance=10050.0, equity=10050.0)
    assert state.trades_today == 1
    assert state.trades_this_week == 3, "the weekly cap must see the weekly count"

    # next Monday
    backtester._roll_periods(sim, monday + 7 * 86400 + 3600, 10200.0)
    assert sim["trades_week"] == 0 and sim["trades_today"] == 0


def test_weekly_pnl_is_measured_from_the_start_of_the_week(engine):
    """It used to be equity minus the starting balance — the whole run, not the week."""
    backtester, _, _ = engine
    sim = backtester._fresh_sim(10000.0)
    monday = backtester.risk.week_start(1767571200)

    backtester._roll_periods(sim, monday + 3600, 10000.0)
    drifted = backtester._risk_state(sim, balance=9000.0, equity=9000.0)
    assert drifted.weekly_pnl == -1000.0, "down 10% inside week one"

    # A new week starts from wherever the account now is: the old week's loss is
    # spent, and the weekly-loss gate gets a fresh budget just like it does live.
    backtester._roll_periods(sim, monday + 7 * 86400 + 3600, 9000.0)
    fresh = backtester._risk_state(sim, balance=9000.0, equity=9000.0)
    assert fresh.weekly_pnl == 0.0
    assert fresh.weekly_pnl_pct == 0.0
    later = backtester._risk_state(sim, balance=8820.0, equity=8820.0)
    assert later.weekly_pnl == -180.0
    assert later.weekly_pnl_pct == pytest.approx(-2.0, abs=0.01), (
        "the percentage must be of this week's opening equity, not the starting balance")


def test_days_and_weeks_are_cut_where_the_live_engine_cuts_them(runtime):
    """UTC midnight is not the same instant as the configured reset timezone."""
    risk = runtime.risk
    # 2026-01-05 is a Monday; 20:00 UTC is already Tuesday 03:00 in Asia/Bangkok.
    t = 1767643200 + 20 * 3600
    assert risk.day_start(t) == risk._day_start(t)
    assert risk.week_start(t) == risk._week_start(t)
    assert risk.day_start(t) != (t // 86400) * 86400, (
        "the configured timezone must not coincide with UTC, or this test proves nothing")
    assert risk.week_start(t) <= risk.day_start(t)


def test_the_cooldown_gate_is_judged_at_bar_time(runtime, settings):
    """A cooldown set during the backtest must be compared against simulated time."""
    from packages.shared_schemas.models import Health, RiskState

    risk = runtime.risk
    spec = runtime.adapter.symbol_spec("XAUUSD")
    bar_time = 1767643200  # a historical bar
    state = RiskState(balance=10000, equity=10000, peak_equity=10000, daily_pnl=0.0,
                      daily_pnl_pct=0.0, weekly_pnl=0.0, weekly_pnl_pct=0.0, drawdown_pct=0.0,
                      open_trades=0, open_lots=0.0, exposure_pct=0.0, consecutive_losses=2,
                      trades_today=0, trades_this_week=0, cooldown_until=bar_time + 1800)
    quality = {"ok": True, "reason": "", "staleness_seconds": 0.0}

    at_bar_time = risk.gate(state, spec, 20.0, quality, {"active": False}, atr_pct=0.2,
                            broker_health=Health.connected, now=bar_time)
    assert at_bar_time.allow is False, "the cooldown was still running at that bar"

    with_wall_clock = risk.gate(state, spec, 20.0, quality, {"active": False}, atr_pct=0.2,
                                broker_health=Health.connected)
    assert with_wall_clock.allow is True, (
        "today is long past 2026-01-05, so the wall clock ignores the cooldown — "
        "which is exactly why the backtest has to pass bar time")


def test_a_fresh_frame_with_one_class_is_not_fitted(settings):
    """Degenerate data must degrade to the proxy, not raise inside the run."""
    flat = pd.DataFrame({
        "t": np.arange(1_700_000_000, 1_700_000_000 + 600 * 300, 300, dtype=int),
        "o": 2000.0, "h": 2000.5, "l": 1999.5, "c": 2000.0, "v": 100.0,
    })
    edge = WalkForwardEdge(settings, horizon_minutes=30, segments=2, min_train_rows=50)
    edge.prepare(flat, first_bar=200)
    assert edge.predict(250) is None
    summary = edge.summary()
    assert summary["available"] in (True, False)
