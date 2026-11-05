"""Price-action pattern detectors used as independent zone evidence.

These are deliberately literal definitions (no adaptive fudge factors) so the
confluence engine can claim "independent evidence" honestly.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from packages.market_structure.structure import Swing


@dataclass
class Level:
    """A price band with the detector that produced it."""
    low: float
    high: float
    family: str
    label: str
    idx: int
    t: int
    direction: str = "neutral"     # "support" | "resistance" | "neutral"
    mitigated: bool = False
    meta: dict = field(default_factory=dict)

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2.0


def find_fair_value_gaps(df, atr: np.ndarray, min_gap_atr: float = 0.15, lookback: int = 300) -> list[Level]:
    """3-candle imbalance (FVG) that has not been fully filled yet."""
    highs = df["h"].to_numpy(float)
    lows = df["l"].to_numpy(float)
    times = df["t"].to_numpy(int)
    closes = df["c"].to_numpy(float)
    out: list[Level] = []
    start = max(2, len(df) - lookback)
    for i in range(start, len(df)):
        a = atr[i] if np.isfinite(atr[i]) else 0.0
        if a <= 0:
            continue
        # Bullish imbalance: gap between high[i-2] and low[i]
        if lows[i] > highs[i - 2] + min_gap_atr * a:
            top, bottom = float(lows[i]), float(highs[i - 2])
            filled = bool(np.any(closes[i + 1:] < bottom)) if i + 1 < len(df) else False
            out.append(Level(bottom, top, "fair_value_gap", "Bullish FVG", i, int(times[i]), "support", filled,
                             {"gap_atr": round((top - bottom) / a, 2)}))
        # Bearish imbalance
        if highs[i] < lows[i - 2] - min_gap_atr * a:
            top, bottom = float(lows[i - 2]), float(highs[i])
            filled = bool(np.any(closes[i + 1:] > top)) if i + 1 < len(df) else False
            out.append(Level(bottom, top, "fair_value_gap", "Bearish FVG", i, int(times[i]), "resistance", filled,
                             {"gap_atr": round((top - bottom) / a, 2)}))
    return [lv for lv in out if not lv.mitigated][-8:]


def find_order_blocks(df, atr: np.ndarray, impulse_atr: float = 1.1, lookback: int = 300) -> list[Level]:
    """Last opposing candle before a displacement leg (order block / supply-demand)."""
    o = df["o"].to_numpy(float)
    h = df["h"].to_numpy(float)
    l = df["l"].to_numpy(float)
    c = df["c"].to_numpy(float)
    times = df["t"].to_numpy(int)
    out: list[Level] = []
    start = max(3, len(df) - lookback)
    for i in range(start, len(df) - 1):
        a = atr[i] if np.isfinite(atr[i]) else 0.0
        if a <= 0:
            continue
        body = abs(c[i] - o[i])
        # Bullish displacement candle -> look back for the last bearish candle.
        if c[i] > o[i] and body > impulse_atr * a:
            j = i - 1
            while j >= max(0, i - 5) and c[j] >= o[j]:
                j -= 1
            if j >= max(0, i - 5):
                top, bottom = float(max(o[j], c[j])), float(min(l[j], h[j]))
                mitigated = bool(np.any(l[i + 1:] < bottom)) if i + 1 < len(df) else False
                out.append(Level(bottom, top, "order_block", "Bullish order block", j, int(times[j]),
                                 "support", mitigated))
        if c[i] < o[i] and body > impulse_atr * a:
            j = i - 1
            while j >= max(0, i - 5) and c[j] <= o[j]:
                j -= 1
            if j >= max(0, i - 5):
                top, bottom = float(max(h[j], o[j])), float(min(o[j], c[j]))
                mitigated = bool(np.any(h[i + 1:] > top)) if i + 1 < len(df) else False
                out.append(Level(bottom, top, "order_block", "Bearish order block", j, int(times[j]),
                                 "resistance", mitigated))
    return [lv for lv in out if not lv.mitigated][-8:]


def find_equal_levels(swings: list[Swing], atr_value: float, tolerance_atr: float = 0.3) -> list[Level]:
    """Equal highs / equal lows = resting liquidity (stop clusters)."""
    out: list[Level] = []
    tol = max(atr_value * tolerance_atr, 1e-9)
    for kind, direction in (("high", "resistance"), ("low", "support")):
        pool = [s for s in swings if s.kind == kind]
        for a, b in zip(pool, pool[1:]):
            if abs(a.price - b.price) <= tol:
                out.append(Level(
                    min(a.price, b.price), max(a.price, b.price), "liquidity_equal_levels",
                    f"Equal {'highs' if kind == 'high' else 'lows'}", b.idx, b.t, direction, False,
                    {"count": 2, "spread_atr": round(abs(a.price - b.price) / max(atr_value, 1e-9), 2)},
                ))
    return out[-6:]


def reaction_count(df, low: float, high: float, atr_value: float, lookback: int = 400) -> int:
    """How many times price tested this band and closed back outside of it."""
    h = df["h"].to_numpy(float)[-lookback:]
    l = df["l"].to_numpy(float)[-lookback:]
    c = df["c"].to_numpy(float)[-lookback:]
    band = max(high - low, atr_value * 0.1)
    touches = 0
    armed = True
    for i in range(len(h)):
        tested = h[i] >= low - band * 0.25 and l[i] <= high + band * 0.25
        if tested and armed:
            touches += 1
            armed = False
        elif not tested:
            armed = True
    del c
    return touches


def swing_origin_levels(swings: list[Swing], atr_value: float, pad_atr: float = 0.08) -> list[Level]:
    """Raw swing highs/lows as zones with an ATR-based thickness."""
    pad = max(atr_value * pad_atr, 1e-9)
    out: list[Level] = []
    for s in swings[-10:]:
        if s.kind == "high":
            out.append(Level(s.price - pad, s.price + pad, "structure_swing", s.label or "Swing high",
                             s.idx, s.t, "resistance"))
        else:
            out.append(Level(s.price - pad, s.price + pad, "structure_swing", s.label or "Swing low",
                             s.idx, s.t, "support"))
    return out
