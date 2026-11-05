"""Market regime detection — chooses which strategy family is allowed to work."""
from __future__ import annotations

import numpy as np

from packages.indicators import core as ta
from packages.shared_schemas.models import Direction, Regime, RegimeReading


def detect_regime(df, cfg: dict, spec_point: float = 0.01, news_shock: bool = False) -> RegimeReading:
    if len(df) < 210:
        return RegimeReading(regime=Regime.sideways, confidence=0.2, adx=0.0, atr_points=0.0,
                             atr_percentile=0.5, note="not enough history", strategy="range_reversion")

    close = df["c"].to_numpy(float)
    adx = ta.adx(df["h"], df["l"], close, 14)
    atr = ta.atr(df["h"], df["l"], close, 14)
    atr_pct = ta.percentile_rank(atr, 200)
    ema50 = ta.ema(close, 50)
    ema200 = ta.ema(close, 200)
    slope = ta.slope(ema50, 20)

    i = len(close) - 1
    a = float(adx[i]) if np.isfinite(adx[i]) else 0.0
    atr_now = float(atr[i]) if np.isfinite(atr[i]) else 0.0
    ap = float(atr_pct[i]) if np.isfinite(atr_pct[i]) else 0.5
    sl = float(slope[i]) if np.isfinite(slope[i]) else 0.0
    above = np.isfinite(ema200[i]) and close[i] > ema200[i]
    atr_pct_price = (atr_now / close[i] * 100) if close[i] else 0.0

    adx_trend = float(cfg.get("adx_trending", 23))
    adx_side = float(cfg.get("adx_sideways", 18))
    high_atr = float(cfg.get("atr_percentile_high", 0.8))
    shock_z = float(cfg.get("news_shock_atr_z", 2.5))

    latest_range = float(df["h"].iloc[-1] - df["l"].iloc[-1])
    shock = news_shock or (atr_now > 0 and latest_range > shock_z * atr_now and ap > 0.9)

    if shock:
        return RegimeReading(regime=Regime.news_shock, confidence=0.85, adx=round(a, 1),
                             atr_points=round(atr_now / spec_point, 1), atr_percentile=round(ap, 3),
                             note=f"bar range {latest_range:.2f} is {latest_range / atr_now:.1f}x ATR — stand aside",
                             strategy="none")
    if ap >= high_atr and a < adx_trend:
        return RegimeReading(regime=Regime.high_volatility, confidence=round(min(0.95, 0.4 + ap * 0.6), 2),
                             adx=round(a, 1), atr_points=round(atr_now / spec_point, 1),
                             atr_percentile=round(ap, 3),
                             note=f"ATR in {ap * 100:.0f}th percentile, ADX {a:.0f} — size down, widen stops",
                             strategy="breakout_continuation")
    if a >= adx_trend:
        direction_up = above and sl > 0
        regime = Regime.trending_up if direction_up else Regime.trending_down
        return RegimeReading(regime=regime, confidence=round(min(0.95, 0.45 + a / 100), 2), adx=round(a, 1),
                             atr_points=round(atr_now / spec_point, 1), atr_percentile=round(ap, 3),
                             note=f"ADX {a:.0f} with {'rising' if direction_up else 'falling'} structure",
                             strategy="trend_pullback")
    if a <= adx_side:
        return RegimeReading(regime=Regime.sideways, confidence=round(min(0.9, 0.5 + (adx_side - a) / 40), 2),
                             adx=round(a, 1), atr_points=round(atr_now / spec_point, 1),
                             atr_percentile=round(ap, 3),
                             note=f"ADX {a:.0f} below {adx_side:.0f} — fade range edges only",
                             strategy="range_reversion")
    direction_up = above and sl > 0
    return RegimeReading(regime=Regime.trending_up if direction_up else Regime.trending_down,
                         confidence=0.4, adx=round(a, 1), atr_points=round(atr_now / spec_point, 1),
                         atr_percentile=round(ap, 3),
                         note=f"weak trend (ADX {a:.0f}, ATR {atr_pct_price:.2f}% of price)",
                         strategy="trend_pullback")


def regime_allows(regime: RegimeReading, strategy_id: str, strategies_cfg: list[dict]) -> bool:
    for strat in strategies_cfg:
        if strat.get("id") == strategy_id:
            if not strat.get("enabled", False):
                return False
            return regime.regime.value in (strat.get("regimes") or [])
    return False


def bias_with_regime(regime: RegimeReading) -> Direction:
    if regime.regime in (Regime.trending_up,):
        return Direction.up
    if regime.regime in (Regime.trending_down,):
        return Direction.down
    if regime.regime == Regime.sideways:
        return Direction.sideways
    return Direction.sideways
