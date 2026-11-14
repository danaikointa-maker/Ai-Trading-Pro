"""Closed-bar Stochastic momentum evidence from three chart timeframes.

This layer is informational until its conflict/staleness behavior is validated
on point-in-time backtests. Missing data is explicitly marked unavailable.
"""
from __future__ import annotations

import math

import pandas as pd

from packages.indicators.core import stochastic
from packages.shared_schemas.models import StochasticReading


TIMEFRAME_SECONDS = {"M5": 300, "M15": 900, "H1": 3600}


def three_tf_stochastic(
    frames: dict[str, pd.DataFrame], reference_t: int,
) -> list[StochasticReading]:
    """Return M5/M15/H1 readings from already-closed candles.

    At most two timeframe periods of source lag are tolerated. A future-dated
    or insufficient frame cannot silently vote for either trading direction.
    """
    readings: list[StochasticReading] = []
    for tf, seconds in TIMEFRAME_SECONDS.items():
        frame = frames.get(tf)
        if frame is None or len(frame) < 18 or not {"t", "h", "l", "c"}.issubset(frame.columns):
            readings.append(StochasticReading(timeframe=tf, reason="แท่งเทียนยังไม่พอ"))
            continue

        source_t = int(frame["t"].iloc[-1])
        lag = reference_t - source_t
        if lag < 0 or lag > 2 * seconds:
            readings.append(StochasticReading(
                timeframe=tf, source_t=source_t, reason="ข้อมูลแท่งเทียนไม่ตรงเวลาหรือเก่าเกินไป",
            ))
            continue

        try:
            k_series, d_series = stochastic(frame["h"], frame["l"], frame["c"])
            k, d = float(k_series[-1]), float(d_series[-1])
        except (TypeError, ValueError, IndexError):
            readings.append(StochasticReading(timeframe=tf, source_t=source_t, reason="ข้อมูลราคาไม่ถูกต้อง"))
            continue
        if not (math.isfinite(k) and math.isfinite(d)):
            readings.append(StochasticReading(timeframe=tf, source_t=source_t, reason="ค่า K/D ยังไม่พร้อม"))
            continue

        direction = "bullish" if k > d + 0.5 else "bearish" if d > k + 0.5 else "neutral"
        readings.append(StochasticReading(
            timeframe=tf, k=round(k, 2), d=round(d, 2), direction=direction,
            source_t=source_t, fresh=True,
        ))
    return readings
