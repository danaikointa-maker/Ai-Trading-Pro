from __future__ import annotations

import pytest

from packages.shared_schemas.models import SymbolSpec
from services.risk_engine.planner import (
    break_even_win_rate_calculator,
    drawdown_recovery_calculator,
    point_tick_converter,
    profit_loss_calculator,
    risk_reward_calculator,
)

SPEC = SymbolSpec(
    symbol="XAUUSD", digits=2, point=0.01, tick_size=0.05, contract_size=100,
    min_lot=0.01, max_lot=50, lot_step=0.01, spread_typical_points=2,
    commission_per_lot_round_turn=7, profit_currency="USD", account_currency="USD",
    quote_to_account_rate=1, rate_source="identity", spec_complete=True,
)


def test_risk_reward_is_side_symmetric_and_cost_aware():
    buy = risk_reward_calculator(SPEC, 2000, 1990, 2020, "BUY", 0.1)
    sell = risk_reward_calculator(SPEC, 2000, 2010, 1980, "SELL", 0.1)

    assert buy["status"] == sell["status"] == "ready"
    assert buy["risk_points"] == sell["risk_points"] == 1000
    assert buy["reward_points"] == sell["reward_points"] == 2000
    assert buy["rr_gross"] == sell["rr_gross"] == 2
    assert buy["rr_net"] == sell["rr_net"]
    assert buy["risk_amount_estimate"] > 0
    assert buy["reward_amount_net_estimate"] < buy["reward_amount_gross"]


def test_risk_reward_rejects_wrong_side_levels_and_unvalued_fx():
    invalid = risk_reward_calculator(SPEC, 2000, 2010, 2020, "BUY", 0.1)
    assert invalid["status"] == "invalid_levels"

    unknown_fx = SPEC.model_copy(update={"profit_currency": "EUR", "rate_source": "unknown"})
    unavailable = risk_reward_calculator(unknown_fx, 2000, 1990, 2020, "BUY", 0.1)
    assert unavailable["status"] == "unavailable"
    assert unavailable["rr_net"] is None


def test_drawdown_recovery_uses_remaining_equity_as_denominator():
    result = drawdown_recovery_calculator(9000, 10000)
    assert result["status"] == "ready"
    assert result["drawdown_pct"] == 10
    assert result["recovery_pct"] == pytest.approx(100 / 9)
    assert drawdown_recovery_calculator(10000, 10000)["recovery_pct"] == 0
    assert drawdown_recovery_calculator(9000, 10000)["source"] == "manual_sandbox"


def test_break_even_win_rate_accounts_for_manual_cost_and_rejects_erased_reward():
    result = break_even_win_rate_calculator(200, 100, 10)
    assert result["status"] == "ready"
    assert result["net_reward"] == 190
    assert result["net_loss"] == 110
    assert result["break_even_win_rate_pct"] == pytest.approx(36.6667)
    assert break_even_win_rate_calculator(10, 100, 10)["status"] == "unavailable"
    assert break_even_win_rate_calculator(100, 100, -1)["status"] == "invalid_input"


def test_point_tick_converter_does_not_assume_point_equals_tick():
    aligned = point_tick_converter(SPEC, 0.10)
    fractional = point_tick_converter(SPEC, 0.03)
    assert aligned["points"] == 10
    assert aligned["exact_ticks"] == 2
    assert aligned["legal_tick_count"] == 2
    assert aligned["tick_aligned"] is True
    assert fractional["tick_aligned"] is False
    assert fractional["legal_tick_count"] is None


def test_profit_loss_calculator_signs_and_suppresses_unknown_fx():
    buy_loss = profit_loss_calculator(SPEC, 2000, 1990, "BUY", 0.1)
    sell_win = profit_loss_calculator(SPEC, 2000, 1990, "SELL", 0.1)
    assert buy_loss["status"] == sell_win["status"] == "ready"
    assert buy_loss["gross_profit"] == -100
    assert buy_loss["net_after_known_costs"] < buy_loss["gross_profit"]
    assert sell_win["gross_profit"] == 100

    unknown_fx = SPEC.model_copy(update={"profit_currency": "EUR", "rate_source": "unknown"})
    unavailable = profit_loss_calculator(unknown_fx, 2000, 2010, "BUY", 0.1)
    assert unavailable["status"] == "unavailable"
    assert unavailable["net_after_known_costs"] is None


def test_calculator_api_is_read_only_and_returns_manual_provenance(client, auth, runtime, monkeypatch):
    from unittest.mock import Mock

    submit, modify, close = Mock(), Mock(), Mock()
    monkeypatch.setattr(runtime.gateway, "submit", submit)
    monkeypatch.setattr(runtime.gateway, "modify", modify)
    monkeypatch.setattr(runtime.gateway, "close", close)
    orders_before = runtime.db.query_one("SELECT COUNT(*) AS n FROM orders")["n"]

    cases = [
        ("risk_reward", "&entry=2000&stop_loss=1990&take_profit=2020&side=BUY&lot=0.1"),
        ("drawdown", "&current_equity=9000&peak_equity=10000"),
        ("break_even", "&gross_reward=200&gross_loss=100&estimated_cost=10"),
        ("point_tick", "&price_delta=0.1"),
        ("profit_loss", "&entry=2000&exit_price=2010&side=BUY&lot=0.1"),
    ]
    for tool, params in cases:
        response = client.get(f"/api/risk/calculator?tool={tool}&symbol=XAUUSD{params}", headers=auth)
        assert response.status_code == 200
        assert response.json()["result"]["source"] == "manual_sandbox"

    assert runtime.db.query_one("SELECT COUNT(*) AS n FROM orders")["n"] == orders_before
    submit.assert_not_called()
    modify.assert_not_called()
    close.assert_not_called()
