"""Confirmed, non-repainting Fibonacci chart anchors for rising/falling legs."""
import pandas as pd

from packages.market_structure.structure import Swing
from packages.strategy_rules.retracement import confirmed_fibonacci_band


def _candles(n: int = 10) -> pd.DataFrame:
    return pd.DataFrame({"t": [300 * i for i in range(n)]})


def test_upward_leg_levels_and_provenance():
    swings = [
        Swing(idx=1, t=300, price=90, kind="low"),
        Swing(idx=5, t=1500, price=110, kind="high"),
    ]
    assert confirmed_fibonacci_band(_candles(7), swings, 2) is None
    reading = confirmed_fibonacci_band(_candles(), swings, 2)
    assert reading.direction == "up"
    assert (reading.level_50, reading.level_618) == (100, 97.64)
    assert (reading.anchor_start_t, reading.anchor_end_t, reading.confirmed_t) == (300, 1500, 2100)


def test_downward_leg_and_unconfirmed_anchor():
    swings = [
        Swing(idx=1, t=300, price=110, kind="high"),
        Swing(idx=5, t=1500, price=90, kind="low"),
    ]
    reading = confirmed_fibonacci_band(_candles(), swings, 2)
    assert reading.direction == "down"
    assert (reading.level_50, reading.level_618) == (100, 102.36)
    swings[-1].confirmed = False
    assert confirmed_fibonacci_band(_candles(), swings, 2) is None


def test_stale_anchor_is_omitted():
    swings = [
        Swing(idx=1, t=300, price=90, kind="low"),
        Swing(idx=5, t=1500, price=110, kind="high"),
    ]
    assert confirmed_fibonacci_band(_candles(), swings, 2, max_anchor_age_bars=2) is None
