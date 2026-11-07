"""MT5's nine swap modes must not be read as one unit.

The unit decides the magnitude: "money per lot" read as "percent per year" turns
-7.5 into a fraction of notional, and a reopen price shift read as money invents a
dollar figure. These tests pin the mapping using a fake `symbol_info`, so nothing
here needs a terminal.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from integrations.brokers.mt5_live import MT5Broker


def info(mode: int, long_raw: float = -7.5, short_raw: float = 2.5) -> SimpleNamespace:
    return SimpleNamespace(swap_mode=mode, swap_long=long_raw, swap_short=short_raw)


def test_points_mode_stays_points():
    out = MT5Broker._swap_fields(info(MT5Broker.SWAP_MODE_POINTS, -120.0, 45.0), 1.0)
    assert out == {"swap_mode": "points", "swap_long_points": -120.0, "swap_short_points": 45.0}


@pytest.mark.parametrize("mode", [MT5Broker.SWAP_MODE_INTEREST_CURRENT,
                                  MT5Broker.SWAP_MODE_INTEREST_OPEN])
def test_both_interest_modes_are_percent(mode):
    """Mode 6 (INTEREST_OPEN) used to be zeroed, which hid a real cost."""
    out = MT5Broker._swap_fields(info(mode), 1.0)
    assert out["swap_mode"] == "percent"
    assert out["swap_long_pct"] == -7.5
    assert out["swap_short_pct"] == 2.5


def test_margin_currency_mode_is_money_not_percent():
    """Mode 3 is CURRENCY_MARGIN; reading it as percent inflates it by the notional."""
    out = MT5Broker._swap_fields(info(MT5Broker.SWAP_MODE_CURRENCY_MARGIN), 1.0)
    assert out["swap_mode"] == "money"
    assert out["swap_long_per_lot"] == -7.5


def test_deposit_currency_mode_is_money():
    out = MT5Broker._swap_fields(info(MT5Broker.SWAP_MODE_CURRENCY_DEPOSIT), 1.0)
    assert out["swap_mode"] == "money"
    assert out["swap_long_per_lot"] == -7.5


def test_symbol_currency_mode_uses_the_base_currency_rate():
    out = MT5Broker._swap_fields(info(MT5Broker.SWAP_MODE_CURRENCY_SYMBOL), rate=1.0,
                                 base_rate=1.1)
    assert out["swap_mode"] == "money"
    assert out["swap_long_per_lot"] == pytest.approx(-7.5 * 1.1)


def test_symbol_currency_without_a_rate_is_not_guessed():
    out = MT5Broker._swap_fields(info(MT5Broker.SWAP_MODE_CURRENCY_SYMBOL), rate=1.0)
    assert out["swap_long_per_lot"] == 0.0
    assert out["swap_short_per_lot"] == 0.0


def test_profit_currency_mode_converts_with_the_profit_rate():
    out = MT5Broker._swap_fields(info(MT5Broker.SWAP_MODE_CURRENCY_PROFIT), rate=0.25)
    assert out["swap_long_per_lot"] == pytest.approx(-7.5 * 0.25)


@pytest.mark.parametrize("mode", [MT5Broker.SWAP_MODE_REOPEN_CURRENT,
                                  MT5Broker.SWAP_MODE_REOPEN_BID, 42])
def test_reopen_and_unknown_modes_report_zero_not_face_value(mode):
    out = MT5Broker._swap_fields(info(mode), 1.0)
    assert out == {"swap_mode": "money", "swap_long_per_lot": 0.0,
                   "swap_short_per_lot": 0.0}


def test_disabled_mode_is_zero():
    out = MT5Broker._swap_fields(info(MT5Broker.SWAP_MODE_DISABLED, 0.0, 0.0), 1.0)
    assert out == {"swap_mode": "money", "swap_long_per_lot": 0.0,
                   "swap_short_per_lot": 0.0}
