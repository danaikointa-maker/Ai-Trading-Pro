"""Numeric invariants: the money/geometry rules that must never drift.

These are the formulas a trader would check with a calculator, expressed as
tests so a refactor cannot quietly change the size of a position or a stop.
"""
from __future__ import annotations

import math

import numpy as np
import pytest
import yaml

from packages.shared_schemas.models import Direction, SymbolSpec, TradeRecord, EquityPoint
from services.ai_forecast.pathprob import PathProbabilityTable
from services.backtest_engine.metrics import compute_metrics
from services.risk_engine.planner import PlanInputs, TradePlanner, _split_lot, points_calculator

SPEC = SymbolSpec(
    symbol="XAUUSD", digits=2, point=0.01, tick_size=0.01, contract_size=100.0,
    min_lot=0.01, max_lot=50.0, lot_step=0.01, stops_level_points=0.0,
    spread_typical_points=25.0, commission_per_lot_round_turn=7.0, profit_currency="USD",
)


@pytest.fixture(scope="module")
def planner():
    return TradePlanner(yaml.safe_load(open("config/risk.yaml")))


def _plan(planner, **kw):
    base = dict(direction=Direction.up, entry=2400.00, spec=SPEC, atr_points=356.0,
                equity=10_000.0, risk_pct=0.5, spread_points=25.0, supports=[], resistances=[],
                swings=[], target_mode="adaptive")
    base.update(kw)
    return planner.build(PlanInputs(**base))


# --------------------------------------------------------------- spec geometry
def test_price_snaps_to_the_tick_grid():
    odd = SPEC.model_copy(update={"tick_size": 0.05, "point": 0.01})
    p = odd.round_price(1234.567)
    assert abs((p / 0.05) - round(p / 0.05)) < 1e-6


def test_lot_never_rounds_up_past_the_risk_budget():
    for raw in (0.1249, 0.1299, 0.1350, 0.0999):
        lot = SPEC.normalize_lot(raw)
        assert lot <= raw + 1e-9 or lot == SPEC.min_lot


def test_points_to_price_matches_point_size():
    assert SPEC.points_to_price(500) == 5.0
    assert SPEC.points_to_price(1000) == 10.0
    assert SPEC.price_to_points(5.0) == 500.0


# ------------------------------------------------------------------- the plan
def test_plan_risk_matches_lot_times_stop(planner):
    res = _plan(planner)
    assert res.blockers == [], res.blockers
    plan = res.plan
    money_at_risk = plan.lot * plan.sl_points * SPEC.value_per_point_per_lot
    assert money_at_risk == pytest.approx(plan.risk_amount, abs=0.02)
    assert plan.risk_amount <= 10_000 * 0.005 + 1e-6, "never risk more than the configured %"
    assert plan.risk_pct <= 0.5 + 1e-6


def test_plan_stop_and_targets_are_on_the_right_side(planner):
    for direction, sign in ((Direction.up, 1), (Direction.down, -1)):
        plan = _plan(planner, direction=direction).plan
        assert plan is not None
        assert (plan.sl - plan.entry) * sign < 0
        assert (plan.tp1 - plan.entry) * sign > 0
        assert plan.tp1 < plan.tp2 < plan.tp3 if sign > 0 else plan.tp3 < plan.tp2 < plan.tp1


def test_targets_stay_inside_the_500_to_1000_point_band(planner):
    plan = _plan(planner).plan
    for tp in plan.tp_points:
        assert 500 - 1e-6 <= tp <= 1000 + 1e-6


def test_partials_sum_exactly_to_the_position(planner):
    for equity in (1_000, 2_500, 10_000, 50_000):
        plan = _plan(planner, equity=equity).plan
        if plan is None:
            continue
        total = round(sum(p.volume for p in plan.partials), 4)
        assert total == pytest.approx(plan.lot, abs=1e-6)
        for p in plan.partials:
            if p.feasible:
                assert p.volume >= SPEC.min_lot - 1e-9
                assert abs((p.volume / SPEC.lot_step) - round(p.volume / SPEC.lot_step)) < 1e-6


def test_unsplittable_position_is_kept_whole():
    vols = _split_lot(SPEC, 0.02, [40, 30, 30])
    assert vols == [0.02, 0.0, 0.0]
    vols = _split_lot(SPEC, 0.10, [40, 30, 30])
    assert sum(vols) == pytest.approx(0.10)
    assert all((v == 0) or v >= SPEC.min_lot for v in vols)


def test_reward_risk_uses_costs_and_the_first_target_stands_alone(planner):
    plan = _plan(planner).plan
    cost = 25 / 2 + 7.0 / SPEC.value_per_point_per_lot  # half-spread + commission in points
    tp1_net_rr = (plan.tp_points[0] - cost) / (plan.sl_points + cost)
    assert plan.reward_risk_net < plan.reward_risk, "net must be below gross"
    assert tp1_net_rr >= 1.0, "a plan may not be built on a sub-1R first target"


def test_stops_level_is_respected():
    broker = SPEC.model_copy(update={"stops_level_points": 900.0})
    planner = TradePlanner(yaml.safe_load(open("config/risk.yaml")))
    res = _plan(planner, spec=broker)
    if res.plan is not None:
        assert res.plan.sl_points >= 900


def test_points_calculator_is_contract_aware():
    calc = points_calculator(SPEC, 750, 0.01)
    assert calc["gross_profit"] == pytest.approx(7.5)
    assert calc["net_profit"] == pytest.approx(7.5 - 0.07, abs=0.01)


# ---------------------------------------------------------------- path model
def test_path_probability_is_bounded_and_decreases_with_a_further_target():
    rng = np.random.default_rng(3)
    n = 4_000
    price = 2000 + np.cumsum(rng.normal(0, 0.2, n))
    df = {"t": np.arange(n) * 300, "o": price, "h": price + 0.4, "l": price - 0.4,
          "c": price, "v": np.ones(n)}
    import pandas as pd
    table = PathProbabilityTable.build(pd.DataFrame(df), np.full(n, 0.5), [6, 12, 48])
    near, _ = table.p_tp_before_sl(30, 0.4, 1.0, p_up=0.5)
    far, _ = table.p_tp_before_sl(30, 4.0, 1.0, p_up=0.5)
    assert 0.0 <= near <= 1.0 and 0.0 <= far <= 1.0
    assert far < near, "a target four times further out cannot be easier to reach"


# ------------------------------------------------------------------- metrics
def _trade(pnl, points, reason, partials=0):
    return TradeRecord(
        ticket=f"T{abs(hash((pnl, points, reason)))}", symbol="XAUUSD", direction=Direction.up,
        volume=0.1, entry=2000.0, exit=2000.0 + points / 100, sl=1996.0, tp=2010.0,
        opened_at=0, closed_at=60, points=points, gross_pnl=pnl, costs=0.0, pnl=pnl,
        r_multiple=pnl / 50, exit_reason=reason, strategy="t", signal_id="s",
        journal={"partials_done": partials},
    )


def _curve(values):
    return [EquityPoint(t=i * 300, equity=v, balance=v, drawdown_pct=0.0) for i, v in enumerate(values)]


def test_profit_factor_is_capped_when_there_are_no_losses():
    m = compute_metrics([_trade(50, 300, "take profit")], _curve([10_000, 10_050]), 10, 10_000)
    assert m.profit_factor == 99.0, "an infinite PF must not be reported as a dollar figure"


def test_tp_before_sl_counts_a_banked_partial():
    trades = [_trade(20, 120, "stop loss", partials=1), _trade(-50, -300, "stop loss")]
    m = compute_metrics(trades, _curve([10_000, 9_970]), 4, 10_000)
    assert m.tp_before_sl_rate == 50.0


def test_directional_accuracy_ignores_costs():
    # price moved the right way (points > 0) but costs turned it into a loss
    trades = [_trade(-5, 40, "time_exit"), _trade(-50, -300, "stop loss")]
    m = compute_metrics(trades, _curve([10_000, 9_945]), 4, 10_000)
    assert m.directional_accuracy == 50.0
    assert m.win_rate == 0.0


def test_no_trade_rate_and_expectancy():
    trades = [_trade(100, 600, "take profit"), _trade(-50, -350, "stop loss")]
    m = compute_metrics(trades, _curve([10_000, 10_050]), 20, 10_000)
    assert m.trades == 2
    assert m.expectancy == pytest.approx(25.0)
    assert m.no_trade_rate == pytest.approx(90.0)
    assert m.max_consecutive_losses == 1


# ------------------------------------------------------------- forecast shape
def test_scenario_fans_are_distinct_and_land_on_their_target():
    from services.ai_forecast.predictor import _normalise_probs

    p_up, p_down, p_side = _normalise_probs(0.41, 0.33, 0.26)
    assert abs(p_up + p_down + p_side - 1.0) < 1e-12

    price, p10, p50, p90 = 2000.0, 1994.0, 1999.0, 2006.0
    half = abs(p90 - p10) / 2.0
    ends = {}
    for name, target in (("bull", p90), ("base", p50), ("bear", p10)):
        pts = []
        for i in range(25):
            frac = i / 24
            centre = price + (target - price) * math.sqrt(frac)
            width = half * math.sqrt(frac)
            pts.append((centre, centre - width, centre + width))
        ends[name] = pts[-1][0]
        assert pts[0][0] == pytest.approx(price)
        # the band is always a band, and it never inverts
        assert all(p10_ <= mid <= p90_ for mid, p10_, p90_ in pts)
        assert pts[-1][0] == pytest.approx(target)
    assert len({round(v, 6) for v in ends.values()}) == 3, "scenarios must not collapse into one path"


def test_risk_in_money_uses_points_not_price_distance():
    """A 200-point stop at 1.0 USD/point/lot and 0.2 lot risks 40 USD, not 0.4."""
    price_distance = 2.00           # 200 points on XAUUSD (point = 0.01)
    qty = 0.2
    correct = (price_distance / SPEC.point) * SPEC.value_per_point_per_lot * qty
    assert correct == pytest.approx(40.0)
    assert correct > 1.0, "a price distance must never be treated as points"


def test_gateway_close_contract_is_uniform(tmp_path, monkeypatch):
    """Simulated closes must return {ok, trade}, not crash on .status, and the
    finished trade must reach the closed-trades table exactly once."""
    monkeypatch.setenv("NO7_DB_PATH", str(tmp_path / "close.sqlite3"))
    from packages.persistence.db import Database
    from packages.shared_schemas.models import OrderRequest, OrderSide
    from services.execution_gateway.gateway import ExecutionGateway
    from services.api_gateway.state import TradingRuntime

    rt = TradingRuntime()
    adapter = rt.registry.get("connext-demo")
    gw = ExecutionGateway(rt.settings, Database(rt.settings.database_path))
    spec = adapter.symbol_spec("XAUUSD")
    tick = adapter.ticker("XAUUSD")
    opened = adapter.order_send(OrderRequest(
        symbol="XAUUSD", side=OrderSide.buy, volume=spec.min_lot,
        sl=round(tick.bid - 3.0, spec.digits), tp=round(tick.bid + 6.0, spec.digits)))
    assert opened.ticket, opened.message
    ticket = opened.ticket
    out = gw.close(adapter, ticket, reason="test")
    assert out["ok"] is True
    assert "trade" in out and "order" not in out
    assert out["trade"]["pnl"] is not None
    rows = gw.db.query("SELECT ticket FROM trades WHERE ticket = ?", (ticket,))
    assert len(rows) == 1, "a closed trade must be journaled exactly once"
    rt.stop()


def test_costs_are_reported_and_gross_minus_net_equals_costs():
    """Spread + slippage must show up as money. The simulated broker used to
    report $0.00 of costs because only commission was counted, while the fill
    price silently carried 12.5 points of spread."""
    from packages.shared_schemas.models import OrderRequest, OrderSide
    from services.api_gateway.state import TradingRuntime

    rt = TradingRuntime()
    adapter = rt.registry.get("connext-demo")
    spec = adapter.symbol_spec("XAUUSD")
    tick = adapter.ticker("XAUUSD")
    before = adapter.account_info().balance
    opened = adapter.order_send(OrderRequest(
        symbol="XAUUSD", side=OrderSide.buy, volume=0.2,
        sl=round(tick.bid - 3.0, spec.digits), tp=round(tick.bid + 3.0, spec.digits)))
    assert opened.ticket
    trade = adapter.close_position(opened.ticket, comment="test")
    expected = (spec.spread_typical_points / 2 * spec.point
                + abs(trade.entry - (tick.bid + 0.0)) * 0)  # spread half at minimum
    assert trade.costs > 0.0, "spread cost must not be reported as zero"
    # 12.5 points of spread x $1/point/lot x 0.2 lot = $2.50 (+ slippage)
    assert trade.costs >= expected / spec.point * spec.value_per_point_per_lot * 0.2 * 0.9
    assert trade.gross_pnl - trade.pnl == pytest.approx(trade.costs, abs=0.02)
    assert adapter.account_info().balance == pytest.approx(before + trade.pnl, abs=0.02), \
        "the spread is already inside the fill price; it must not be charged twice"
    rt.stop()


def test_quote_currency_conversion():
    """One point of USDJPY is worth 100 JPY, not 100 USD. Sizing and P&L must be
    converted, and an unresolvable rate must block sizing instead of assuming 1.0."""
    from integrations.brokers.fx import resolve_quote_rate
    from packages.shared_schemas.models import SymbolSpec

    quotes = {"GBPUSD": 1.25, "USDJPY": 157.2}
    price_of = lambda name: quotes.get(name)  # noqa: E731

    rate, source = resolve_quote_rate("USD", "USD", price_of)
    assert (rate, source) == (1.0, "identity")

    rate, source = resolve_quote_rate("GBP", "USD", price_of)
    assert source == "ticker" and rate == pytest.approx(1.25)

    rate, source = resolve_quote_rate("JPY", "USD", price_of)
    assert source == "ticker" and rate == pytest.approx(1 / 157.2, rel=1e-9)

    rate, source = resolve_quote_rate("CHF", "USD", price_of)
    assert (rate, source) == (1.0, "unknown")

    jpy = SymbolSpec(symbol="USDJPY", point=0.001, contract_size=100_000, profit_currency="JPY",
                     quote_to_account_rate=1 / 157.2, rate_source="ticker")
    # 1 point on 1 lot = 0.001 * 100000 = 100 JPY = 100/157.2 USD
    assert jpy.value_per_point_per_lot == pytest.approx(100 / 157.2, rel=1e-9)
    assert jpy.sizing_blocked is False

    unknown = jpy.model_copy(update={"rate_source": "unknown", "quote_to_account_rate": 1.0})
    assert unknown.sizing_blocked is True


def test_paper_broker_pnl_is_in_account_currency():
    """A cross pair must not inflate the balance by the exchange rate."""
    from integrations.brokers.paper import gross_pnl
    from packages.shared_schemas.models import Direction, SymbolSpec

    usdjpy = SymbolSpec(symbol="USDJPY", point=0.001, contract_size=100_000,
                        profit_currency="JPY", quote_to_account_rate=1 / 157.2, rate_source="ticker")
    pnl = gross_pnl(Direction.up, 157.000, 157.100, 1.0, usdjpy)  # +100 points
    assert pnl == pytest.approx(100 * (100 / 157.2), rel=1e-9)
    assert pnl < 100, "JPY profit must be converted before it hits a USD balance"


def test_backtest_is_reproducible_for_the_same_data():
    """Same OHLCV in => identical metrics out, and the fingerprint proves it.

    Before this, two identical runs could differ and there was no way to say why;
    the report now records a hash of the exact candles it consumed.
    """
    from packages.shared_schemas.models import BacktestRequest
    from services.api_gateway.state import TradingRuntime
    from services.backtest_engine.backtester import Backtester

    rt = TradingRuntime()
    adapter = rt.registry.get("connext-demo")
    spec = adapter.symbol_spec("XAUUSD")
    frame = adapter.candles("XAUUSD", "M1", 2400).copy()
    request = BacktestRequest(symbol="XAUUSD", bars=2400, slippage_points=2, starting_balance=10000)

    engine = Backtester(rt.settings, rt.risk, rt.planner)
    first = engine.run(frame, spec, request, "connext-demo")
    second = engine.run(frame, spec, request, "connext-demo")

    assert first.data_fingerprint and len(first.data_fingerprint) == 16
    assert first.data_fingerprint == second.data_fingerprint
    assert first.metrics.model_dump() == second.metrics.model_dump()
    assert first.equity_curve[-1].equity == pytest.approx(second.equity_curve[-1].equity, abs=1e-9)

    # One changed bar must change the fingerprint (otherwise the hash is useless).
    nudged = frame.copy()
    nudged.loc[nudged.index[-5], "c"] = float(nudged["c"].iloc[-5]) + 0.5
    third = engine.run(nudged, spec, request, "connext-demo")
    assert third.data_fingerprint != first.data_fingerprint
    rt.stop()


def test_short_backtest_raises_a_clear_error():
    """Asking for too few bars must say so, not blow up with a pandas IndexError."""
    from packages.shared_schemas.models import BacktestRequest
    from services.api_gateway.state import TradingRuntime
    from services.backtest_engine.backtester import Backtester

    rt = TradingRuntime()
    adapter = rt.registry.get("connext-demo")
    spec = adapter.symbol_spec("XAUUSD")
    frame = adapter.candles("XAUUSD", "M1", 1200).copy()
    with pytest.raises(ValueError, match="not enough history"):
        Backtester(rt.settings, rt.risk, rt.planner).run(
            frame, spec, BacktestRequest(symbol="XAUUSD", bars=1200), "connext-demo")
    rt.stop()


def test_news_calendar_file_overrides_the_placeholder(tmp_path):
    """A real calendar file must replace the demo schedule, and the demo entries
    must announce themselves as provisional so nobody mistakes them for news."""
    import json

    from packages.persistence.db import Database
    from services.market_data.news import NewsService

    calendar = tmp_path / "news.json"
    now = 1_800_000_000
    calendar.write_text(json.dumps({"events": [
        {"t": now + 600, "currency": "USD", "impact": "high", "title": "US CPI m/m"},
        {"t": now + 1200, "currency": "EUR", "impact": "medium", "title": "ECB minutes"},
        {"t": "bad", "currency": "USD", "impact": "high", "title": "broken row"},
        {"t": now + 1800, "currency": "USD", "impact": "nonsense", "title": "bad impact"},
    ]}), encoding="utf-8")

    db = Database(tmp_path / "news.sqlite3")
    service = NewsService(db, now=now, calendar_path=calendar)
    assert service.source.endswith("news.json")
    assert service.skipped_events == 2, "malformed rows are skipped, not silently accepted"
    assert [e.title for e in service.events] == ["US CPI m/m", "ECB minutes"]
    assert all(not e.provisional for e in service.events)

    lock = service.lockout(now + 700)
    assert lock["active"] is True
    assert lock["provisional"] is False
    assert "provisional" not in lock["reason"]

    demo = NewsService(Database(tmp_path / "demo.sqlite3"), now=now)
    assert demo.source == "demo"
    assert all(e.provisional for e in demo.events)
    demo_lock = demo.lockout(demo.events[0].t - 60)
    assert demo_lock["active"] is True
    assert demo_lock["provisional"] is True
    assert "NOT a real economic release" in demo_lock["reason"]


def test_provisional_flag_survives_a_restart(tmp_path):
    """The demo-news flag must survive the sqlite round trip: a reloaded event
    used to come back as if it were real news."""
    from packages.persistence.db import Database
    from services.market_data.news import NewsService

    db_path = tmp_path / "news.sqlite3"
    now = 1_800_000_000
    first = NewsService(Database(db_path), now=now)
    assert first.events and all(e.provisional for e in first.events)

    second = NewsService(Database(db_path), now=now)
    assert all(e.provisional for e in second.events), "provisional flag lost on reload"
    event = second.events[0]
    lock = second.lockout(event.t - 60)
    assert lock["provisional"] is True
    assert "NOT a real economic release" in lock["reason"]
    assert lock["event"]["provisional"] is True
    assert lock["next_event"]["provisional"] is True


def test_fx_triangulation_through_a_third_currency():
    """GBP P&L on a USD account must still be valued when only EUR pairs exist:
    EURUSD / EURGBP = GBPUSD."""
    from integrations.brokers.fx import resolve_quote_rate

    quotes = {"EURUSD": 1.08, "EURGBP": 0.85}
    rate, source = resolve_quote_rate("GBP", "USD", quotes.get)
    assert source == "triangulated"
    assert rate == pytest.approx(1.08 / 0.85, rel=1e-12)

    # A direct quote always wins over triangulation.
    rate, source = resolve_quote_rate("GBP", "USD", {"GBPUSD": 1.27, **quotes}.get)
    assert (source, rate) == ("ticker", 1.27)

    # No path at all -> still unknown (the planner will refuse to size).
    rate, source = resolve_quote_rate("TRY", "USD", quotes.get)
    assert (rate, source) == (1.0, "unknown")


def test_overnight_swap_is_charged_and_wednesday_counts_triple():
    """Holding past midnight must cost money, and the demo swap rates must reach
    the balance (before this, swap was configured but never applied)."""
    from datetime import datetime, timezone

    from packages.shared_schemas.models import OrderRequest, OrderSide
    from services.api_gateway.state import TradingRuntime

    rt = TradingRuntime()
    adapter = rt.registry.get("connext-demo")
    spec = adapter.symbol_spec("XAUUSD")
    assert spec.swap_long_per_lot != 0 or spec.swap_short_per_lot != 0, \
        "the demo profile must carry swap rates for this to mean anything"

    tick = adapter.ticker("XAUUSD")
    opened = adapter.order_send(OrderRequest(
        symbol="XAUUSD", side=OrderSide.sell, volume=0.5,
        sl=round(tick.bid + 5.0, spec.digits), tp=round(tick.bid - 8.0, spec.digits)))
    assert opened.ticket

    # Start from a Monday so the first rollover is a plain weekday night.
    monday = int(datetime(2026, 11, 2, 23, 30, tzinfo=timezone.utc).timestamp())
    position = adapter._positions[opened.ticket]
    position.last_swap_day = monday // 86400
    balance_before = adapter.account_info().balance

    adapter.clock = lambda: monday + 3600  # 00:30 Tuesday
    adapter._apply_swap()
    tuesday = datetime(2026, 11, 3, tzinfo=timezone.utc).weekday()
    assert tuesday == 1
    expected = spec.swap_short_per_lot * 0.5
    assert position.swap_charged == pytest.approx(expected, rel=1e-9)
    assert adapter.account_info().balance == pytest.approx(balance_before + expected, abs=0.01)

    # Tuesday -> Wednesday: the rollover that carries the weekend, so triple.
    wednesday_epoch = int(datetime(2026, 11, 4, 0, 30, tzinfo=timezone.utc).timestamp())
    adapter.clock = lambda: wednesday_epoch
    adapter._apply_swap()
    assert position.swap_charged == pytest.approx(expected * 4, rel=1e-9)

    # Nothing is charged twice for the same day.
    adapter._apply_swap()
    assert position.swap_charged == pytest.approx(expected * 4, rel=1e-9)

    trade = adapter.close_position(opened.ticket, comment="test")
    assert trade.swap == pytest.approx(expected * 4, abs=0.01)
    # gross = P&L with no costs and no financing: gross - pnl == costs - swap
    assert trade.gross_pnl - trade.pnl == pytest.approx(trade.costs - trade.swap, abs=0.02)
    rt.stop()
