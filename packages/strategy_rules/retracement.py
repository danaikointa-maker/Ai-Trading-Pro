"""Point-in-time Fibonacci anchors for a *visual* retracement band.

This does not enter, approve, or modify trades. It identifies the most recent
pair of opposite, confirmed fractal swings already known on the closed bars.
"""
from __future__ import annotations

import pandas as pd

from packages.market_structure.structure import Swing
from packages.shared_schemas.models import FibonacciBand


def confirmed_fibonacci_band(
    closed_candles: pd.DataFrame,
    swings: list[Swing],
    digits: int,
    *,
    swing_confirmation_bars: int = 2,
    max_anchor_age_bars: int = 120,
) -> FibonacciBand | None:
    """Provide explicit anchors only once both swings are confirmed and recent."""
    confirmed = [swing for swing in swings if swing.confirmed]
    if len(confirmed) < 2 or closed_candles.empty:
        return None
    start, end = confirmed[-2:]
    confirmation_idx = end.idx + swing_confirmation_bars
    if (
        start.kind == end.kind
        or confirmation_idx >= len(closed_candles)
        or len(closed_candles) - 1 - end.idx > max_anchor_age_bars
        or start.price == end.price
    ):
        return None

    delta = end.price - start.price
    direction = "up" if delta > 0 else "down"
    # For a rising leg, retracements are measured downward from the last high;
    # for a falling leg, they are measured upward from the last low.
    return FibonacciBand(
        direction=direction,
        anchor_start_t=start.t, anchor_end_t=end.t,
        anchor_start_price=round(start.price, digits),
        anchor_end_price=round(end.price, digits),
        confirmed_t=int(closed_candles["t"].iloc[confirmation_idx]),
        level_50=round(end.price - delta * 0.5, digits),
        level_618=round(end.price - delta * 0.618, digits),
    )
