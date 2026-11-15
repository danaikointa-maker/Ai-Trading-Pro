"""Vectorised technical indicators (numpy only, no TA-Lib dependency).

Every function returns arrays aligned with the input length, NaN-padded where
the indicator is not yet defined. All calculations use closed candles only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "sma", "ema", "rsi", "atr", "adx", "macd", "stochastic", "bollinger", "vwap_session",
    "volume_profile", "pivot_points", "stdev", "percentile_rank", "zscore",
    "crossover", "slope",
]


def _series(values) -> np.ndarray:
    return np.asarray(values, dtype="float64")


def sma(values, period: int) -> np.ndarray:
    s = pd.Series(_series(values))
    return s.rolling(period, min_periods=period).mean().to_numpy()


def ema(values, period: int) -> np.ndarray:
    s = pd.Series(_series(values))
    return s.ewm(span=period, adjust=False, min_periods=period).mean().to_numpy()


def stdev(values, period: int) -> np.ndarray:
    s = pd.Series(_series(values))
    return s.rolling(period, min_periods=period).std(ddof=0).to_numpy()


def rsi(close, period: int = 14) -> np.ndarray:
    s = pd.Series(_series(close))
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100 - (100 / (1 + rs))
    # No losses at all -> 100; perfectly flat (no gains either) -> neutral 50.
    out = out.where(avg_loss != 0, 100.0)
    out = out.where(~((avg_loss == 0) & (avg_gain == 0)), 50.0)
    return out.to_numpy()


def stochastic(high, low, close, period: int = 14,
               smooth_k: int = 3, smooth_d: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Stochastic K/D (14,3,3); no centered windows or future candle access.

    The flat-price 0/0 case is neutral (50) rather than falsely overbought.
    Incomplete warmup bars remain NaN so callers cannot treat them as signals.
    """
    h, l, c = _series(high), _series(low), _series(close)
    if not (len(h) == len(l) == len(c)):
        raise ValueError("high, low, close lengths must match")
    if min(period, smooth_k, smooth_d) < 1:
        raise ValueError("stochastic periods must be positive")
    high_max = pd.Series(h).rolling(period, min_periods=period).max()
    low_min = pd.Series(l).rolling(period, min_periods=period).min()
    span = high_max - low_min
    raw_k = 100.0 * (pd.Series(c) - low_min) / span.replace(0, np.nan)
    raw_k = raw_k.where(span != 0, 50.0).clip(0, 100)
    k = raw_k.rolling(smooth_k, min_periods=smooth_k).mean()
    d = k.rolling(smooth_d, min_periods=smooth_d).mean()
    return k.to_numpy(), d.to_numpy()


def true_range(high, low, close) -> np.ndarray:
    h, l, c = _series(high), _series(low), _series(close)
    prev_close = np.concatenate(([np.nan], c[:-1]))
    tr = np.maximum.reduce([h - l, np.abs(h - prev_close), np.abs(l - prev_close)])
    tr[0] = h[0] - l[0]
    return tr


def atr(high, low, close, period: int = 14) -> np.ndarray:
    tr = pd.Series(true_range(high, low, close))
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean().to_numpy()


def adx(high, low, close, period: int = 14) -> np.ndarray:
    h, l, c = _series(high), _series(low), _series(close)
    up = np.zeros_like(h)
    down = np.zeros_like(h)
    up[1:] = h[1:] - h[:-1]
    down[1:] = l[:-1] - l[1:]
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = pd.Series(true_range(h, l, c))
    atr_s = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_s = pd.Series(plus_dm).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    minus_s = pd.Series(minus_dm).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * plus_s / atr_s.replace(0.0, np.nan)
    minus_di = 100 * minus_s / atr_s.replace(0.0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean().to_numpy()


def macd(close, fast: int = 12, slow: int = 26, signal: int = 9):
    s = pd.Series(_series(close))
    line = s.ewm(span=fast, adjust=False).mean() - s.ewm(span=slow, adjust=False).mean()
    sig = line.ewm(span=signal, adjust=False).mean()
    hist = line - sig
    return line.to_numpy(), sig.to_numpy(), hist.to_numpy()


def bollinger(close, period: int = 20, mult: float = 2.0):
    s = pd.Series(_series(close))
    mid = s.rolling(period, min_periods=period).mean()
    sd = s.rolling(period, min_periods=period).std(ddof=0)
    upper = mid + mult * sd
    lower = mid - mult * sd
    width = (upper - lower) / mid.replace(0.0, np.nan)
    return upper.to_numpy(), mid.to_numpy(), lower.to_numpy(), width.to_numpy()


def vwap_session(high, low, close, volume, times) -> np.ndarray:
    """Session VWAP anchored on UTC day boundaries."""
    df = pd.DataFrame({
        "h": _series(high), "l": _series(low), "c": _series(close),
        "v": _series(volume), "t": pd.to_datetime(pd.Series(times), unit="s", utc=True),
    })
    typical = (df.h + df.l + df.c) / 3.0
    day = df.t.dt.floor("D")
    pv = typical * df.v
    cum_pv = pv.groupby(day).cumsum()
    cum_v = df.v.groupby(day).cumsum().replace(0.0, np.nan)
    return (cum_pv / cum_v).to_numpy()


def volume_profile(high, low, close, volume, bins: int = 60) -> dict[str, float]:
    """Volume profile over the supplied window: POC, VAH and VAL (70% value area).

    Prices are weighted by the bar's typical price spread across the bar range,
    which keeps the histogram stable without requiring tick data.
    """
    h, l, c, v = _series(high), _series(low), _series(close), _series(volume)
    if len(h) == 0:
        return {"poc": 0.0, "vah": 0.0, "val": 0.0, "hist": np.array([]), "edges": np.array([])}
    lo, hi = float(np.nanmin(l)), float(np.nanmax(h))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return {"poc": float(c[-1]), "vah": float(c[-1]), "val": float(c[-1]), "hist": np.array([]), "edges": np.array([])}
    edges = np.linspace(lo, hi, bins + 1)
    hist = np.zeros(bins)
    for i in range(len(h)):
        if not np.isfinite(l[i]) or not np.isfinite(h[i]):
            continue
        a = np.searchsorted(edges, l[i], side="right") - 1
        b = np.searchsorted(edges, h[i], side="right") - 1
        a = max(0, min(bins - 1, a))
        b = max(0, min(bins - 1, b))
        span = max(1, b - a + 1)
        hist[a:b + 1] += v[i] / span
    poc_idx = int(np.argmax(hist))
    total = hist.sum()
    target = total * 0.70
    acc = hist[poc_idx]
    low_i = high_i = poc_idx
    while acc < target and (low_i > 0 or high_i < bins - 1):
        below = hist[low_i - 1] if low_i > 0 else -1
        above = hist[high_i + 1] if high_i < bins - 1 else -1
        if above >= below:
            high_i += 1
            acc += max(above, 0.0)
        else:
            low_i -= 1
            acc += max(below, 0.0)
    return {
        "poc": float((edges[poc_idx] + edges[poc_idx + 1]) / 2),
        "vah": float(edges[high_i + 1]),
        "val": float(edges[low_i]),
        "hist": hist,
        "edges": edges,
    }


def pivot_points(high: float, low: float, close: float) -> dict[str, float]:
    p = (high + low + close) / 3.0
    rng = high - low
    return {
        "P": p,
        "R1": 2 * p - low,
        "S1": 2 * p - high,
        "R2": p + rng,
        "S2": p - rng,
        "R3": high + 2 * (p - low),
        "S3": low - 2 * (high - p),
    }


def percentile_rank(values, window: int = 200) -> np.ndarray:
    """Rolling percentile rank of the latest value inside the trailing window."""
    s = pd.Series(_series(values))
    return s.rolling(window, min_periods=max(10, window // 4)).apply(
        lambda w: (w <= w[-1]).mean(), raw=True
    ).to_numpy()


def zscore(values, window: int = 50) -> np.ndarray:
    s = pd.Series(_series(values))
    mean = s.rolling(window, min_periods=5).mean()
    sd = s.rolling(window, min_periods=5).std(ddof=0).replace(0.0, np.nan)
    return ((s - mean) / sd).to_numpy()


def slope(values, window: int = 20) -> np.ndarray:
    """Rolling linear-regression slope, normalised by price level."""
    s = pd.Series(_series(values))
    x = np.arange(window, dtype="float64")
    x_centered = x - x.mean()
    denom = float((x_centered ** 2).sum())

    def _slope(win: np.ndarray) -> float:
        y = win - win.mean()
        return float((x_centered * y).sum() / denom)

    return s.rolling(window, min_periods=window).apply(_slope, raw=True).to_numpy()


def crossover(a, b) -> np.ndarray:
    aa, bb = _series(a), _series(b)
    out = np.zeros(len(aa), dtype=bool)
    out[1:] = (aa[1:] > bb[1:]) & (aa[:-1] <= bb[:-1])
    return out
