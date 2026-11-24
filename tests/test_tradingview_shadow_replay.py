from __future__ import annotations

import pandas as pd
import pytest

from packages.shared_schemas.models import SymbolSpec
from services.strategy_engine.tradingview_shadow import (
    ShadowCostAssumptions,
    ShadowNo7Decision,
    replay_tradingview_shadow,
)


def _evidence(*, bar_close: int = 600, received: int = 620,
              long_score: int = 80, short_score: int = 20,
              timeframe: str = "5", quality: str = "accepted_shadow") -> dict:
    return {
        "source_schema": "ai-agent-lens/v1",
        "event": "LONG_SETUP",
        "source_symbol": "OANDA:XAUUSD",
        "mapped_symbol": "XAUUSD",
        "timeframe": timeframe,
        "bar_close_utc": bar_close,
        "received_at_utc": received,
        "payload_sha256": f"{bar_close:064x}",
        "regime": "TREND_UP",
        "candle": {
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
            "direction": "bull", "body_pct": 25, "upper_wick_pct": 25,
            "lower_wick_pct": 25, "close_position_pct": 75,
            "closed_above_prev_high": False, "closed_below_prev_low": False,
            "pattern": "test",
        },
        "long_score": long_score,
        "short_score": short_score,
        "score_threshold": 70,
        "quality": quality,
        "features": {},
    }


def _spec(**changes) -> SymbolSpec:
    values = {
        "symbol": "XAUUSD", "digits": 2, "point": 0.01, "tick_size": 0.01,
        "contract_size": 100, "min_lot": 0.01, "max_lot": 50, "lot_step": 0.01,
        "commission_per_lot_round_turn": 7.0, "profit_currency": "USD",
        "account_currency": "USD", "source": "broker", "rate_source": "identity",
        "quote_to_account_rate": 1.0,
    }
    values.update(changes)
    return SymbolSpec(**values)


def _bars() -> pd.DataFrame:
    # t is the UTC close label; each open is priced only after the close label.
    return pd.DataFrame({
        "t": [300, 600, 900, 1200, 1500, 1800],
        "o": [100, 101, 102, 103, 104, 105],
        "c": [101, 102, 103, 104, 105, 106],
    })


def _replay(evidence=None, decisions=None, bars=None, spec=None, costs=None):
    return replay_tradingview_shadow(
        symbol="XAUUSD", timeframe="M5",
        evidence=[_evidence()] if evidence is None else evidence,
        no7_decisions=[ShadowNo7Decision(
            "XAUUSD", "5", 600, 650, "SELL", 60)] if decisions is None else decisions,
        closed_bars=_bars() if bars is None else bars,
        spec=_spec() if spec is None else spec,
        costs=ShadowCostAssumptions(10, 2, 1.0) if costs is None else costs,
        horizons_bars=(1,),
    )


def test_replay_matches_exact_bar_and_keeps_external_and_no7_scores_separate():
    result = _replay()

    assert result["comparison"] == {
        "exact_unique_matches": 1, "agreements": 0, "disagreements": 1,
        "neutral_agreements": 0, "mean_absolute_signed_score_gap": 120.0,
        "score_gap_samples": 1,
    }
    assert result["horizons"]["1"]["tradingview"]["mean_net_points"] == 79.0
    assert result["horizons"]["1"]["no7"]["mean_net_points"] == -121.0
    assert result["decision_influence"] is False
    assert result["execution_simulated"] is False


def test_replay_waits_until_after_alert_availability_and_ignores_signal_bar_prices():
    baseline = _replay()
    changed = _bars()
    changed.loc[changed["t"] <= 600, ["o", "c"]] = [1_000_000, 2_000_000]
    changed.loc[changed["t"] == 900, "o"] = 999_999  # bar opened before alert at 950
    late = _evidence(received=950)

    result = _replay(evidence=[late], bars=changed, decisions=[])

    # For a late alert, entry waits until t=1500 (open=1200), never the 900/1200
    # close-labelled candle whose open preceded the packet's receipt time.
    assert result["horizons"]["1"]["tradingview"]["mean_net_points"] == 79.0
    assert baseline["horizons"]["1"]["tradingview"]["samples"] == 1
    assert result["horizons"]["1"]["no7"]["samples"] == 0


def test_duplicate_evidence_for_same_closed_bar_is_excluded_as_ambiguous():
    result = _replay(evidence=[_evidence(), _evidence(long_score=90)])

    assert result["coverage"]["duplicate_evidence_excluded"] == 1
    assert result["coverage"]["unique_evidence"] == 0
    assert result["horizons"]["1"]["tradingview"]["samples"] == 0


def test_replay_uses_only_accepted_shadow_evidence():
    accepted = _evidence(bar_close=900, received=920, quality="accepted_shadow")
    unverified = _evidence(bar_close=600, quality="unverified")
    rejected = _evidence(bar_close=600, quality="rejected", long_score=95)
    decision = ShadowNo7Decision("XAUUSD", "M5", 900, 950, "SELL", 60)

    result = _replay(evidence=[unverified, rejected, accepted], decisions=[decision])

    assert result["comparison"]["exact_unique_matches"] == 1
    assert result["coverage"]["unique_evidence"] == 1
    assert result["coverage"]["evidence_excluded_by_quality"] == 2
    assert result["coverage"]["evidence_quality_counts"] == {
        "accepted_shadow": 1, "rejected": 1, "unverified": 1,
    }
    assert result["cost_assumptions"]["symbol_spec_source"] == "broker"
    assert result["horizons"]["1"]["tradingview"]["samples"] == 1


def test_replay_rejects_missing_or_untrusted_broker_cost_spec():
    with pytest.raises(ValueError, match="complete broker spec"):
        _replay(spec=_spec(spec_complete=False))
    with pytest.raises(ValueError, match="complete broker spec"):
        _replay(spec=_spec(rate_source="unknown"))
    with pytest.raises(ValueError, match="complete broker spec"):
        _replay(spec=_spec(source="declared"))
    with pytest.raises(ValueError, match="legal reference lot"):
        _replay(costs=ShadowCostAssumptions(10, 2, 0.015))


def test_replay_rejects_overflowed_derived_broker_point_value():
    with pytest.raises(ValueError, match="broker point value must be finite"):
        _replay(spec=_spec(point=1e308))


def test_replay_rejects_overflowed_cost_and_outcome_calculations():
    with pytest.raises(ValueError, match="estimated broker costs must remain finite"):
        _replay(costs=ShadowCostAssumptions(1e308, 1e308, 1.0))

    bars = _bars()
    bars["c"] = bars["c"].astype(float)
    bars.loc[bars["t"] == 1200, "c"] = 1e308
    with pytest.raises(ValueError, match="replay outcome must remain finite"):
        _replay(bars=bars)


def test_replay_rejects_duplicate_or_nonchronological_bar_timestamps():
    bars = _bars()
    bars.loc[3, "t"] = 900

    with pytest.raises(ValueError, match="strictly time-ordered and unique"):
        _replay(bars=bars)


def test_replay_excludes_no7_rows_with_nonmatching_symbol_or_timeframe():
    wrong_symbol = ShadowNo7Decision("XAGUSD", "M5", 600, 650, "SELL", 60)
    wrong_timeframe = ShadowNo7Decision("XAUUSD", "M15", 600, 650, "SELL", 60)

    result = _replay(decisions=[wrong_symbol, wrong_timeframe])

    assert result["comparison"]["exact_unique_matches"] == 0
    assert result["coverage"]["filtered_no7_symbol_or_timeframe"] == 2
    assert result["horizons"]["1"]["no7"]["samples"] == 0


def test_no_trade_is_a_valid_neutral_no7_decision():
    decision = ShadowNo7Decision("XAUUSD", "M5", 600, 650, "NO_TRADE", 20)
    result = _replay(
        evidence=[_evidence(long_score=30, short_score=20)], decisions=[decision])

    assert result["comparison"]["exact_unique_matches"] == 1
    assert result["comparison"]["agreements"] == 1
    assert result["comparison"]["neutral_agreements"] == 1
    assert result["horizons"]["1"]["no7"]["samples"] == 0
