"""Market structure: swing detection, HH/HL/LH/LL labelling, BOS and CHoCH.

All detection is closed-bar only. Swings need ``lookback`` bars of confirmation
before they are allowed to influence a decision, which is what keeps the
dashboard free of repainting structure.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from packages.shared_schemas.models import Direction, StructureEvent, SwingPoint


@dataclass
class Swing:
    idx: int
    t: int
    price: float
    kind: str          # "high" | "low"
    confirmed: bool = True
    label: str = ""


def find_swings(df, lookback: int = 2, min_displacement_atr: float = 0.2) -> list[Swing]:
    """Fractal swings, alternating high/low, labelled HH/HL/LH/LL."""
    highs = df["h"].to_numpy(dtype=float)
    lows = df["l"].to_numpy(dtype=float)
    times = df["t"].to_numpy(dtype=int)
    atr = df["atr"].to_numpy(dtype=float) if "atr" in df else np.full(len(df), np.nan)
    n = len(df)
    if n < lookback * 2 + 3:
        return []

    candidates: list[Swing] = []
    for i in range(lookback, n - lookback):
        window_h = highs[i - lookback:i + lookback + 1]
        window_l = lows[i - lookback:i + lookback + 1]
        a = atr[i] if np.isfinite(atr[i]) and atr[i] > 0 else 0.0
        if highs[i] == window_h.max() and (highs[i] - np.sort(window_h)[-2]) >= min_displacement_atr * a:
            candidates.append(Swing(idx=i, t=int(times[i]), price=float(highs[i]), kind="high"))
        if lows[i] == window_l.min() and (np.sort(window_l)[1] - lows[i]) >= min_displacement_atr * a:
            candidates.append(Swing(idx=i, t=int(times[i]), price=float(lows[i]), kind="low"))

    if not candidates:
        return []

    # Keep strictly alternating swings; when two of the same kind appear in a
    # row keep the more extreme one.
    filtered: list[Swing] = []
    for swing in candidates:
        if filtered and filtered[-1].kind == swing.kind:
            prev = filtered[-1]
            if (swing.kind == "high" and swing.price >= prev.price) or (
                swing.kind == "low" and swing.price <= prev.price
            ):
                filtered[-1] = swing
            continue
        filtered.append(swing)

    last_high: float | None = None
    last_low: float | None = None
    for swing in filtered:
        if swing.kind == "high":
            swing.label = "HH" if (last_high is not None and swing.price > last_high) else ("LH" if last_high is not None else "H")
            last_high = swing.price
        else:
            swing.label = "HL" if (last_low is not None and swing.price > last_low) else ("LL" if last_low is not None else "L")
            last_low = swing.price
        # The trailing swing cannot be confirmed until `lookback` bars pass.
        swing.confirmed = swing.idx <= n - lookback - 1
    return filtered


def to_swing_points(swings: list[Swing], limit: int = 12) -> list[SwingPoint]:
    return [
        SwingPoint(idx=s.idx, t=s.t, price=s.price, kind=s.kind, label=s.label, confirmed=s.confirmed)
        for s in swings[-limit:]
    ]


def detect_events(df, swings: list[Swing], max_events: int = 40) -> list[StructureEvent]:
    """Walk closed bars and record break-of-structure / change-of-character.

    A swing may only act as a reference once it is genuinely confirmed at the
    bar being evaluated, so no future information leaks into the events.
    """
    if len(swings) < 2:
        return []
    closes = df["c"].to_numpy(dtype=float)
    times = df["t"].to_numpy(dtype=int)
    n = len(closes)

    highs = [s for s in swings if s.kind == "high"]
    lows = [s for s in swings if s.kind == "low"]
    events: list[StructureEvent] = []
    trend = 0
    ref_high: Swing | None = None
    ref_low: Swing | None = None
    hi_ptr = lo_ptr = 0

    start = min(swings[0].idx, n - 1)
    for i in range(start, n):
        # Activate swings whose confirmation bar has been reached.
        while hi_ptr < len(highs) and highs[hi_ptr].idx + 2 <= i:
            ref_high = highs[hi_ptr]
            hi_ptr += 1
        while lo_ptr < len(lows) and lows[lo_ptr].idx + 2 <= i:
            ref_low = lows[lo_ptr]
            lo_ptr += 1

        close = closes[i]
        if ref_high is not None and close > ref_high.price:
            kind = "CHoCH" if trend <= 0 else "BOS"
            events.append(StructureEvent(
                kind=kind, direction=Direction.up, level=float(ref_high.price), t=int(times[i]),
                bars_ago=0, confirmed=True,
                note=("Bullish CHoCH: close above the last swing high flipped the trend" if trend < 0
                      else "Bullish BOS: continuation above the previous swing high"),
            ))
            trend = 1
            ref_high = None
        if ref_low is not None and close < ref_low.price:
            kind = "CHoCH" if trend >= 0 else "BOS"
            events.append(StructureEvent(
                kind=kind, direction=Direction.down, level=float(ref_low.price), t=int(times[i]),
                bars_ago=0, confirmed=True,
                note=("Bearish CHoCH: close below the last swing low flipped the trend" if trend > 0
                      else "Bearish BOS: continuation below the previous swing low"),
            ))
            trend = -1
            ref_low = None

    recent = events[-max_events:]
    for ev in recent:
        ev.bars_ago = max(0, n - 1 - int(np.searchsorted(times, ev.t, side="right")) + 1)
    return recent


def structure_bias(swings: list[Swing], events: list[StructureEvent]) -> tuple[Direction, float]:
    """Directional structure bias plus a 0..1 confidence."""
    if not swings:
        return Direction.sideways, 0.0
    labels = [s.label for s in swings[-6:]]
    score = 0.0
    score += 1.0 if labels.count("HH") and labels.count("HL") else 0.0
    score -= 1.0 if labels.count("LH") and labels.count("LL") else 0.0
    last = events[-1] if events else None
    if last is not None:
        recency = max(0.0, 1.0 - last.bars_ago / 60.0)
        if last.direction == Direction.up:
            score += 0.8 * recency + (0.3 if last.kind == "CHoCH" else 0.0)
        elif last.direction == Direction.down:
            score -= 0.8 * recency + (0.3 if last.kind == "CHoCH" else 0.0)
    if score > 0.4:
        return Direction.up, min(1.0, abs(score) / 1.6)
    if score < -0.4:
        return Direction.down, min(1.0, abs(score) / 1.6)
    return Direction.sideways, min(1.0, 1.0 - abs(score))


def swing_range(swings: list[Swing], lookback: int = 4) -> tuple[float, float]:
    recent = swings[-lookback:]
    if not recent:
        return 0.0, 0.0
    return float(min(s.price for s in recent)), float(max(s.price for s in recent))


def trend_from_swings(swings: list[Swing]) -> Direction:
    recent = swings[-4:]
    highs = [s.price for s in recent if s.kind == "high"]
    lows = [s.price for s in recent if s.kind == "low"]
    if len(highs) >= 2 and len(lows) >= 2:
        if highs[-1] > highs[0] and lows[-1] > lows[0]:
            return Direction.up
        if highs[-1] < highs[0] and lows[-1] < lows[0]:
            return Direction.down
    return Direction.sideways
