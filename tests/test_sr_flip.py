"""Point-in-time checks for the isolated SR-flip detector."""
import pytest

from packages.strategy_rules.sr_flip import detect_sr_flips


def test_resistance_becomes_support_only_after_later_retest():
    closes = [99, 101, 103, 102]
    highs = [99.5, 101.5, 103.5, 103]
    lows = [98, 99.5, 102, 99.9]
    assert detect_sr_flips(closes[:2], highs[:2], lows[:2], 100, tolerance=0.2) == []
    result = detect_sr_flips(closes, highs, lows, 100, tolerance=0.2)
    assert len(result) == 1
    assert result[0].direction == "resistance_to_support"
    assert (result[0].break_index, result[0].retest_index) == (1, 3)


def test_support_becomes_resistance():
    closes = [101, 99, 97, 98]
    highs = [102, 100.5, 98, 100.1]
    lows = [100.5, 98, 96, 97.5]
    result = detect_sr_flips(closes, highs, lows, 100, tolerance=0.2)
    assert len(result) == 1
    assert result[0].direction == "support_to_resistance"


def test_reversal_invalidates_pending_break():
    closes = [99, 101, 99, 98]
    highs = [99.5, 102, 100, 99]
    lows = [98, 99, 98, 97]
    assert detect_sr_flips(closes, highs, lows, 100, tolerance=0.2) == []


def test_bad_input_rejected():
    with pytest.raises(ValueError):
        detect_sr_flips([100], [], [99], 100, tolerance=0.1)
