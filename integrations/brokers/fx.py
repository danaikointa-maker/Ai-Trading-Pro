"""Convert a symbol's profit currency into the account currency.

A broker reports profit in the symbol's *quote* currency: 1 point on one lot of
USDJPY is worth 100 JPY, not 100 USD. Sizing and P&L only make sense once that
amount is expressed in the currency the balance is kept in.

The rate is resolved from tickers the account can already see, so nothing extra
has to be downloaded:

* ``GBPUSD`` profit currency ``GBP`` on a USD account -> rate = mid(GBPUSD)
* ``USDJPY`` profit currency ``JPY`` on a USD account -> rate = 1 / mid(USDJPY)
* same currency -> 1.0

When neither pair is available the rate is reported as ``unknown``; callers must
then refuse to size a trade rather than silently apply 1.0.
"""

from __future__ import annotations

from typing import Callable

# A price lookup that returns a mid price, or None when the symbol is unknown.
PriceOf = Callable[[str], float | None]


# Anchors tried when neither the direct nor the inverse pair is quoted. USD first
# because most accounts and most liquid crosses go through it.
DEFAULT_ANCHORS = ("USD", "EUR", "GBP", "JPY", "CHF")


def _pair_rate(base: str, quote: str, price_of: PriceOf) -> float | None:
    """How many `quote` one unit of `base` is worth, or None when unquoted."""
    if base == quote:
        return 1.0
    direct = price_of(f"{base}{quote}")
    if direct and direct > 0:
        return float(direct)
    inverse = price_of(f"{quote}{base}")
    if inverse and inverse > 0:
        return 1.0 / float(inverse)
    return None


def resolve_quote_rate(profit_currency: str, account_currency: str, price_of: PriceOf,
                       anchors: tuple[str, ...] = DEFAULT_ANCHORS) -> tuple[float, str]:
    """Return ``(rate, source)`` where ``source`` is identity/ticker/triangulated/unknown."""
    profit = (profit_currency or "").upper()
    account = (account_currency or "").upper()
    if not profit or not account:
        return 1.0, "unknown"
    if profit == account:
        return 1.0, "identity"

    direct = _pair_rate(profit, account, price_of)
    if direct:
        return direct, "ticker"

    # e.g. GBP profit on a USD account with no GBPUSD quote, but EURUSD and
    # EURGBP are visible: 1 GBP = (EURGBP)^-1 EUR = EURUSD / EURGBP USD.
    for anchor in anchors or ():
        anchor = anchor.upper()
        if anchor in (profit, account):
            continue
        p = _pair_rate(profit, anchor, price_of)
        a = _pair_rate(account, anchor, price_of)
        if p and a:
            return p / a, "triangulated"

    return 1.0, "unknown"


def mid_of_bid_ask(bid: float, ask: float) -> float:
    return (float(bid) + float(ask)) / 2.0
