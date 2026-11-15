"""Read-only SR-flip annotations built from pre-confirmed swing levels.

These readings are intentionally not inputs to the order executor or risk gate.
They consume completed bars and only emit a flip after its retest bar closes.
"""
from __future__ import annotations

import math

import pandas as pd

from packages.market_structure.structure import Swing
from packages.shared_schemas.models import SRFlipReading
from packages.strategy_rules.sr_flip import detect_sr_flips


def confirmed_flip_readings(
    candles: pd.DataFrame,
    swings: list[Swing],
    point: float,
    *,
    swing_confirmation_bars: int = 2,
    max_age_bars: int = 120,
    limit: int = 8,
) -> list[SRFlipReading]:
    """Find recent break/retests without activating a future swing prematurely.

    A level becomes eligible only *after* the swing's confirmation bars.
    Resistance must break upward, support downward; a close on the new side
    after a later touch is required. `candles` must already exclude the live bar.
    """
    if len(candles) < 5 or not swings or limit < 1 or not math.isfinite(point) or point <= 0:
        return []

    closes = candles["c"].to_numpy(dtype=float)
    highs = candles["h"].to_numpy(dtype=float)
    lows = candles["l"].to_numpy(dtype=float)
    times = candles["t"].to_numpy(dtype=int)
    # Corrupt source bars should not take the whole analysis endpoint offline.
    if not all(
        math.isfinite(close) and math.isfinite(high) and math.isfinite(low)
        and low <= close <= high
        for close, high, low in zip(closes, highs, lows)
    ):
        return []
    readings: list[SRFlipReading] = []
    oldest_index = max(0, len(candles) - max_age_bars)

    for swing in swings[-40:]:
        # Do not use the pivot until its full confirmation window is complete.
        active_from = swing.idx + swing_confirmation_bars
        if not swing.confirmed or active_from >= len(candles) - 2:
            continue

        atr = float(candles["atr"].iloc[active_from]) if "atr" in candles else math.nan
        tolerance = max(2 * point, 0.1 * atr if math.isfinite(atr) and atr > 0 else 0.0)
        for event in detect_sr_flips(
            closes[active_from:], highs[active_from:], lows[active_from:],
            swing.price, tolerance=tolerance,
        ):
            if swing.kind == "high" and event.direction != "resistance_to_support":
                continue
            if swing.kind == "low" and event.direction != "support_to_resistance":
                continue
            break_index = active_from + event.break_index
            retest_index = active_from + event.retest_index
            if retest_index < oldest_index:
                continue
            readings.append(SRFlipReading(
                level=float(swing.price), direction=event.direction,
                source_swing_t=swing.t, break_t=int(times[break_index]),
                retest_t=int(times[retest_index]), confirmed_t=int(times[retest_index]),
            ))

    # Multiple nearby historical swings can describe the same break/retest;
    # keep a bounded, deterministic view (never used as trading permission).
    readings.sort(key=lambda event: (event.confirmed_t, event.source_swing_t), reverse=True)
    return readings[:limit]
