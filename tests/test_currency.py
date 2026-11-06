"""P&L and exposure must be denominated in the *account* currency.

A JPY-quoted pair (USDJPY) books profit in JPY while the account is USD, so the
contract formula alone overstates money by the whole exchange rate (~157x). Every
engine that turns a price move into money — backtest, paper, the offline MT5
estimate, and the risk engine's notional exposure — has to apply the same
quote->account rate, otherwise the same trade is worth two different amounts
depending on which component reported it.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from integrations.brokers.paper import gross_pnl
from packages.shared_schemas.models import Direction, SymbolSpec, TradeMode
from services.backtest_engine.backtester import Backtester, SimPosition
from services.risk_engine.engine import RiskEngine

USDJPY_RATE = 1 / 157.2  # 1 JPY -> USD


def jpy_spec(rate: float = USDJPY_RATE, source: str = "ticker") -> SymbolSpec:
    return SymbolSpec(
        symbol="USDJPY", digits=3, point=0.001, tick_size=0.001, contract_size=100_000.0,
        min_lot=0.01, max_lot=50.0, lot_step=0.01, spread_typical_points=8.0,
        profit_currency="JPY", quote_to_account_rate=rate, rate_source=source,
    )


def usd_spec() -> SymbolSpec:
    return SymbolSpec(
        symbol="XAUUSD", digits=2, point=0.01, tick_size=0.01, contract_size=100.0,
        min_lot=0.01, max_lot=50.0, lot_step=0.01, spread_typical_points=25.0,
        profit_currency="USD", quote_to_account_rate=1.0, rate_source="identity",
    )


def _position(spec: SymbolSpec, direction: Direction, entry: float, volume: float) -> SimPosition:
    return SimPosition(
        direction=direction, entry=entry, sl=entry - 1, sl_initial=entry - 1, tps=[entry + 1],
        volumes=[volume], partials_done=0, remaining=volume, initial_volume=volume,
        opened_at=0, entry_bar=0, risk_amount=50.0, trade_mode=TradeMode.manual,
        strategy="test", signal_id="sig-1",
    )


# ------------------------------------------------------------------ spec helper
def test_one_yen_move_is_converted_to_usd():
    spec = jpy_spec()
    # 1.00 JPY of price movement on 1.00 lot = 100,000 JPY = 100,000 / 157.2 USD
    assert spec.pnl_in_account_currency(1.0, 1.0) == pytest.approx(100_000 / 157.2)


def test_usd_quoted_pair_is_unchanged():
    spec = usd_spec()
    assert spec.pnl_in_account_currency(1.0, 1.0) == pytest.approx(100.0)


# ------------------------------------------- backtest == paper (same trade, same money)
@pytest.mark.parametrize("direction", [Direction.up, Direction.down])
def test_backtest_floating_matches_paper_for_jpy_symbol(direction):
    spec = jpy_spec()
    entry, exit_price, volume = 157.00, 157.50, 0.10
    pos = _position(spec, direction, entry, volume)

    backtest = Backtester._floating(pos, exit_price, spec)
    paper = gross_pnl(direction, entry, exit_price, volume, spec)

    assert backtest == pytest.approx(paper)
    move = (exit_price - entry) if direction == Direction.up else (entry - exit_price)
    assert backtest == pytest.approx(move * 100_000 * volume / 157.2)


def test_backtest_does_not_report_yen_as_dollars():
    """The regression: a 0.5 JPY move on 0.1 lot is 31.81 USD, not 5,000."""
    spec = jpy_spec()
    pos = _position(spec, Direction.up, 157.00, 0.10)
    # 0.5 x 100,000 x 0.1 = 5,000 JPY -> / 157.2 = 31.81 USD
    assert Backtester._floating(pos, 157.50, spec) == pytest.approx(31.81, abs=0.01)
    assert Backtester._floating(pos, 157.50, spec) < 100  # never the raw yen amount


# ------------------------------------------------------------- MT5 offline estimate
def _mt5_broker(symbol_raw: dict):
    from integrations.brokers.mt5_live import MT5Broker

    profile = {"id": "test-broker", "symbols": {"USDJPY": symbol_raw}, "symbol_mapping": {}}
    return MT5Broker(profile)


def test_mt5_offline_estimate_matches_paper():
    broker = _mt5_broker({
        "digits": 3, "point": 0.001, "tick_size": 0.001, "contract_size": 100_000,
        "min_lot": 0.01, "max_lot": 50.0, "lot_step": 0.01, "spread_typical_points": 8.0,
        "profit_currency": "JPY", "quote_to_account_rate": USDJPY_RATE, "rate_source": "ticker",
    })
    spec = broker.symbol_spec("USDJPY")
    assert broker.calc_profit("USDJPY", Direction.up, 0.10, 157.00, 157.50) == pytest.approx(
        gross_pnl(Direction.up, 157.00, 157.50, 0.10, spec)
    )


def test_mt5_refuses_to_invent_a_rate():
    """No resolved rate => no number, instead of a 157x-too-large guess."""
    from integrations.brokers.base import BrokerError

    broker = _mt5_broker({
        "digits": 3, "point": 0.001, "tick_size": 0.001, "contract_size": 100_000,
        "min_lot": 0.01, "max_lot": 50.0, "lot_step": 0.01,
        "profit_currency": "JPY", "rate_source": "unknown",
    })
    assert broker.symbol_spec("USDJPY").sizing_blocked
    with pytest.raises(BrokerError):
        broker.calc_profit("USDJPY", Direction.up, 0.10, 157.00, 157.50)


# --------------------------------------------------------------- risk exposure
def _adapter(specs: dict[str, SymbolSpec], positions: list):
    return SimpleNamespace(
        symbol_spec=lambda symbol: specs[symbol],
        positions=lambda: positions,
    )


def test_notional_exposure_is_converted_to_account_currency():
    spec = jpy_spec()
    pos = SimpleNamespace(symbol="USDJPY", volume=0.50, entry=157.00, current_price=157.20)
    notional = RiskEngine._notional(_adapter({"USDJPY": spec}, [pos]), [pos])
    # 0.5 lot x 100,000 x 157.20 = 7,860,000 JPY = 50,000 USD, not 7.86 million USD
    assert notional == pytest.approx(0.50 * 100_000 * 157.20 / 157.2, rel=1e-6)
    assert notional == pytest.approx(50_000, rel=1e-3)


def test_gold_notional_stays_contract_times_price():
    spec = usd_spec()
    pos = SimpleNamespace(symbol="XAUUSD", volume=1.0, entry=3800.0, current_price=3810.0)
    assert RiskEngine._notional(_adapter({"XAUUSD": spec}, [pos]), [pos]) == pytest.approx(381_000.0)


def test_unresolved_rate_is_not_valued_at_one():
    spec = jpy_spec(rate=1.0, source="unknown")
    pos = SimpleNamespace(symbol="USDJPY", volume=0.50, entry=157.00, current_price=157.20)
    assert RiskEngine._notional(_adapter({"USDJPY": spec}, [pos]), [pos]) == 0.0
