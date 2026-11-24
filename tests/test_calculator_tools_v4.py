from __future__ import annotations

import pytest

from packages.shared_schemas.models import SymbolSpec
from services.risk_engine.planner import (
    break_even_win_rate_calculator,
    capital_growth_calculator,
    currency_conversion_calculator,
    drawdown_recovery_calculator,
    point_tick_converter,
    profit_loss_calculator,
    risk_reward_calculator,
    scenario_simulator,
    trading_costs_calculator,
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


def test_trading_costs_reuse_declared_swap_mode_and_manual_triple_count():
    swap_spec = SPEC.model_copy(update={
        "swap_mode": "money", "swap_long_per_lot": -21.4,
        "swap_short_per_lot": 9.1,
    })
    result = trading_costs_calculator(swap_spec, "BUY", 2000, 0.1, 3, 1)
    assert result["status"] == "ready"
    assert result["swap_nights_applied"] == 5
    assert result["spread_cost"] == pytest.approx(0.2)
    assert result["commission_cost"] == pytest.approx(0.7)
    assert result["swap_amount_signed"] == pytest.approx(-10.7)
    assert result["total_cost_estimate"] == pytest.approx(11.6)

    points_mode = swap_spec.model_copy(update={"swap_mode": "points", "swap_long_points": -10})
    points_result = trading_costs_calculator(points_mode, "BUY", 2000, 0.1, 1, 0)
    assert points_result["swap_amount_signed"] == pytest.approx(-1.0)

    percent_mode = swap_spec.model_copy(update={"swap_mode": "percent", "swap_long_pct": -5})
    percent_result = trading_costs_calculator(percent_mode, "BUY", 2000, 0.1, 1, 0)
    assert percent_result["swap_amount_signed"] == pytest.approx(-2.78)
    assert trading_costs_calculator(swap_spec, "BUY", 2000, 0.1, 1, 2)["status"] == "invalid_input"


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


def test_scenario_simulator_is_seeded_bounded_and_not_a_backtest():
    first = scenario_simulator(10_000, 0.5, 50, 2, 80, 3, runs=100, seed=42)
    again = scenario_simulator(10_000, 0.5, 50, 2, 80, 3, runs=100, seed=42)
    assert first == again
    assert first["status"] == "ready"
    assert first["ending_equity_p10"] <= first["ending_equity_median"] <= first["ending_equity_p90"]
    assert first["expectancy_per_trade_at_start"] == pytest.approx(22)
    assert first["expectancy_pct_of_starting_equity"] == pytest.approx(0.22)
    assert "not historical backtest" in first["disclaimer"]
    assert scenario_simulator(10_000, 0.5, 50, 2, 1001, 0)["status"] == "invalid_input"
    assert scenario_simulator(1e308, 100, 100, 1000, 1000, runs=50)["status"] == "unavailable"


def test_capital_growth_uses_only_explicit_period_assumptions():
    result = capital_growth_calculator(1000, -2, 1, 4, 2, 10, 2)
    assert result["status"] == "ready"
    assert result["low_case"] == pytest.approx(960.4)
    assert result["base_case"] == pytest.approx(1020.1)
    assert result["high_case"] == pytest.approx(1081.6)
    assert result["after_assumed_losing_streak"] == pytest.approx(810)
    assert result["losing_streak_drawdown_pct"] == pytest.approx(19)
    assert capital_growth_calculator(1000, -100, 1, 2, 3)["status"] == "invalid_input"
    assert capital_growth_calculator(1000, 4, 1, -2, 3)["status"] == "invalid_input"


def test_currency_conversion_requires_a_resolved_timestamped_rate():
    converted = currency_conversion_calculator(100, "USD", "THB", 34.6, "ticker", 1234)
    assert converted["status"] == "ready"
    assert converted["converted_amount"] == 3460
    assert converted["captured_at"] == 1234
    assert currency_conversion_calculator(100, "USD", "THB", 1, "unknown", None)["status"] == "unavailable"
    assert currency_conversion_calculator(100, "USD", "USD", 1, "identity", None)["converted_amount"] == 100


def test_calculator_scenarios_are_user_scoped_and_only_store_manual_inputs(client, auth):
    from services.api_gateway.deps import current_user

    saved = client.post("/api/risk/calculator/scenarios", headers=auth, json={
        "name": "Conservative baseline", "tool": "scenario",
        "inputs": {"manual_equity": 10000, "risk_pct": 0.5, "win_rate_pct": 45},
    })
    assert saved.status_code == 200, saved.text
    item = saved.json()["scenario"]
    assert item["source"] == "manual_sandbox"
    assert set(item["inputs"]) == {"manual_equity", "risk_pct", "win_rate_pct"}

    listed = client.get("/api/risk/calculator/scenarios", headers=auth)
    assert listed.status_code == 200
    assert item["id"] in {row["id"] for row in listed.json()["scenarios"]}

    client.app.dependency_overrides[current_user] = lambda: {
        "email": "other-user@no7.ai", "tenant_id": "default", "role": "trader",
    }
    try:
        other_list = client.get("/api/risk/calculator/scenarios", headers=auth)
        assert other_list.status_code == 200
        assert item["id"] not in {row["id"] for row in other_list.json()["scenarios"]}
        assert client.delete(f"/api/risk/calculator/scenarios/{item['id']}",
                             headers=auth).status_code == 404
    finally:
        client.app.dependency_overrides.pop(current_user, None)

    assert client.delete(f"/api/risk/calculator/scenarios/{item['id']}",
                         headers=auth).status_code == 200


@pytest.mark.parametrize("payload", [
    {"name": "", "tool": "scenario", "inputs": {"risk_pct": 1}},
    {"name": "bad scope", "tool": "scenario", "inputs": {"broker_id": "live", "risk_pct": 1}},
    {"name": "bad value", "tool": "scenario", "inputs": {"risk_pct": "0.5"}},
    {"name": "wrong tool", "tool": "margin", "inputs": {"lot": 1}},
])
def test_calculator_scenario_save_rejects_non_manual_or_invalid_payload(client, auth, payload):
    response = client.post("/api/risk/calculator/scenarios", headers=auth, json=payload)
    assert response.status_code == 422


def test_trade_review_whatif_separates_actual_and_manual_preview_without_execution(
        client, auth, runtime, monkeypatch):
    from unittest.mock import Mock

    from packages.shared_schemas.models import Direction, TradeRecord

    identity = runtime.gateway._assert_account(runtime.adapter)
    runtime.db.kv_set("account-owner:" + runtime.adapter.id, identity)
    trade = TradeRecord(
        ticket="whatif-closed-1", symbol="XAUUSD", direction=Direction.up,
        volume=0.1, entry=2000, exit=2010, sl=1990, tp=2020,
        opened_at=1_700_000_000, closed_at=1_700_000_600, points=100,
        gross_pnl=100, costs=1, swap=-0.5, pnl=98.5, r_multiple=1.0,
        broker_id=runtime.adapter.id,
    )
    runtime.gateway.record_trade(trade)
    monkeypatch.setattr(runtime.market, "spec", lambda _symbol: SPEC)
    submit, modify, close = Mock(), Mock(), Mock()
    monkeypatch.setattr(runtime.gateway, "submit", submit)
    monkeypatch.setattr(runtime.gateway, "modify", modify)
    monkeypatch.setattr(runtime.gateway, "close", close)
    orders_before = runtime.db.query_one("SELECT COUNT(*) AS n FROM orders")["n"]

    response = client.get(
        "/api/risk/calculator?tool=trade_review_whatif&trade_ticket=whatif-closed-1"
        "&whatif_entry=2001&whatif_stop_loss=1991&whatif_take_profit=2021",
        headers=auth,
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["actual"]["net_pnl"] == 98.5
    assert result["actual"]["entry"] == 2000
    assert result["whatif"]["entry"] == 2001
    assert result["whatif"]["risk_reward"]["status"] == "ready"
    assert result["execution_approved"] is False
    assert response.json()["provenance"]["account_scope_verified"] is True
    runtime.db.kv_set("account-owner:" + runtime.adapter.id, {"login": "other", "workspace_id": identity["workspace_id"]})
    denied = client.get(
        "/api/risk/calculator?tool=trade_review_whatif&trade_ticket=whatif-closed-1",
        headers=auth,
    )
    assert denied.status_code == 409
    runtime.db.kv_set("account-owner:" + runtime.adapter.id, identity)
    assert runtime.db.query_one("SELECT COUNT(*) AS n FROM orders")["n"] == orders_before
    submit.assert_not_called()
    modify.assert_not_called()
    close.assert_not_called()


def test_trade_review_whatif_cannot_read_another_broker_ticket(client, auth, runtime):
    from packages.shared_schemas.models import Direction, TradeRecord

    other = TradeRecord(
        ticket="whatif-private-other", symbol="XAUUSD", direction=Direction.down,
        volume=0.1, entry=2000, exit=1990, opened_at=1_700_000_000,
        closed_at=1_700_000_600, points=100, gross_pnl=100, costs=0,
        pnl=100, broker_id="another-account",
    )
    runtime.gateway.record_trade(other)
    response = client.get(
        "/api/risk/calculator?tool=trade_review_whatif&trade_ticket=whatif-private-other",
        headers=auth,
    )
    assert response.status_code == 404


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
        ("trading_costs", "&side=BUY&price=2000&lot=0.1&holding_nights=3&triple_swap_nights=1"),
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


def test_calculator_analysis_source_reuses_fresh_closed_bar_snapshot(client, auth, runtime, monkeypatch):
    from unittest.mock import Mock

    submit, modify, close = Mock(), Mock(), Mock()
    monkeypatch.setattr(runtime.gateway, "submit", submit)
    monkeypatch.setattr(runtime.gateway, "modify", modify)
    monkeypatch.setattr(runtime.gateway, "close", close)
    response = client.get("/api/analysis/XAUUSD?fresh=true", headers=auth)
    assert response.status_code == 200
    snapshot = response.json()["snapshot"]
    assert snapshot["timeframe"] == "M5"
    assert isinstance(snapshot["server_time"], int)
    assert isinstance(snapshot["data_quality"].get("ok"), bool)
    assert isinstance(snapshot["indicators"].get("atr14_valid"), bool)
    submit.assert_not_called()
    modify.assert_not_called()
    close.assert_not_called()


def _ready_manual_preview_context(runtime, monkeypatch):
    from packages.shared_schemas.models import SymbolSpec

    ctx = runtime.analysis.snapshot("XAUUSD")
    ctx.snapshot.spec = SymbolSpec(
        symbol="XAUUSD", digits=2, point=0.01, tick_size=0.05,
        contract_size=100, min_lot=0.01, max_lot=50, lot_step=0.01,
        spread_typical_points=2, commission_per_lot_round_turn=7,
        profit_currency="USD", account_currency="USD",
        quote_to_account_rate=1, rate_source="identity", spec_complete=True,
    )
    ctx.snapshot.data_quality = {
        "ok": True, "health": "connected", "feed": "simulated",
        "staleness_seconds": 0, "spread_points": 2, "reason": "",
    }
    ctx.snapshot.indicators.atr14_valid = True
    ctx.snapshot.indicators.atr_points = 100
    ctx.frames["M5"] = ctx.frames["M5"].tail(100).copy()
    closed_at = int(ctx.frames["M5"]["t"].iloc[-1]) + 300
    monkeypatch.setattr(runtime.market, "now", lambda: closed_at)
    monkeypatch.setattr(runtime.analysis, "snapshot", lambda _symbol: ctx)
    return ctx


def test_auto_sl_tp_calculator_uses_fresh_snapshot_and_never_executes(
        client, auth, runtime, monkeypatch):
    import copy
    from unittest.mock import Mock

    _ready_manual_preview_context(runtime, monkeypatch)
    submit, modify, close = Mock(), Mock(), Mock()
    monkeypatch.setattr(runtime.gateway, "submit", submit)
    monkeypatch.setattr(runtime.gateway, "modify", modify)
    monkeypatch.setattr(runtime.gateway, "close", close)
    orders_before = runtime.db.query_one("SELECT COUNT(*) AS n FROM orders")["n"]
    risk_config_before = copy.deepcopy(runtime.settings.risk_cfg())

    response = client.get(
        "/api/risk/calculator?tool=auto_sl_tp&symbol=XAUUSD&entry=2000&side=BUY"
        "&manual_equity=12345&risk_pct=0.5&stop_mode=atr&target_mode=fixed",
        headers=auth,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    preview = body["result"]
    assert preview["status"] in {"ready", "blocked"}
    assert preview["source"] == "manual_sandbox"
    assert preview["execution_approved"] is False
    assert preview["risk_budget"] == pytest.approx(61.725)
    assert body["provenance"]["equity_source"] == "manual_sandbox"
    assert body["provenance"]["closed_m5_age_seconds"] == 0
    assert runtime.db.query_one("SELECT COUNT(*) AS n FROM orders")["n"] == orders_before
    assert runtime.settings.risk_cfg() == risk_config_before
    submit.assert_not_called()
    modify.assert_not_called()
    close.assert_not_called()


def test_auto_sl_tp_calculator_fails_closed_on_stale_market_data(
        client, auth, runtime, monkeypatch):
    from unittest.mock import Mock

    ctx = _ready_manual_preview_context(runtime, monkeypatch)
    ctx.snapshot.data_quality = {
        "ok": False, "health": "disconnected", "feed": "simulated",
        "staleness_seconds": 999, "spread_points": None, "reason": "stale test quote",
    }
    submit, modify, close = Mock(), Mock(), Mock()
    monkeypatch.setattr(runtime.gateway, "submit", submit)
    monkeypatch.setattr(runtime.gateway, "modify", modify)
    monkeypatch.setattr(runtime.gateway, "close", close)

    response = client.get(
        "/api/risk/calculator?tool=auto_sl_tp&symbol=XAUUSD&entry=2000&side=SELL"
        "&manual_equity=10000&risk_pct=0.5&stop_mode=atr_structure",
        headers=auth,
    )

    assert response.status_code == 200, response.text
    preview = response.json()["result"]
    assert preview["status"] == "unavailable"
    assert preview["plan"] is None
    assert preview["blockers"] == ["stale test quote"]
    submit.assert_not_called()
    modify.assert_not_called()
    close.assert_not_called()


def test_auto_sl_tp_calculator_rejects_invalid_manual_inputs(client, auth, runtime, monkeypatch):
    from unittest.mock import Mock

    snapshot = Mock()
    monkeypatch.setattr(runtime.analysis, "snapshot", snapshot)
    response = client.get(
        "/api/risk/calculator?tool=auto_sl_tp&symbol=XAUUSD&entry=2000&side=BUY"
        "&risk_pct=0.5&stop_mode=fixed",
        headers=auth,
    )

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["status"] == "invalid_input"
    assert result["plan"] is None
    snapshot.assert_not_called()


def test_read_only_scenario_and_growth_tools_use_user_inputs(client, auth, runtime, monkeypatch):
    from unittest.mock import Mock

    submit, modify, close = Mock(), Mock(), Mock()
    monkeypatch.setattr(runtime.gateway, "submit", submit)
    monkeypatch.setattr(runtime.gateway, "modify", modify)
    monkeypatch.setattr(runtime.gateway, "close", close)
    orders_before = runtime.db.query_one("SELECT COUNT(*) AS n FROM orders")["n"]
    scenario = client.get(
        "/api/risk/calculator?tool=scenario&manual_equity=10000&risk_pct=0.5"
        "&win_rate_pct=55&reward_risk=2&trades=30&runs=50&seed=11",
        headers=auth,
    )
    growth = client.get(
        "/api/risk/calculator?tool=capital_growth&manual_equity=10000"
        "&low_return_pct=-2&base_return_pct=1&high_return_pct=4&periods=12&loss_streak=5",
        headers=auth,
    )
    assert scenario.status_code == growth.status_code == 200
    assert scenario.json()["result"]["status"] == "ready"
    assert scenario.json()["result"]["source"] == "manual_sandbox"
    assert growth.json()["result"]["status"] == "ready"
    assert growth.json()["result"]["source"] == "manual_sandbox"
    assert runtime.db.query_one("SELECT COUNT(*) AS n FROM orders")["n"] == orders_before
    submit.assert_not_called()
    modify.assert_not_called()
    close.assert_not_called()


def test_capital_growth_api_preserves_explicit_zero_risk(client, auth):
    response = client.get(
        "/api/risk/calculator?tool=capital_growth&manual_equity=10000"
        "&low_return_pct=0&base_return_pct=1&high_return_pct=2&risk_pct=0&loss_streak=4",
        headers=auth,
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["status"] == "ready"
    assert result["risk_pct"] == 0
    assert result["after_assumed_losing_streak"] == 10000
    assert result["losing_streak_drawdown_pct"] == 0


def test_currency_converter_uses_only_fresh_resolved_market_fx(client, auth, runtime, monkeypatch):
    from packages.shared_schemas.models import Tick

    captured_at = runtime.market.now()
    monkeypatch.setattr(runtime.market, "ticker", lambda pair: Tick(
        t=captured_at, bid=34.5, ask=34.7, spread_points=20, last=34.6))
    monkeypatch.setattr(runtime.market, "data_quality", lambda pair, timeframe: {
        "ok": True, "feed": "mt5-live", "staleness_seconds": 0.5,
    })
    response = client.get(
        "/api/risk/calculator?tool=currency_convert&amount=100&from_currency=USD&to_currency=THB",
        headers=auth,
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["status"] == "ready"
    assert result["rate_pair"] == "USDTHB"
    assert result["rate"] == pytest.approx(34.6)
    assert result["converted_amount"] == pytest.approx(3460)
    assert result["captured_at"] == captured_at


def test_currency_converter_suppresses_stale_market_fx(client, auth, runtime, monkeypatch):
    from packages.shared_schemas.models import Tick

    captured_at = runtime.market.now() - 60
    monkeypatch.setattr(runtime.market, "ticker", lambda pair: Tick(
        t=captured_at, bid=34.5, ask=34.7, spread_points=20, last=34.6))
    monkeypatch.setattr(runtime.market, "data_quality", lambda pair, timeframe: {
        "ok": True, "feed": "mt5-live", "staleness_seconds": 60,
    })
    response = client.get(
        "/api/risk/calculator?tool=currency_convert&amount=100&from_currency=USD&to_currency=THB",
        headers=auth,
    )
    assert response.status_code == 200, response.text
    assert response.json()["result"]["status"] == "unavailable"
    assert response.json()["result"]["converted_amount"] is None


def test_100_point_preview_reuses_gate_math_without_reading_or_writing_candidate_state(
        client, auth, runtime, monkeypatch):
    from unittest.mock import Mock

    from packages.shared_schemas.models import Direction, SymbolSpec, Tick

    ctx = runtime.analysis.snapshot("XAUUSD")
    ctx.snapshot.spec = SymbolSpec(
        symbol="XAUUSD", digits=2, point=0.01, tick_size=0.05,
        contract_size=100, min_lot=0.01, max_lot=50, lot_step=0.01,
        profit_currency="USD", account_currency="USD", quote_to_account_rate=1,
        rate_source="identity", spec_complete=True,
    )
    ctx.snapshot.data_quality = {"ok": True, "feed": "simulated", "staleness_seconds": 0}
    ctx.frames["M1"] = ctx.frames["M1"].tail(100).copy()
    ctx.frames["M1"].loc[ctx.frames["M1"].index[-1], "c"] = 2000.0
    last_open = int(ctx.frames["M1"]["t"].iloc[-1])
    monkeypatch.setattr(runtime.market, "now", lambda: last_open + 60)
    monkeypatch.setattr(runtime.analysis, "snapshot", lambda _symbol: ctx)
    monkeypatch.setattr(runtime.market, "ticker", lambda _symbol, _broker_id=None: Tick(
        t=last_open + 60, bid=2000.0, ask=2000.1, spread_points=10, last=2000.0))
    ctx.snapshot.trend = [
        item.model_copy(update={"direction": Direction.up}) if item.timeframe.upper() == "M5" else item
        for item in ctx.snapshot.trend
    ]
    submit, modify, close = Mock(), Mock(), Mock()
    monkeypatch.setattr(runtime.gateway, "submit", submit)
    monkeypatch.setattr(runtime.gateway, "modify", modify)
    monkeypatch.setattr(runtime.gateway, "close", close)
    confirmations_before = runtime.db.query_one(
        "SELECT COUNT(*) AS n FROM kv WHERE key LIKE 'signal-confirmation-v4:%'")["n"]

    response = client.get(
        "/api/risk/calculator?tool=confirmation_100pt&symbol=XAUUSD"
        "&side=BUY&reference_price=1999",
        headers=auth,
    )

    assert response.status_code == 200, response.text
    preview = response.json()["result"]
    assert preview["status"] == "preview_match"
    assert preview["closed_m1_progress_points"] == pytest.approx(100)
    assert preview["m5_aligned"] is True
    assert preview["execution_approved"] is False
    assert preview["persisted_confirmation_read"] is False
    assert runtime.db.query_one(
        "SELECT COUNT(*) AS n FROM kv WHERE key LIKE 'signal-confirmation-v4:%'")["n"] == confirmations_before
    submit.assert_not_called()
    modify.assert_not_called()
    close.assert_not_called()


def test_100_point_preview_fails_closed_when_current_tick_is_invalid(client, auth, runtime, monkeypatch):
    from packages.shared_schemas.models import SymbolSpec, Tick

    ctx = runtime.analysis.snapshot("XAUUSD")
    ctx.snapshot.spec = SymbolSpec(
        symbol="XAUUSD", digits=2, point=0.01, tick_size=0.05,
        contract_size=100, min_lot=0.01, max_lot=50, lot_step=0.01,
        profit_currency="USD", account_currency="USD", quote_to_account_rate=1,
        rate_source="identity", spec_complete=True,
    )
    ctx.snapshot.data_quality = {"ok": True, "feed": "simulated", "staleness_seconds": 0}
    ctx.frames["M1"] = ctx.frames["M1"].tail(100).copy()
    last_open = int(ctx.frames["M1"]["t"].iloc[-1])
    monkeypatch.setattr(runtime.market, "now", lambda: last_open + 60)
    monkeypatch.setattr(runtime.analysis, "snapshot", lambda _symbol: ctx)
    monkeypatch.setattr(runtime.market, "ticker", lambda *_args: Tick(
        t=last_open + 60, bid=float("nan"), ask=2000.1, spread_points=10, last=2000.0))

    response = client.get(
        "/api/risk/calculator?tool=confirmation_100pt&symbol=XAUUSD"
        "&side=BUY&reference_price=1999",
        headers=auth,
    )
    assert response.status_code == 200, response.text
    assert response.json()["result"]["status"] == "unavailable"
    assert response.json()["result"]["execution_approved"] is False


def test_margin_calculator_is_unavailable_without_verified_mt5_adapter(client, auth, runtime):
    response = client.get(
        "/api/risk/calculator?tool=margin&symbol=XAUUSD&side=BUY&lot=0.1",
        headers=auth,
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["status"] == "unavailable"
    assert result["required_margin"] is None
    assert response.json()["provenance"]["account_scope_verified"] is False
