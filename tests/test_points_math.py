"""Contract-spec maths: points, profit and lot sizing must follow the broker."""
from __future__ import annotations

import pytest

from packages.shared_schemas.models import SymbolSpec
from services.risk_engine.planner import points_calculator, TradePlanner

GOLD = SymbolSpec(
    symbol="XAUUSD", digits=2, point=0.01, tick_size=0.01, contract_size=100.0,
    min_lot=0.01, max_lot=50.0, lot_step=0.01, stops_level_points=0.0,
    spread_typical_points=25.0, commission_per_lot_round_turn=7.0,
)
GOLD_SMALL_POINT = GOLD.model_copy(update={"symbol": "XAUUSDm", "digits": 3, "point": 0.001, "tick_size": 0.001})


def test_500_points_on_gold_is_five_dollars_per_lot():
    calc = points_calculator(GOLD, 500, 0.01)
    assert calc["price_move"] == pytest.approx(5.0)
    assert calc["gross_profit"] == pytest.approx(5.0)
    assert calc["value_per_point_per_lot"] == pytest.approx(1.0)


def test_750_and_1000_points():
    assert points_calculator(GOLD, 750, 0.01)["gross_profit"] == pytest.approx(7.5)
    assert points_calculator(GOLD, 1000, 0.01)["gross_profit"] == pytest.approx(10.0)


def test_small_point_symbol_moves_ten_times_less_per_point():
    big = points_calculator(GOLD, 500, 0.01)
    small = points_calculator(GOLD_SMALL_POINT, 500, 0.01)
    assert small["price_move"] == pytest.approx(big["price_move"] / 10)
    assert small["gross_profit"] == pytest.approx(big["gross_profit"] / 10)


def test_lot_is_derived_from_risk_and_stop_distance():
    lot = TradePlanner.lot_for_risk(GOLD, equity=10_000, risk_pct=0.5, sl_points=400)
    # 50 USD of risk over 400 points * 1 USD/point/lot = 0.125 lots
    assert lot == pytest.approx(0.12, abs=0.011)
    assert lot > 0


def test_lot_respects_broker_step_and_never_exceeds_risk():
    lot = TradePlanner.lot_for_risk(GOLD, equity=1_000, risk_pct=0.5, sl_points=350)
    assert lot == 0.01  # below one step -> clamped to the minimum tradable size
    risk_taken = lot * 350 * GOLD.value_per_point_per_lot
    assert risk_taken <= 1_000 * 0.005 + 1e-9


def test_lot_grows_with_equity_not_lottery_sizes():
    small = TradePlanner.lot_for_risk(GOLD, 10_000, 0.5, 400)
    big = TradePlanner.lot_for_risk(GOLD, 20_000, 0.5, 400)
    assert big == pytest.approx(small * 2, rel=0.05)
