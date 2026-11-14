"""Builds the market analysis snapshot the AI and the dashboard consume."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from packages.indicators import core as ta
from packages.indicators.pipeline import strip_nan
from packages.market_structure.structure import (
    Swing,
    detect_events,
    find_swings,
    structure_bias,
    to_swing_points,
)
from packages.shared_schemas.models import (
    AnalysisSnapshot,
    Direction,
    IndicatorSnapshot,
    StructureEvent,
    TrendReading,
)
from packages.shared_schemas.settings import Settings
from packages.strategy_rules import regime as regime_mod
from packages.strategy_rules.flip_readings import confirmed_flip_readings
from packages.strategy_rules.retracement import confirmed_fibonacci_band
from packages.strategy_rules.trend import alignment_score, read_trend
from packages.strategy_rules.zones import ZoneEngineConfig, build_zones
from services.market_data.service import MarketDataService
from services.market_data.news import NewsService


def _round_step(price: float) -> float:
    """A human "round number" grid appropriate to the instrument's scale."""
    if price >= 1000:
        return 10.0
    if price >= 100:
        return 1.0
    if price >= 10:
        return 0.5
    if price >= 1:
        return 0.05
    return 0.005


@dataclass
class AnalysisContext:
    snapshot: AnalysisSnapshot
    frames: dict[str, pd.DataFrame]
    swings: list[Swing]
    events: list[StructureEvent]
    bias: Direction = Direction.sideways
    bias_confidence: float = 0.0
    alignment: float = 0.0
    alignment_notes: list[str] = field(default_factory=list)


class AnalysisService:
    def __init__(self, settings: Settings, market: MarketDataService, news: NewsService) -> None:
        self.settings = settings
        self.market = market
        self.news = news
        cfg = settings.strategy_cfg().get("zone_engine", {})
        families = cfg.get("families", {})
        self.zone_cfg = ZoneEngineConfig.from_dict(cfg, families)
        self.regime_cfg = settings.strategy_cfg().get("regime_detector", {})
        self.base_timeframe = "M5"

    def snapshot(self, symbol: str, broker_id: str | None = None) -> AnalysisContext:
        adapter_id = self.market.registry.get(broker_id).id
        spec = self.market.spec(symbol, broker_id)
        # The last row of every live series is still forming. Structure, zones and
        # indicators must be built from *closed* candles only, otherwise a zone
        # can flip between "confirmed" and "candidate" inside the same bar.
        def closed(df: pd.DataFrame) -> pd.DataFrame:
            return df.iloc[:-1].reset_index(drop=True) if len(df) > 2 else df

        frames: dict[str, pd.DataFrame] = {
            "M1": closed(self.market.candles(symbol, "M1", 600, broker_id)),
            "M5": closed(self.market.candles(symbol, "M5", 900, broker_id)),
            "M15": closed(self.market.candles(symbol, "M15", 600, broker_id)),
            "H1": closed(self.market.candles(symbol, "H1", 500, broker_id)),
            "H4": closed(self.market.candles(symbol, "H4", 300, broker_id)),
        }
        tick = self.market.ticker(symbol, broker_id)
        price = float(tick.last or tick.bid)
        quality = self.market.data_quality(symbol, "M1", broker_id)
        daily = self.market.registry.get(broker_id).candles(symbol, "D1", 10)
        news_lock = self.news.lockout(
            self.market.now(),
            before_minutes=self.settings.risk_cfg()["limits"]["news_window_before_minutes"],
            after_minutes=self.settings.risk_cfg()["limits"]["news_window_after_minutes"])
        return self.assemble(symbol, spec, frames, price, quality, news_lock, adapter_id, daily)

    def assemble(self, symbol: str, spec, frames: dict[str, pd.DataFrame], price: float,
                 quality: dict[str, Any], news_lock: dict[str, Any], broker_id: str = "",
                 daily: pd.DataFrame | None = None) -> AnalysisContext:
        """Pure assembly used by both the live service and the backtester."""
        trends: list[TrendReading] = [
            read_trend(frames[tf], tf, spec.point) for tf in ("M1", "M5", "M15", "H1", "H4")
        ]
        base = frames[self.base_timeframe]
        swings = find_swings(base)
        events = detect_events(base, swings)
        # Visual evidence only. The strategy/risk/order gates do not consume this.
        sr_flips = confirmed_flip_readings(base, swings, spec.point)
        fibonacci_band = confirmed_fibonacci_band(base, swings, spec.digits)
        bias, bias_conf = structure_bias(swings, events)
        htf_bias = next((t for t in trends if t.timeframe == "H1"), trends[-1])
        align, align_notes = alignment_score(trends, bias if bias != Direction.sideways else htf_bias.direction)

        pivots: dict[str, float] = {}
        if daily is not None and len(daily) >= 2:
            prev = daily.iloc[-2]
            pivots = {k: round(v, spec.digits) for k, v in ta.pivot_points(
                float(prev["h"]), float(prev["l"]), float(prev["c"])).items()}

        atr_value = float(base["atr"].iloc[-1]) if np.isfinite(base["atr"].iloc[-1]) else price * 0.001
        vwap = strip_nan(base["vwap"].iloc[-1], price)
        ema50 = strip_nan(base["ema50"].iloc[-1], price)
        ema200 = strip_nan(base["ema200"].iloc[-1], price)
        vp = ta.volume_profile(base["h"].tail(240), base["l"].tail(240), base["c"].tail(240),
                               base["v"].tail(240), bins=50)

        zones, supports, resistances = build_zones(
            base, spec, price, swings, atr_value, pivots, vwap, ema50, ema200, vp, self.zone_cfg,
            round_step=_round_step(price),
        )

        shock = bool(news_lock.get("active"))
        regime = regime_mod.detect_regime(frames["M15"], self.regime_cfg, spec.point, news_shock=shock)

        last = base.iloc[-1]
        indicators = IndicatorSnapshot(
            ema20=round(strip_nan(last["ema20"]), spec.digits),
            ema50=round(ema50, spec.digits),
            ema200=round(ema200, spec.digits),
            rsi14=round(strip_nan(last["rsi14"], 50.0), 2),
            atr14=round(atr_value, spec.digits),
            atr_points=round(atr_value / spec.point, 1),
            adx14=round(strip_nan(last["adx14"]), 2),
            macd=round(strip_nan(last["macd"]), 3),
            macd_signal=round(strip_nan(last["macd_signal"]), 3),
            macd_hist=round(strip_nan(last["macd_hist"]), 3),
            vwap=round(vwap, spec.digits),
            poc=round(float(vp.get("poc", price)), spec.digits),
            vah=round(float(vp.get("vah", price)), spec.digits),
            val=round(float(vp.get("val", price)), spec.digits),
            volume_z=round(strip_nan(last.get("vol_z")), 2),
            bb_width_pct=round(strip_nan(last.get("bb_width")) * 100, 3),
        )

        day_start = int(base["t"].iloc[-1] // 86400) * 86400
        today = base[base["t"] >= day_start]
        session_high = float(today["h"].max()) if len(today) else float(base["h"].tail(60).max())
        session_low = float(today["l"].min()) if len(today) else float(base["l"].tail(60).min())

        snapshot = AnalysisSnapshot(
            symbol=symbol, timeframe=self.base_timeframe, broker_id=broker_id,
            price=round(price, spec.digits), server_time=int(base["t"].iloc[-1]), spec=spec,
            trend=trends, structure=events[-12:], swings=to_swing_points(swings),
            sr_flips=sr_flips, fibonacci_band=fibonacci_band, zones=zones,
            supports=supports, resistances=resistances, regime=regime, indicators=indicators,
            pivots=pivots, session_high=round(session_high, spec.digits),
            session_low=round(session_low, spec.digits), news_lockout=news_lock,
            data_quality=quality,
        )
        return AnalysisContext(
            snapshot=snapshot, frames=frames, swings=swings, events=events, bias=bias,
            bias_confidence=bias_conf, alignment=align, alignment_notes=align_notes,
        )

    # ------------------------------------------------------------- helpers
    def multi_tf_trend(self, symbol: str, broker_id: str | None = None) -> list[TrendReading]:
        ctx = self.snapshot(symbol, broker_id)
        return ctx.snapshot.trend

    def summary(self, symbol: str, broker_id: str | None = None) -> dict[str, Any]:
        ctx = self.snapshot(symbol, broker_id)
        snap = ctx.snapshot
        return {
            "symbol": symbol,
            "price": snap.price,
            "trend": [t.model_dump() for t in snap.trend],
            "structure_bias": ctx.bias.value,
            "alignment": round(ctx.alignment, 3),
            "regime": snap.regime.model_dump() if snap.regime else None,
            "supports": [z.model_dump() for z in snap.supports],
            "resistances": [z.model_dump() for z in snap.resistances],
            "news_lockout": snap.news_lockout,
            "data_quality": snap.data_quality,
        }
