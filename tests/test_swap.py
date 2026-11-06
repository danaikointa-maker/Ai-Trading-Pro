"""Overnight swap: quoted in a declared unit, charged in the account currency.

Brokers quote swap in three incompatible ways — account currency per lot, price
points per lot, or an annual interest rate on the notional. Reading `swap_long`
without its mode turns a points figure into dollars (or the reverse), and an
interest rate into a per-night charge that is ~360x too big.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from integrations.brokers.paper import PaperBroker, PaperPosition
from packages.shared_schemas.models import (
    Direction,
    SymbolSpec,
    TradeMode,
    swap_night_multiplier,
)
from services.backtest_engine.backtester import Backtester, SimPosition

GOLD = dict(symbol="XAUUSD", digits=2, point=0.01, tick_size=0.01, contract_size=100.0,
            min_lot=0.01, max_lot=50.0, lot_step=0.01, profit_currency="USD")


def day_index(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp()) // 86400


# ------------------------------------------------------------------- the units
def test_money_mode_is_account_currency_per_lot_per_night():
    spec = SymbolSpec(**GOLD, swap_mode="money", swap_long_per_lot=-21.4, swap_short_per_lot=9.1)
    assert spec.swap_for(Direction.up, 0.50, 3800.0) == pytest.approx(-10.70)
    assert spec.swap_for(Direction.down, 0.50, 3800.0) == pytest.approx(4.55)


def test_points_mode_equals_money_mode_for_gold():
    """1 point on 1 lot of gold is exactly $1, so -21.4 points is -21.4 USD."""
    points = SymbolSpec(**GOLD, swap_mode="points", swap_long_points=-21.4)
    money = SymbolSpec(**GOLD, swap_mode="money", swap_long_per_lot=-21.4)
    assert points.swap_for(Direction.up, 1.0, 3800.0) == pytest.approx(
        money.swap_for(Direction.up, 1.0, 3800.0)
    )


def test_percent_mode_uses_notional_and_360_day_basis():
    # 5% a year on 1 lot of gold at 3800: notional 380,000 -> 52.78 per night
    spec = SymbolSpec(**GOLD, swap_mode="percent", swap_long_pct=-5.0)
    assert spec.swap_for(Direction.up, 1.0, 3800.0) == pytest.approx(-380_000 * 0.05 / 360)


def test_points_mode_converts_jpy_quote_to_account_currency():
    jpy = SymbolSpec(symbol="USDJPY", digits=3, point=0.001, tick_size=0.001,
                     contract_size=100_000.0, min_lot=0.01, max_lot=50.0, lot_step=0.01,
                     profit_currency="JPY", quote_to_account_rate=1 / 157.2, rate_source="ticker",
                     swap_mode="points", swap_long_points=-21.4)
    # 21.4 points x 0.001 x 100,000 = 2,140 JPY -> / 157.2 = 13.61 USD
    assert jpy.swap_for(Direction.up, 1.0, 157.0) == pytest.approx(-2140 / 157.2)


def test_wednesday_night_is_charged_triple():
    wednesday = day_index(2026, 11, 4)
    thursday = day_index(2026, 11, 5)
    assert datetime.fromtimestamp(wednesday * 86400, tz=timezone.utc).weekday() == 2
    assert swap_night_multiplier(wednesday) == 3
    assert swap_night_multiplier(thursday) == 1


# ------------------------------------------------------------------ paper broker
class _NoFeed:
    """`_apply_swap` never touches the feed; the broker only needs the attribute."""


def _broker(now: list[float]) -> PaperBroker:
    symbol_cfg = {k: v for k, v in GOLD.items() if k != "symbol"}
    symbol_cfg.update(swap_mode="money", swap_long_per_lot=-21.4, swap_short_per_lot=9.1)
    profile = {"id": "test", "symbols": {"XAUUSD": symbol_cfg}}
    return PaperBroker(profile, _NoFeed(), starting_balance=10_000.0, clock=lambda: now[0])


def _open_position(broker: PaperBroker, opened_day: int, volume: float = 1.0) -> PaperPosition:
    spec = broker.symbol_spec("XAUUSD")
    pos = PaperPosition(
        ticket="P1", symbol="XAUUSD", spec=spec, direction=Direction.up, volume=volume,
        initial_volume=volume, entry=3800.0, sl=0.0, tp=0.0, open_time=opened_day * 86400,
        last_price=3800.0, last_swap_day=opened_day,
    )
    broker._positions["P1"] = pos
    return pos


def test_paper_charges_one_night_per_midnight():
    now = [0.0]
    broker = _broker(now)
    monday = day_index(2026, 11, 2)
    pos = _open_position(broker, monday)

    now[0] = (monday + 1) * 86400 + 60  # just after midnight
    broker._apply_swap()
    assert pos.swap_charged == pytest.approx(-21.4)
    assert broker.balance == pytest.approx(10_000.0 - 21.4)

    # Two more nights in one jump must both be charged, Wednesday triple included.
    now[0] = (monday + 3) * 86400 + 60
    broker._apply_swap()
    # nights Tue->Wed (1x) and Wed->Thu (3x) => 4 x -21.4 more
    assert pos.swap_charged == pytest.approx(-21.4 * 5)
    assert broker.balance == pytest.approx(10_000.0 - 21.4 * 5)


def test_paper_swap_is_repeatable_within_a_night():
    now = [0.0]
    broker = _broker(now)
    monday = day_index(2026, 11, 2)
    pos = _open_position(broker, monday)
    now[0] = (monday + 1) * 86400 + 60
    broker._apply_swap()
    broker._apply_swap()  # same night -> no second charge
    assert pos.swap_charged == pytest.approx(-21.4)


def test_trade_record_reports_swap_separately_from_costs():
    now = [0.0]
    broker = _broker(now)
    monday = day_index(2026, 11, 2)
    pos = _open_position(broker, monday)
    now[0] = (monday + 1) * 86400 + 60
    broker._apply_swap()

    record = broker._realize(pos, 3810.0, 1.0, "test close")
    assert record is not None and record.swap == pytest.approx(-21.4)
    # gross - pnl == costs - swap keeps the price result free of financing
    assert record.gross_pnl == pytest.approx(record.pnl + record.costs - record.swap, abs=0.01)
    assert record.gross_pnl == pytest.approx(1000.0, abs=0.01)  # 10.00 move x 100 oz


# --------------------------------------------------------------------- backtest
def test_backtest_gross_excludes_swap():
    spec = SymbolSpec(**GOLD)
    pos = SimPosition(
        direction=Direction.up, entry=3800.0, sl=3790.0, sl_initial=3790.0, tps=[3810.0],
        volumes=[1.0], partials_done=0, remaining=0.0, initial_volume=1.0, opened_at=0,
        entry_bar=1, risk_amount=1000.0, trade_mode=TradeMode.manual, strategy="t",
        signal_id="S1-000001",
    )
    pos.weighted_exit, pos.closed_volume = 3810.0, 1.0
    pos.realized = 1000.0 - 10.0 - 21.4   # price +1000, commission 10, swap -21.4
    pos.costs, pos.swap = 10.0, -21.4

    record = Backtester._finalize(pos, bar_time=86400, spec=spec)
    assert record.swap == pytest.approx(-21.4)
    assert record.gross_pnl == pytest.approx(1000.0)
    assert record.pnl == pytest.approx(1000.0 - 10.0 - 21.4)
