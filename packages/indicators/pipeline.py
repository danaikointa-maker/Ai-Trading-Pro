"""Indicator enrichment used by the analysis and ML feature layers."""
from __future__ import annotations

import numpy as np
import pandas as pd

from packages.indicators import core as ta


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) == 0:
        return df
    out = df.copy()
    c, h, l = out["c"].to_numpy(float), out["h"].to_numpy(float), out["l"].to_numpy(float)
    out["atr"] = ta.atr(h, l, c, 14)
    out["ema20"] = ta.ema(c, 20)
    out["ema50"] = ta.ema(c, 50)
    out["ema200"] = ta.ema(c, 200)
    out["rsi14"] = ta.rsi(c, 14)
    out["adx14"] = ta.adx(h, l, c, 14)
    macd_line, macd_sig, macd_hist = ta.macd(c)
    out["macd"] = macd_line
    out["macd_signal"] = macd_sig
    out["macd_hist"] = macd_hist
    out["vwap"] = ta.vwap_session(h, l, c, out["v"], out["t"])
    upper, mid, lower, width = ta.bollinger(c, 20, 2.0)
    out["bb_upper"] = upper
    out["bb_lower"] = lower
    out["bb_width"] = width
    out["logret"] = np.log(pd.Series(c)).diff()
    out["vol_z"] = ta.zscore(out["v"].to_numpy(float), 50)
    out["atr_pct"] = ta.percentile_rank(out["atr"].to_numpy(float), 200)
    return out


def strip_nan(value: float | None, fallback: float = 0.0) -> float:
    if value is None:
        return fallback
    try:
        f = float(value)
    except (TypeError, ValueError):
        return fallback
    return f if np.isfinite(f) else fallback
