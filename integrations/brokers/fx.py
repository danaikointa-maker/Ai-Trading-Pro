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


def resolve_quote_rate(profit_currency: str, account_currency: str, price_of: PriceOf,
                       ) -> tuple[float, str]:
    """Return ``(rate, source)`` where ``source`` is one of the literals below."""
    profit = (profit_currency or "").upper()
    account = (account_currency or "").upper()
    if not profit or not account:
        return 1.0, "unknown"
    if profit == account:
        return 1.0, "identity"

    direct = price_of(f"{profit}{account}")
    if direct and direct > 0:
        return float(direct), "ticker"

    inverse = price_of(f"{account}{profit}")
    if inverse and inverse > 0:
        return 1.0 / float(inverse), "ticker"

    return 1.0, "unknown"


def mid_of_bid_ask(bid: float, ask: float) -> float:
    return (float(bid) + float(ask)) / 2.0
