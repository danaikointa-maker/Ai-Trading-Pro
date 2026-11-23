"""Source-scoped contracts for TradingView AI Agent Lens evidence.

These models deliberately do not inherit from ``Signal`` or ``TradePlan``. Lens
packets are untrusted analytics and must never be mistaken for an executable
No7 decision or a broker quote.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)


class LensCandle(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float | None = Field(default=None, ge=0)
    direction: Literal["bull", "bear", "flat"]
    body_pct: float = Field(ge=0, le=100)
    upper_wick_pct: float = Field(ge=0, le=100)
    lower_wick_pct: float = Field(ge=0, le=100)
    range_atr: float | None = Field(default=None, ge=0)
    close_position_pct: float = Field(ge=0, le=100)
    gap_pct: float | None = Field(default=None, ge=-100, le=100)
    closed_above_prev_high: bool
    closed_below_prev_low: bool
    pattern: str = Field(max_length=64)

    @model_validator(mode="after")
    def validate_ohlc(self) -> "LensCandle":
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("candle high is inconsistent with OHLC")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("candle low is inconsistent with OHLC")
        if not all(math.isfinite(v) for v in (self.open, self.high, self.low, self.close)):
            raise ValueError("candle prices must be finite")
        return self


class LensScores(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    long: StrictInt = Field(ge=0, le=100)
    short: StrictInt = Field(ge=0, le=100)
    threshold: StrictInt = Field(ge=0, le=100)
    long_factors: dict[str, StrictInt] = Field(default_factory=dict)
    short_factors: dict[str, StrictInt] = Field(default_factory=dict)

    @field_validator("long_factors", "short_factors")
    @classmethod
    def validate_factors(cls, value: dict[str, StrictInt]) -> dict[str, StrictInt]:
        allowed = {"trend", "momentum", "strength", "volume", "htf"}
        if set(value) - allowed or any(not 0 <= score <= 20 for score in value.values()):
            raise ValueError("Lens score factors must be known and within 0..20")
        return value


class LensRecentCandle(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    bars_ago: int = Field(ge=0, le=10000)
    o: float = Field(gt=0)
    h: float = Field(gt=0)
    l: float = Field(gt=0)
    c: float = Field(gt=0)
    v: float | None = Field(default=None, ge=0)
    dir: Literal["bull", "bear", "flat"]
    body_pct: float = Field(ge=0, le=100)
    range_atr: float | None = Field(default=None, ge=0)
    pattern: str = Field(max_length=64)

    @model_validator(mode="after")
    def validate_ohlc(self) -> "LensRecentCandle":
        if self.h < max(self.o, self.c, self.l) or self.l > min(self.o, self.c, self.h):
            raise ValueError("recent candle OHLC is inconsistent")
        return self


class LensTrend(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    ema_fast: float | None = None
    ema_mid: float | None = None
    ema_slow: float | None = None
    stack: Literal["BULLISH", "BEARISH", "MIXED"]
    slow_slope: Literal["RISING", "FALLING", "FLAT"]
    htf: str = Field(max_length=12)
    htf_bias: Literal["UP", "DOWN", "FLAT", "N/A"]


class LensMomentum(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    rsi: float | None = Field(default=None, ge=0, le=100)
    macd_hist: float | None = None
    macd_hist_rising: bool | None = None


class LensStrength(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    adx: float | None = Field(default=None, ge=0, le=100)
    di_plus: float | None = Field(default=None, ge=0, le=100)
    di_minus: float | None = Field(default=None, ge=0, le=100)


class LensVolatility(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    atr: float | None = Field(default=None, ge=0)
    atr_percentile: float | None = Field(default=None, ge=0, le=100)


class LensVolume(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    relative: float | None = Field(default=None, ge=0)


class LensStructure(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    bias: Literal["BULLISH", "BEARISH", "MIXED"]
    event: Literal["BREAK_UP", "BREAK_DOWN", "NONE"]
    last_swing_high: float | None = Field(default=None, gt=0)
    last_swing_low: float | None = Field(default=None, gt=0)


class LensLevels(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    prev_day_high: float | None = Field(default=None, gt=0)
    prev_day_low: float | None = Field(default=None, gt=0)
    vwap: float | None = Field(default=None, gt=0)


class TradingViewLensPacket(BaseModel):
    """Validated subset of the documented ``ai-agent-lens/v1`` webhook packet."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, allow_inf_nan=False)

    schema_version: Literal["ai-agent-lens/v1"] = Field(alias="schema")
    event: Literal["BAR_CLOSE", "LONG_SETUP", "SHORT_SETUP", "TRADE_UPDATE"]
    symbol: str = Field(min_length=1, max_length=96)
    timeframe: str = Field(min_length=1, max_length=12)
    time: datetime
    state_code: str = Field(default="", max_length=256)
    candle: LensCandle
    recent_candles: list[LensRecentCandle] = Field(default_factory=list, max_length=30)
    regime: Literal["TREND_UP", "TREND_DOWN", "RANGE", "HIGH_VOLATILITY"]
    trend: LensTrend
    momentum: LensMomentum
    strength: LensStrength
    volatility: LensVolatility
    volume: LensVolume
    structure: LensStructure
    levels: LensLevels
    scores: LensScores
    trade: dict[str, Any] = Field(default_factory=dict)
    last_setup: dict[str, Any] = Field(default_factory=dict)

    @field_validator("time")
    @classmethod
    def require_utc_close(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None or value.utcoffset().total_seconds() != 0:
            raise ValueError("TradingView candle close time must include a UTC timezone")
        return value.astimezone(timezone.utc)

    @field_validator("symbol")
    @classmethod
    def trim_symbol(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(ch) < 32 for ch in value):
            raise ValueError("invalid TradingView symbol")
        return value

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, value: str) -> str:
        value = value.strip().upper()
        if not value.isalnum():
            raise ValueError("invalid TradingView timeframe")
        return value


class ExternalAnalysisEvidence(BaseModel):
    """Normalized, non-executable Lens evidence shared by API and dashboard."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    source: Literal["tradingview_ai_agent_lens"] = "tradingview_ai_agent_lens"
    source_schema: Literal["ai-agent-lens/v1"]
    event: Literal["BAR_CLOSE", "LONG_SETUP", "SHORT_SETUP", "TRADE_UPDATE"]
    source_symbol: str
    mapped_symbol: str
    timeframe: str
    bar_close_utc: int
    received_at_utc: int
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    regime: str
    candle: LensCandle
    long_score: int = Field(ge=0, le=100)
    short_score: int = Field(ge=0, le=100)
    score_threshold: int = Field(ge=0, le=100)
    features: dict[str, Any] = Field(default_factory=dict)
    quality: Literal["unverified", "accepted_shadow", "rejected"] = "unverified"
    executable: Literal[False] = False
