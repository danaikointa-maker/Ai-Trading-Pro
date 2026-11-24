import math

import pytest

from services.strategy_engine.analysis import closed_atr_value


@pytest.mark.parametrize("raw", [float("nan"), float("inf"), 0.0, -1.0, None])
def test_invalid_closed_atr_keeps_legacy_fallback_but_marks_it_unverified(raw):
    value, valid = closed_atr_value(raw, 2000.0)
    assert value == pytest.approx(2.0)
    assert valid is False


def test_finite_positive_closed_atr_is_valid():
    assert closed_atr_value(1.25, 2000.0) == (1.25, True)


def test_invalid_fallback_price_does_not_create_a_fake_atr():
    assert closed_atr_value(math.nan, math.inf) == (0.0, False)
