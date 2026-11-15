"""Three-frame Stochastic readings only use completed, fresh OHLC history."""
import numpy as np
import pandas as pd
import pytest

from packages.indicators.core import stochastic
from packages.strategy_rules.stochastic_readings import three_tf_stochastic


def _frame(seconds: int, end: int, n: int = 35) -> pd.DataFrame:
    values = np.linspace(100, 120, n)
    return pd.DataFrame({
        "t": [end - (n - i - 1) * seconds for i in range(n)],
        "h": values + 1, "l": values - 1, "c": values + 0.3,
    })


def test_stochastic_no_future_leakage_and_flat_is_neutral():
    high = np.arange(50, dtype=float) + 2
    low = high - 3
    close = high - 0.5
    short_k, short_d = stochastic(high[:30], low[:30], close[:30])
    long_k, long_d = stochastic(high, low, close)
    np.testing.assert_allclose(short_k, long_k[:30], equal_nan=True)
    np.testing.assert_allclose(short_d, long_d[:30], equal_nan=True)
    flat_k, flat_d = stochastic([100] * 25, [100] * 25, [100] * 25)
    assert (flat_k[-1], flat_d[-1]) == (50, 50)


def test_stochastic_bad_input_rejected():
    with pytest.raises(ValueError):
        stochastic([1, 2], [0], [1, 1])
    with pytest.raises(ValueError):
        stochastic([1], [0], [0.5], period=0)


def test_three_frames_fresh_and_typed():
    ref = 180000
    frames = {
        "M5": _frame(300, ref),
        "M15": _frame(900, ref - 600),
        "H1": _frame(3600, ref - 1800),
    }
    result = three_tf_stochastic(frames, ref)
    assert [r.timeframe for r in result] == ["M5", "M15", "H1"]
    assert all(r.fresh and 0 <= r.k <= 100 and 0 <= r.d <= 100 for r in result)
    assert all(r.source_t <= ref for r in result)


def test_missing_stale_and_future_frame_does_not_vote():
    ref = 180000
    frames = {"M5": _frame(300, ref), "M15": _frame(900, ref - 3600),
              "H1": _frame(3600, ref + 3600)}
    result = three_tf_stochastic(frames, ref)
    assert result[0].fresh
    assert not result[1].fresh and result[1].direction == "unavailable"
    assert not result[2].fresh and result[2].direction == "unavailable"
    assert all(not r.fresh for r in three_tf_stochastic({}, ref))
