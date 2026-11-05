"""Multi-timeframe trend detection."""
from __future__ import annotations

import numpy as np

from packages.indicators import core as ta
from packages.market_structure.structure import detect_events, find_swings, structure_bias
from packages.shared_schemas.models import Direction, TrendReading


def read_trend(df, timeframe: str, spec_point: float = 0.01) -> TrendReading:
    if len(df) < 60:
        return TrendReading(timeframe=timeframe, direction=Direction.sideways, strength=0.0, note="insufficient history")
    close = df["c"].to_numpy(float)
    ema20 = ta.ema(close, 20)
    ema50 = ta.ema(close, 50)
    ema200 = ta.ema(close, 200)
    adx = ta.adx(df["h"], df["l"], close, 14)
    slope50 = ta.slope(close, 20)

    i = len(close) - 1
    price = close[i]
    e20, e50, e200 = ema20[i], ema50[i], ema200[i]
    a = adx[i] if np.isfinite(adx[i]) else 0.0
    sl = slope50[i] if np.isfinite(slope50[i]) else 0.0

    votes = 0.0
    votes += 1.0 if (np.isfinite(e20) and np.isfinite(e50) and e20 > e50) else -1.0
    votes += 1.0 if (np.isfinite(e200) and price > e200) else -1.0
    votes += 1.0 if sl > 0 else -1.0

    swings = find_swings(df)
    events = detect_events(df, swings)
    bias, bias_conf = structure_bias(swings, events)
    votes += (1.0 if bias == Direction.up else -1.0 if bias == Direction.down else 0.0) * bias_conf

    strength = min(1.0, abs(votes) / 4.0)
    trend_strength = min(1.0, a / 40.0)
    strength = round(min(1.0, 0.6 * strength + 0.4 * trend_strength), 3)

    if a >= 20 and abs(votes) >= 1.2:
        direction = Direction.up if votes > 0 else Direction.down
    elif abs(votes) < 0.8:
        direction = Direction.sideways
    else:
        direction = Direction.up if votes > 0 else Direction.down
        strength = min(strength, 0.55)

    ema_gap_points = (price - e200) / spec_point if np.isfinite(e200) and spec_point else 0.0
    note_parts = [
        f"EMA20 {'>' if e20 >= e50 else '<'} EMA50",
        f"price {'above' if price > e200 else 'below'} EMA200" if np.isfinite(e200) else "EMA200 n/a",
        f"ADX {a:.1f}",
        f"structure {bias.value}",
    ]
    return TrendReading(
        timeframe=timeframe,
        direction=direction,
        strength=strength,
        adx=round(float(a), 2),
        ema_slope_points=round(float(sl) / spec_point, 1) if spec_point else 0.0,
        price_vs_ema200_pct=round(float((price - e200) / e200 * 100), 3) if np.isfinite(e200) and e200 else 0.0,
        note=", ".join(note_parts) + f" (EMA200 distance {ema_gap_points:,.0f} pts)",
    )


def alignment_score(trends: list[TrendReading], direction: Direction) -> tuple[float, list[str]]:
    """0..1 alignment of HTF/LTF trends with the intended direction."""
    weights = {"H4": 1.4, "H1": 1.2, "M15": 1.0, "M5": 0.8, "M1": 0.5}
    total = 0.0
    got = 0.0
    notes: list[str] = []
    for reading in trends:
        w = weights.get(reading.timeframe, 0.6)
        total += w
        if reading.direction == direction:
            got += w * (0.5 + 0.5 * reading.strength)
            notes.append(f"{reading.timeframe} aligned ({reading.direction.value}, adx {reading.adx:.0f})")
        elif reading.direction == Direction.sideways:
            got += w * 0.25
            notes.append(f"{reading.timeframe} sideways")
        else:
            got += 0.0
            notes.append(f"{reading.timeframe} opposes ({reading.direction.value})")
    return (got / total if total else 0.0), notes
