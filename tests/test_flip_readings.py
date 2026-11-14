"""Closed-bar and prior-level provenance for dashboard SR-flip readings."""
import pandas as pd

from packages.market_structure.structure import Swing
from packages.strategy_rules.flip_readings import confirmed_flip_readings


def _history() -> pd.DataFrame:
    # Historical high at index 1 is confirmed at index 3; breakout at 5,
    # retest at 7. No event may be announced from the earlier prefix.
    closes = [98, 99, 98, 98, 99, 101, 102, 101]
    highs = [99, 100, 99, 99, 99.5, 102, 103, 102]
    lows = [97, 98, 97, 97, 98, 99, 101, 99.9]
    return pd.DataFrame({
        "t": [1000 + 300 * i for i in range(len(closes))],
        "c": closes, "h": highs, "l": lows, "atr": [1.0] * len(closes),
    })


def test_flip_reading_emerges_only_after_closed_retest():
    candles = _history()
    swing = Swing(idx=1, t=1300, price=100.0, kind="high")
    assert confirmed_flip_readings(candles.iloc[:7], [swing], 0.01) == []
    events = confirmed_flip_readings(candles, [swing], 0.01)
    assert len(events) == 1
    assert events[0].direction == "resistance_to_support"
    assert events[0].source_swing_t == 1300
    assert (events[0].break_t, events[0].confirmed_t) == (2500, 3100)


def test_wrong_source_side_and_unconfirmed_swing_not_reported():
    candles = _history()
    low_swing = Swing(idx=1, t=1300, price=100.0, kind="low")
    unconfirmed = Swing(idx=1, t=1300, price=100.0, kind="high", confirmed=False)
    assert confirmed_flip_readings(candles, [low_swing, unconfirmed], 0.01) == []


def test_bounded_age_and_invalid_point():
    candles = _history()
    swing = Swing(idx=1, t=1300, price=100.0, kind="high")
    assert confirmed_flip_readings(candles, [swing], 0.01, max_age_bars=1) != []
    assert confirmed_flip_readings(candles, [swing], 0.01, max_age_bars=0) == []
    assert confirmed_flip_readings(candles, [swing], 0.0) == []
    candles.loc[4, "c"] = float("nan")
    assert confirmed_flip_readings(candles, [swing], 0.01) == []
