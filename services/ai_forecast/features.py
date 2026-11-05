"""Feature pipeline shared by training and inference.

Rules that keep the model honest:
* every feature at row *i* only uses data available at the close of row *i*;
* forward-looking targets are built separately (``build_targets``) and never
  appear in the feature frame;
* the exact same function builds training rows and the live vector.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from packages.indicators.pipeline import enrich

FEATURE_COLUMNS = [
    "r1", "r3", "r6", "r12", "r24",
    "atr_pct", "atr_pctile", "atr_change",
    "rsi", "adx", "macd_hist", "ema_fast_gap", "ema_slow_gap",
    "bb_width", "vol_z", "vol_ratio",
    "range_atr", "body_atr", "close_pos",
    "dist_hi12", "dist_lo12", "dist_hi48", "dist_lo48",
    "hh_flag", "ll_flag", "vwap_dist",
    "hour_sin", "hour_cos", "dow",
]


def _safe_div(a, b):
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(np.abs(b) > 1e-12, a / b, np.nan)
    return out


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    if "atr" not in df.columns:
        df = enrich(df)
    out = pd.DataFrame(index=df.index)
    close = df["c"].to_numpy(float)
    atr = df["atr"].to_numpy(float)
    logc = np.log(close)

    for lag in (1, 3, 6, 12, 24):
        ret = pd.Series(logc).diff(lag).to_numpy()
        out[f"r{lag}"] = ret / (atr / close) * 0.05  # scale: 1 ATR ~ meaningful move

    out["atr_pct"] = atr / close * 100
    out["atr_pctile"] = df["atr_pct"].to_numpy() if "atr_pct" in df else np.nan
    out["atr_change"] = _safe_div(atr, pd.Series(atr).rolling(20).mean().to_numpy()) - 1.0
    out["rsi"] = df["rsi14"].to_numpy() / 100.0
    out["adx"] = df["adx14"].to_numpy() / 100.0
    out["macd_hist"] = _safe_div(df["macd_hist"].to_numpy(), atr)
    out["ema_fast_gap"] = _safe_div(df["ema20"].to_numpy() - df["ema50"].to_numpy(), atr)
    out["ema_slow_gap"] = _safe_div(close - df["ema200"].to_numpy(), atr)
    out["bb_width"] = df["bb_width"].to_numpy() * 100
    out["vol_z"] = df["vol_z"].to_numpy()
    out["vol_ratio"] = _safe_div(df["v"].to_numpy(), pd.Series(df["v"].to_numpy()).rolling(20).mean().to_numpy())

    rng = (df["h"] - df["l"]).to_numpy(float)
    body = (df["c"] - df["o"]).to_numpy(float)
    out["range_atr"] = _safe_div(rng, atr)
    out["body_atr"] = _safe_div(body, atr)
    out["close_pos"] = _safe_div(df["c"].to_numpy() - df["l"].to_numpy(), rng)

    highs = pd.Series(df["h"].to_numpy(float))
    lows = pd.Series(df["l"].to_numpy(float))
    closes = pd.Series(close)
    out["dist_hi12"] = _safe_div(highs.rolling(12).max().to_numpy() - close, atr)
    out["dist_lo12"] = _safe_div(close - lows.rolling(12).min().to_numpy(), atr)
    out["dist_hi48"] = _safe_div(highs.rolling(48).max().to_numpy() - close, atr)
    out["dist_lo48"] = _safe_div(close - lows.rolling(48).min().to_numpy(), atr)
    out["hh_flag"] = (close > closes.rolling(12).max().shift(1).to_numpy()).astype(float)
    out["ll_flag"] = (close < closes.rolling(12).min().shift(1).to_numpy()).astype(float)
    out["vwap_dist"] = _safe_div(close - df["vwap"].to_numpy(), atr)

    times = pd.to_datetime(pd.Series(df["t"].to_numpy()), unit="s", utc=True)
    hour = times.dt.hour.to_numpy()
    out["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
    out["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)
    out["dow"] = times.dt.dayofweek.to_numpy() / 6.0

    out = out[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan)
    out["t"] = df["t"].to_numpy(int)
    out["close"] = close
    out["atr"] = atr
    return out


def build_targets(df: pd.DataFrame, df_features: pd.DataFrame, horizon_bars: int,
                  deadband_atr: float = 0.25) -> pd.DataFrame:
    """Forward return in ATR units + 3-class label (up / sideways / down)."""
    close = df["c"].to_numpy(float)
    atr = df_features["atr"].to_numpy(float)
    n = len(df)
    fwd = np.full(n, np.nan)
    if n > horizon_bars:
        fwd[:-horizon_bars] = close[horizon_bars:] - close[:-horizon_bars]
    fwd_atr = _safe_div(fwd, atr)
    band = deadband_atr
    label = np.where(fwd_atr > band, 1, np.where(fwd_atr < -band, -1, 0)).astype(float)
    label[~np.isfinite(fwd_atr)] = np.nan
    return pd.DataFrame({
        "t": df_features["t"].to_numpy(),
        "fwd_points": fwd,
        "fwd_atr": fwd_atr,
        "label": label,
        "atr": atr,
        "close": close,
    })


def inference_vector(df: pd.DataFrame) -> tuple[np.ndarray, pd.DataFrame]:
    feats = build_features(df)
    last = feats.iloc[[-1]]
    if last[FEATURE_COLUMNS].isna().any(axis=1).iloc[0]:
        # Impute any missing indicator with the cross-sectional median of the frame.
        filled = last[FEATURE_COLUMNS].fillna(feats[FEATURE_COLUMNS].median(numeric_only=True))
        return filled.to_numpy(dtype=float)[0], feats
    return last[FEATURE_COLUMNS].to_numpy(dtype=float)[0], feats
