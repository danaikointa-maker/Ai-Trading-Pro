"""Pure closed-candle support/resistance flip detection.

This module is deliberately independent of execution and UI. The caller must
supply *closed* candles in chronological order. No lookahead is used.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence


@dataclass(frozen=True)
class FlipEvent:
    level: float
    direction: Literal["support_to_resistance", "resistance_to_support"]
    break_index: int
    retest_index: int
    confirmed_index: int


def detect_sr_flips(
    closes: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    level: float,
    *,
    tolerance: float,
    max_retest_bars: int = 8,
) -> list[FlipEvent]:
    """Return confirmed break-and-retest flips without future candles.

    A break requires a close beyond the level +/- tolerance. A retest must
    occur on a later candle, touch the level's tolerance band, and close on
    the breakout side. Repeated retests after one break are not duplicated.

    This is a basic detector, not a complete trade entry signal. The caller
    must establish a meaningful prior S/R level independently.
    """
    if not (len(closes) == len(highs) == len(lows)):
        raise ValueError("OHLC arrays must have equal lengths")
    if tolerance < 0 or max_retest_bars < 1:
        raise ValueError("tolerance must be nonnegative and max_retest_bars >= 1")
    if not all(lo <= hi and lo <= close <= hi for close, lo, hi in zip(closes, lows, highs)):
        raise ValueError("invalid OHLC values")
    if len(closes) < 3:
        return []

    events: list[FlipEvent] = []
    pending: tuple[int, Literal["support_to_resistance", "resistance_to_support"]] | None = None
    for i in range(1, len(closes)):
        prev, close = closes[i - 1], closes[i]
        if pending is not None:
            broken_at, direction = pending
            if i - broken_at > max_retest_bars:
                pending = None
            else:
                if direction == "resistance_to_support":
                    if close < level - tolerance:
                        pending = None
                    elif lows[i] <= level + tolerance and close > level + tolerance:
                        events.append(FlipEvent(level, direction, broken_at, i, i))
                        pending = None
                        continue
                else:
                    if close > level + tolerance:
                        pending = None
                    elif highs[i] >= level - tolerance and close < level - tolerance:
                        events.append(FlipEvent(level, direction, broken_at, i, i))
                        pending = None
                        continue
                if pending is not None:
                    continue
        if prev <= level + tolerance and close > level + tolerance:
            pending = (i, "resistance_to_support")
        elif prev >= level - tolerance and close < level - tolerance:
            pending = (i, "support_to_resistance")
    return events
