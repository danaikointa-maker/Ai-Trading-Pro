"""The backtest is the number generator the whole product is judged on.

These tests pin the invariants that make its output trustworthy: the cost
identity on every trade, metrics that cannot contradict each other, honest
assumption text, determinism, and the direction that costs must push profit.
"""
from __future__ import annotations

import pytest

from packages.shared_schemas.models import BacktestRequest
from services.backtest_engine.backtester import Backtester
from services.market_data.simulator import SyntheticFeed

BARS = 4000


@pytest.fixture(scope="module")
def engine(runtime, settings):
    feed = SyntheticFeed({"XAUUSD": {"digits": 2, "point": 0.01, "contract_size": 100}},
                         history_bars=BARS, seed=7)
    candles = feed.warm_history("XAUUSD", BARS)
    spec = runtime.adapter.symbol_spec("XAUUSD")
    return Backtester(settings, runtime.risk, runtime.planner), candles, spec


@pytest.fixture(scope="module")
def report(engine):
    backtester, candles, spec = engine
    return backtester.run(candles, spec, BacktestRequest(symbol="XAUUSD", bars=BARS, slippage_points=2))


# ------------------------------------------------------------------ accounting
def test_every_trade_satisfies_the_cost_identity(report):
    """gross - pnl must equal costs - swap, for every single trade."""
    for t in report.trades:
        assert t.gross_pnl - t.pnl == pytest.approx(t.costs - t.swap, abs=0.02), t.ticket


def test_net_profit_is_the_sum_of_trade_pnl(report):
    assert report.metrics.net_profit == pytest.approx(sum(t.pnl for t in report.trades), abs=0.05)


def test_total_costs_is_the_sum_of_trade_costs(report):
    assert report.metrics.total_costs == pytest.approx(sum(t.costs for t in report.trades), abs=0.05)


# --------------------------------------------------------------------- metrics
def test_metrics_cannot_contradict_each_other(report):
    m = report.metrics
    assert m.wins + m.losses <= m.trades
    assert 0.0 <= m.win_rate <= 100.0
    assert 0.0 <= m.no_trade_rate <= 100.0
    assert m.max_drawdown_pct >= 0.0
    # capped on purpose: a book with no losses has an infinite ratio
    assert m.profit_factor <= 99.0
    if m.trades:
        assert m.expectancy == pytest.approx(m.net_profit / m.trades, abs=0.02)
    for t in report.trades:
        if t.pnl > 0:
            assert t.r_multiple > 0
        if t.pnl < 0:
            assert t.r_multiple < 0


def test_no_trade_rate_matches_the_decision_count(report):
    """A high no-trade rate is a measurement, so it has to be arithmetically true."""
    if report.metrics.trades == 0:
        assert report.metrics.no_trade_rate == 100.0
    else:
        # trades >= 1 implies at least one decision was taken
        assert report.metrics.no_trade_rate < 100.0


# ------------------------------------------------------------------- honesty
def test_report_states_its_assumptions_honestly(report):
    text = " ".join(report.assumptions)
    assert "Swap basis" in text
    assert "rule proxy" in text and "NOT used" in text
    # Without a stated data source the report must say so, not assume "simulated".
    assert "Bar data:" in text and "unverified" in text
    assert "stop is assumed first" in text
    assert "commission" in text


def test_the_bar_data_note_is_whatever_the_caller_recorded(engine):
    backtester, candles, spec = engine
    note = "Bar data: imported candles replayed from the dataset directory — real bars, no ticks."
    report = backtester.run(candles, spec, BacktestRequest(symbol="XAUUSD", bars=BARS),
                            data_note=note)
    assert note in report.assumptions
    assert not any("Simulated feed data" in line for line in report.assumptions)


# ----------------------------------------------------------------- behaviour
def test_rerun_on_the_same_candles_is_deterministic(engine, report):
    backtester, candles, spec = engine
    again = backtester.run(candles, spec, BacktestRequest(symbol="XAUUSD", bars=BARS, slippage_points=2))
    assert again.metrics.trades == report.metrics.trades
    assert again.metrics.net_profit == pytest.approx(report.metrics.net_profit, abs=0.01)
    assert [(t.entry, t.exit) for t in again.trades] == [(t.entry, t.exit) for t in report.trades]


def test_higher_slippage_cannot_improve_the_result(engine, report):
    backtester, candles, spec = engine
    worse = backtester.run(candles, spec, BacktestRequest(symbol="XAUUSD", bars=BARS, slippage_points=40))
    assert worse.metrics.net_profit <= report.metrics.net_profit + 1e-6


def test_timeline_is_ordered(report):
    stamps = [p.t for p in report.equity_curve]
    assert stamps == sorted(stamps), "equity curve must be chronological"
    assert len(set(stamps)) == len(stamps), "duplicate timestamps would double-draw the curve"
    for t in report.trades:
        assert t.closed_at >= t.opened_at


def test_diagnostics_explain_why_the_trade_count_is_what_it_is(engine, report):
    """no_trade_rate must divide by the points that were actually analysed."""
    d = report.diagnostics
    assert d["decision_points"] == d["analysed"] + d["no_context"]
    assert d["analysed"] >= d["actionable"] >= d["trades_opened"]
    assert d["trades_opened"] == report.metrics.trades
    if d["analysed"]:
        expected = round(max(0.0, 1 - d["trades_opened"] / d["analysed"]) * 100, 2)
        assert report.metrics.no_trade_rate == pytest.approx(expected, abs=0.01)
    assert d["no_trade_rate_basis"].startswith("trades / analysed")

    text = " ".join(report.assumptions)
    assert "analysis ran on" in text
    assert f"{d['no_context']} skipped" in text
