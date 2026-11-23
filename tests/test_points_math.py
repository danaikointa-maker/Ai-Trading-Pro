"""Contract-spec maths: points, profit and lot sizing must follow the broker."""
from __future__ import annotations

import pytest

from packages.shared_schemas.models import SymbolSpec
from services.risk_engine.planner import (
    TradePlanner,
    points_calculator,
    position_size_calculator,
)

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


def test_manual_position_size_floors_to_step_and_includes_known_costs():
    result = position_size_calculator(GOLD, equity=10_000, risk_pct=0.5, sl_points=400)

    assert result["status"] == "ready"
    assert result["risk_budget"] == 50.0
    assert result["lot"] == 0.11
    assert GOLD.lot_is_valid(result["lot"])
    assert result["estimated_stop_cost"] == pytest.approx(47.52)
    assert result["estimated_stop_cost"] <= result["risk_budget"]


def test_manual_position_size_rejects_minimum_lot_above_budget():
    result = position_size_calculator(GOLD, equity=100, risk_pct=0.1, sl_points=100)

    assert result["status"] == "no_legal_lot"
    assert result["lot"] == 0.0
    assert result["minimum_lot"] == GOLD.min_lot
    assert result["estimated_stop_cost"] > result["risk_budget"]


@pytest.mark.parametrize("equity,risk_pct,sl_points", [
    (0, 0.5, 100), (-10, 0.5, 100), (1000, 0, 100),
    (1000, 101, 100), (1000, 0.5, 0), (float("nan"), 0.5, 100),
])
def test_manual_position_size_rejects_invalid_inputs(equity, risk_pct, sl_points):
    result = position_size_calculator(GOLD, equity, risk_pct, sl_points)
    assert result["status"] == "invalid_input"
    assert result["lot"] == 0.0


def test_manual_position_size_suppresses_unknown_account_currency_value():
    result = position_size_calculator(
        SymbolSpec(symbol="USDJPY", digits=3, point=0.001, tick_size=0.001,
                   contract_size=100_000, min_lot=0.01, max_lot=50, lot_step=0.01,
                   profit_currency="JPY", account_currency="USD",
                   quote_to_account_rate=1.0, rate_source="unknown", spec_complete=False),
        equity=10_000, risk_pct=0.5, sl_points=100,
    )
    assert result["status"] == "unavailable"
    assert result["lot"] is None
    assert result["estimated_stop_cost"] is None


def test_manual_position_size_handles_extreme_finite_values_without_overflow():
    result = position_size_calculator(
        GOLD, equity=1e308, risk_pct=100, sl_points=1e-300,
    )
    assert result["status"] == "ready"
    assert result["lot"] == GOLD.max_lot
    assert result["max_lot_capped"] is True


def test_points_calculator_converts_gross_profit_to_account_currency():
    jpy_quoted_usd_account = SymbolSpec(
        symbol="USDJPY", digits=3, point=0.001, tick_size=0.001,
        contract_size=100_000, min_lot=0.01, max_lot=50, lot_step=0.01,
        spread_typical_points=8, commission_per_lot_round_turn=7,
        profit_currency="JPY", account_currency="USD",
        quote_to_account_rate=1 / 157.2, rate_source="ticker", source="broker",
    )

    calc = points_calculator(jpy_quoted_usd_account, points=1000, lot=0.1)

    assert calc["gross_profit"] == pytest.approx(10_000 / 157.2, abs=0.01)
    assert calc["commission"] == pytest.approx(0.7)
    assert calc["spread_cost"] == pytest.approx(8 * 0.001 * 100_000 * 0.1 / 157.2, abs=0.01)
    assert calc["net_profit"] == pytest.approx(calc["gross_profit"] - calc["commission"])
    assert calc["net_after_known_costs"] == pytest.approx(
        calc["gross_profit"] - calc["commission"] - calc["spread_cost"])
    assert calc["currency"] == "USD"
    assert calc["profit_currency"] == "JPY"
    assert calc["rate_source"] == "ticker"
    assert calc["spec_source"] == "broker"


def test_points_calculator_suppresses_money_when_fx_rate_is_unknown():
    unresolved = SymbolSpec(
        symbol="USDJPY", digits=3, point=0.001, tick_size=0.001,
        contract_size=100_000, min_lot=0.01, max_lot=50, lot_step=0.01,
        profit_currency="JPY", account_currency="USD",
        quote_to_account_rate=1.0, rate_source="unknown", spec_complete=False,
    )

    calc = points_calculator(unresolved, points=1000, lot=0.1)

    assert calc["valuation_valid"] is False
    assert calc["gross_profit"] is None
    assert calc["commission"] is None
    assert calc["net_profit"] is None
    assert calc["spread_cost"] is None
    assert "unresolved" in calc["valuation_reason"]


def test_points_calculator_rejects_inconsistent_identity_fx_rate():
    invalid_identity = SymbolSpec(
        symbol="EURUSD", digits=5, point=0.00001, tick_size=0.00001,
        contract_size=100_000, min_lot=0.01, max_lot=50, lot_step=0.01,
        profit_currency="USD", account_currency="USD",
        quote_to_account_rate=1.25, rate_source="identity",
    )

    calc = points_calculator(invalid_identity, points=1000, lot=0.1)

    assert calc["valuation_valid"] is False
    assert calc["gross_profit"] is None
    assert calc["net_profit"] is None
