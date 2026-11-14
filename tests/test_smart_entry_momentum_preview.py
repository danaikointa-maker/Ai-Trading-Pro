from packages.shared_schemas.models import Direction, StochasticReading
from services.strategy_engine.momentum_veto import preview_stochastic_veto


def momentum(tf, direction="bullish", fresh=True):
    return StochasticReading(timeframe=tf, k=70, d=60, direction=direction, fresh=fresh)


def test_three_confirmed_timeframes_align_without_granting_execution():
    result = preview_stochastic_veto([momentum(tf) for tf in ("M5", "M15", "H1")], Direction.up)
    assert result["would_block"] is False
    assert result["activated"] is False
    assert result["execution_effect"] == "none"


def test_stale_missing_or_conflicting_timeframe_requires_wait():
    scenarios = [
        [momentum("M5"), momentum("M15")],
        [momentum("M5"), momentum("M15", fresh=False), momentum("H1")],
        [momentum("M5"), momentum("M15", direction="bearish"), momentum("H1")],
    ]
    assert all(preview_stochastic_veto(rows, Direction.up)["would_block"] for rows in scenarios)
    assert preview_stochastic_veto([momentum(tf) for tf in ("M5", "M15", "H1")],
                                  Direction.down)["would_block"]
