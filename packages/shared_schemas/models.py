"""Shared domain schemas — the contract between the AI core and the dashboard."""
from __future__ import annotations

import math

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- enums
class Health(str, Enum):
    connected = "connected"
    degraded = "degraded"
    disconnected = "disconnected"
    stale = "stale"


class Direction(str, Enum):
    up = "up"
    down = "down"
    sideways = "sideways"


class SignalAction(str, Enum):
    buy = "BUY"
    sell = "SELL"
    wait = "WAIT"
    no_trade = "NO_TRADE"


class SignalStatus(str, Enum):
    strong = "strong"
    valid = "valid"
    weak = "weak"
    no_trade = "no_trade"


class TradeMode(str, Enum):
    manual = "manual"
    semi_auto = "semi_auto"
    full_auto = "full_auto"


class ZoneKind(str, Enum):
    support = "support"
    resistance = "resistance"


class ZoneQuality(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class ZoneStatus(str, Enum):
    confirmed = "confirmed"
    candidate = "candidate"


class Regime(str, Enum):
    trending_up = "trending_up"
    trending_down = "trending_down"
    sideways = "sideways"
    high_volatility = "high_volatility"
    news_shock = "news_shock"


class OrderSide(str, Enum):
    buy = "buy"
    sell = "sell"


class OrderState(str, Enum):
    pending = "pending"
    submitted = "submitted"
    filled = "filled"
    partially_filled = "partially_filled"
    rejected = "rejected"
    cancelled = "cancelled"
    closed = "closed"


# --------------------------------------------------------------------------- market
class Candle(BaseModel):
    t: int                      # epoch seconds (bar open)
    o: float
    h: float
    l: float
    c: float
    v: float


class Tick(BaseModel):
    t: float                    # epoch seconds, float for sub-second ticks
    bid: float
    ask: float
    spread_points: float
    last: float


class SymbolSpec(BaseModel):
    symbol: str
    description: str = ""
    digits: int = 2
    point: float = 0.01
    tick_size: float = 0.01
    contract_size: float = 100.0
    min_lot: float = 0.01
    max_lot: float = 50.0
    lot_step: float = 0.01
    stops_level_points: float = 0.0
    freeze_level_points: float = 0.0
    spread_typical_points: float = 25.0
    commission_per_lot_round_turn: float = 0.0
    swap_long_per_lot: float = 0.0
    swap_short_per_lot: float = 0.0
    profit_currency: str = "USD"
    # Multiplier that turns one unit of `profit_currency` into one unit of the
    # account currency. 1.0 means "same currency" (or that no rate was needed).
    quote_to_account_rate: float = 1.0
    rate_source: Literal["identity", "ticker", "triangulated", "unknown"] = "identity"
    source: Literal["broker", "declared"] = "declared"

    @property
    def value_per_point_per_lot(self) -> float:
        """Account-currency profit for a 1.0 point move on 1.0 lot."""
        return self.point * self.contract_size * self.quote_to_account_rate

    @property
    def quote_in_account_currency(self) -> bool:
        """True when one point of P&L is already denominated in the account currency."""
        return self.profit_currency.upper() == "USD"

    @property
    def sizing_blocked(self) -> bool:
        """A cross pair whose FX rate could not be resolved must not be sized.

        Applying an assumed 1.0 rate to, say, USDJPY would overstate the value of
        a point by the whole exchange rate (about 150x), so the planner is told to
        stand down instead.
        """
        return not self.quote_in_account_currency and self.rate_source == "unknown"

    def round_price(self, price: float) -> float:
        """Snap to the broker's legal price grid (tick size), not just digits."""
        tick = self.tick_size or self.point
        if not tick or tick <= 0:
            return round(price, self.digits)
        snapped = round(round(price / tick) * tick, self.digits)
        return float(f"{snapped:.{self.digits}f}")

    def points_to_price(self, points: float) -> float:
        return round(points * self.point, self.digits)

    def price_to_points(self, distance: float) -> float:
        return distance / self.point if self.point else 0.0

    def normalize_lot(self, lot: float) -> float:
        """Round a lot *down* to the broker step.

        Rounding to the nearest step could hand back a position slightly larger
        than the risk budget allowed, so sizing always floors; only a size below
        the broker minimum is raised to that minimum (the caller reports it).
        """
        step = self.lot_step or 0.01
        if lot <= 0:
            return 0.0
        steps = math.floor(lot / step + 1e-9)
        snapped = round(steps * step, 4)
        if snapped < self.min_lot - 1e-12:
            return float(self.min_lot)
        return round(min(self.max_lot, snapped), 4)

    def lot_is_valid(self, lot: float) -> bool:
        step = self.lot_step or 0.01
        ratio = lot / step
        return abs(ratio - round(ratio)) < 1e-6 and self.min_lot - 1e-9 <= lot <= self.max_lot + 1e-9


class AccountInfo(BaseModel):
    broker_id: str
    label: str
    server: str
    account_type: str
    login: str = "—"
    currency: str = "USD"
    balance: float
    equity: float
    margin: float = 0.0
    free_margin: float
    leverage: int = 100
    health: Health = Health.connected
    adapter: str = "simulated_mt5"
    live_allowed: bool = False
    last_sync: float = 0.0
    message: str = ""
    regulated_note: str = ""


# --------------------------------------------------------------------------- analysis
class SwingPoint(BaseModel):
    idx: int
    t: int
    price: float
    kind: Literal["high", "low"]
    label: str = ""
    confirmed: bool = True


class StructureEvent(BaseModel):
    kind: Literal["BOS", "CHoCH", "NONE"] = "NONE"
    direction: Direction = Direction.sideways
    level: float = 0.0
    t: int = 0
    bars_ago: int = 0
    confirmed: bool = True
    note: str = ""


class TrendReading(BaseModel):
    timeframe: str
    direction: Direction
    strength: float               # 0..1
    adx: float = 0.0
    ema_slope_points: float = 0.0
    price_vs_ema200_pct: float = 0.0
    note: str = ""


class ZoneEvidence(BaseModel):
    family: str
    label: str
    weight: float
    detail: str


class Zone(BaseModel):
    id: str
    kind: ZoneKind
    low: float
    high: float
    mid: float
    strength: float               # 0..1 weighted confluence
    quality: ZoneQuality
    status: ZoneStatus
    families: list[str] = Field(default_factory=list)
    evidence: list[ZoneEvidence] = Field(default_factory=list)
    touches: int = 0
    distance_points: float = 0.0
    distance_atr: float = 0.0
    created_t: int = 0
    last_tested_t: int | None = None
    note: str = ""

    @property
    def independent_families(self) -> int:
        return len(set(self.families))


class RegimeReading(BaseModel):
    regime: Regime
    confidence: float
    adx: float
    atr_points: float
    atr_percentile: float
    note: str = ""
    strategy: str = ""


class IndicatorSnapshot(BaseModel):
    ema20: float = 0.0
    ema50: float = 0.0
    ema200: float = 0.0
    rsi14: float = 50.0
    atr14: float = 0.0
    atr_points: float = 0.0
    adx14: float = 0.0
    macd: float = 0.0
    macd_signal: float = 0.0
    macd_hist: float = 0.0
    vwap: float = 0.0
    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0
    volume_z: float = 0.0
    bb_width_pct: float = 0.0


class AnalysisSnapshot(BaseModel):
    symbol: str
    timeframe: str
    broker_id: str
    price: float
    server_time: int
    spec: SymbolSpec
    trend: list[TrendReading] = Field(default_factory=list)
    structure: list[StructureEvent] = Field(default_factory=list)
    swings: list[SwingPoint] = Field(default_factory=list)
    zones: list[Zone] = Field(default_factory=list)
    supports: list[Zone] = Field(default_factory=list)
    resistances: list[Zone] = Field(default_factory=list)
    regime: RegimeReading | None = None
    indicators: IndicatorSnapshot = Field(default_factory=IndicatorSnapshot)
    pivots: dict[str, float] = Field(default_factory=dict)
    session_high: float = 0.0
    session_low: float = 0.0
    news_lockout: dict[str, Any] = Field(default_factory=dict)
    data_quality: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- forecast
class HorizonForecast(BaseModel):
    horizon_minutes: int
    p_up: float
    p_down: float
    p_sideways: float
    calibrated: bool = False
    method: str = "statistical"
    expected_move_points: float = 0.0
    p10_points: float = 0.0
    p50_points: float = 0.0
    p90_points: float = 0.0
    p10_price: float = 0.0
    p50_price: float = 0.0
    p90_price: float = 0.0
    p_tp_before_sl: float = 0.0
    tp_points: float = 0.0
    sl_points: float = 0.0
    volatility_points: float = 0.0
    confidence: float = 0.0
    coverage_note: str = ""
    invalidate_above: float = 0.0
    invalidate_below: float = 0.0
    directional_accuracy_oos: float | None = None
    sample_size: int = 0


class ForecastPathPoint(BaseModel):
    t: int
    p10: float
    p50: float
    p90: float


class Scenario(BaseModel):
    name: Literal["bull", "base", "bear"]
    probability: float
    target_price: float
    path: list[ForecastPathPoint] = Field(default_factory=list)
    description: str = ""


class ForecastBundle(BaseModel):
    symbol: str
    generated_at: int
    price: float
    model_version: str = "baseline-statistical"
    model_approved: bool = False
    method: str = "statistical"
    confidence: float = 0.0
    horizons: list[HorizonForecast] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list)
    invalidation: list[str] = Field(default_factory=list)
    narrative: str = ""
    regime: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- signals
class ScoreComponent(BaseModel):
    key: str
    label: str
    score: float
    max_score: float
    detail: str


class PartialTarget(BaseModel):
    level: int
    price: float
    points: float
    close_pct: float
    volume: float
    feasible: bool = True
    note: str = ""


class TradePlan(BaseModel):
    direction: Direction
    entry: float
    sl: float
    tp1: float
    tp2: float
    tp3: float
    sl_points: float
    tp_points: list[float] = Field(default_factory=list)
    lot: float = 0.0
    risk_amount: float = 0.0
    risk_pct: float = 0.0
    reward_risk: float = 0.0
    reward_risk_net: float = 0.0
    estimated_cost: float = 0.0
    expected_value: float = 0.0
    p_tp_before_sl: float = 0.0
    partials: list[PartialTarget] = Field(default_factory=list)
    target_mode: str = "adaptive"
    notes: list[str] = Field(default_factory=list)


class Signal(BaseModel):
    id: str
    t: int
    symbol: str
    timeframe: str
    broker_id: str
    action: SignalAction
    status: SignalStatus
    score: float
    strategy: str
    regime: str
    components: list[ScoreComponent] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    plan: TradePlan | None = None
    forecast: HorizonForecast | None = None
    zones_used: list[str] = Field(default_factory=list)
    mode: TradeMode = TradeMode.manual
    approval_required: bool = True
    approved_by: str | None = None
    approved_at: int | None = None
    rejected_reason: str | None = None
    expires_at: int = 0
    executed_order_id: str | None = None
    explanation: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- risk
class RiskLimits(BaseModel):
    risk_per_trade_pct: float = 0.5
    max_daily_loss_pct: float = 2.0
    max_weekly_loss_pct: float = 5.0
    max_drawdown_pct: float = 10.0
    max_open_trades: int = 1
    max_open_per_symbol: int = 1
    max_consecutive_losses: int = 3
    cooldown_minutes: int = 20
    max_spread_points: float = 60
    max_slippage_points: float = 15
    max_exposure_lots: float = 1.0
    max_leverage_notional_x_equity: float = 5.0
    min_free_margin_pct: float = 30.0
    min_reward_risk: float = 1.3
    max_weekly_trades: int = 60
    data_staleness_seconds: int = 30
    news_lockout_enabled: bool = True
    news_window_before_minutes: int = 30
    news_window_after_minutes: int = 15
    abnormal_volatility_atr_pct: float = 3.0


class RiskSettings(BaseModel):
    limits: RiskLimits = Field(default_factory=RiskLimits)
    targets_mode: str = "adaptive"
    fixed_points: list[float] = Field(default_factory=lambda: [500, 750, 1000])
    min_points: float = 500
    max_points: float = 1000
    sl_atr_multiplier: float = 1.5
    full_auto_enabled: bool = False
    news_lockout_enabled: bool = True


class RiskState(BaseModel):
    balance: float
    equity: float
    peak_equity: float
    daily_pnl: float
    daily_pnl_pct: float
    weekly_pnl: float
    weekly_pnl_pct: float
    drawdown_pct: float
    open_trades: int
    open_lots: float
    exposure_pct: float
    consecutive_losses: int
    trades_today: int
    trades_this_week: int
    cooldown_until: int | None = None
    kill_switch_active: bool = False
    kill_switch_reason: str = ""
    max_trades_allowed: int = 1
    mode: TradeMode = TradeMode.manual
    updated_at_virtual: float = 0.0


# --------------------------------------------------------------------------- execution
class Position(BaseModel):
    ticket: str
    symbol: str
    direction: Direction
    volume: float
    entry: float
    sl: float
    tp: float
    open_time: int
    current_price: float
    points: float = 0.0
    unrealized: float = 0.0
    comment: str = ""
    signal_id: str | None = None
    strategy: str = ""
    partials_done: int = 0
    max_favorable_points: float = 0.0
    breakeven_done: bool = False
    trailing_active: bool = False
    broker_id: str = "connext-demo"


class OrderRequest(BaseModel):
    symbol: str
    side: OrderSide
    volume: float
    price: float | None = None
    sl: float | None = None
    tp: float | None = None
    comment: str = ""
    signal_id: str | None = None
    idempotency_key: str | None = None
    mode: TradeMode = TradeMode.manual
    broker_id: str | None = None


class OrderResult(BaseModel):
    order_id: str
    idempotency_key: str
    status: OrderState
    retcode: int = 0
    message: str = ""
    ticket: str | None = None
    filled_volume: float = 0.0
    fill_price: float | None = None
    slippage_points: float = 0.0
    latency_ms: float = 0.0
    verified: bool = False
    created_at: float = 0.0


class TradeRecord(BaseModel):
    ticket: str
    symbol: str
    direction: Direction
    volume: float
    entry: float
    exit: float
    sl: float = 0.0
    tp: float = 0.0
    opened_at: int
    closed_at: int
    points: float
    gross_pnl: float
    costs: float
    swap: float = 0.0
    pnl: float
    r_multiple: float = 0.0
    exit_reason: str = ""
    strategy: str = ""
    signal_id: str | None = None
    mode: TradeMode = TradeMode.manual
    broker_id: str = "connext-demo"
    journal: dict[str, Any] = Field(default_factory=dict)


class TradeJournalEntry(BaseModel):
    trade: TradeRecord
    headline: str
    what_worked: list[str] = Field(default_factory=list)
    what_failed: list[str] = Field(default_factory=list)
    lesson: str = ""
    tags: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- backtest
class BacktestRequest(BaseModel):
    symbol: str = "XAUUSD"
    broker_id: str | None = None
    strategy: str = "all"
    bars: int = 8000
    risk_per_trade_pct: float = 0.5
    spread_points: float | None = None
    commission_per_lot: float | None = None
    slippage_points: float = 2.0
    starting_balance: float = 10000.0
    validate_walk_forward: bool = True
    seed: int = 7


class BacktestMetrics(BaseModel):
    trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_profit: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    expectancy_r: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    tp_before_sl_rate: float = 0.0
    directional_accuracy: float = 0.0
    no_trade_rate: float = 0.0
    avg_hold_minutes: float = 0.0
    total_costs: float = 0.0
    total_swap: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    return_pct: float = 0.0
    recovery_factor: float = 0.0
    max_consecutive_losses: int = 0


class EquityPoint(BaseModel):
    t: int
    equity: float
    balance: float
    drawdown_pct: float = 0.0


class BacktestReport(BaseModel):
    id: str
    created_at: int
    symbol: str
    strategy: str
    broker_id: str
    bars: int
    from_t: int = 0
    to_t: int = 0
    # sha256 of the OHLCV the run consumed: same fingerprint => same numbers.
    data_fingerprint: str = ""
    seed: int = 7
    metrics: BacktestMetrics = Field(default_factory=BacktestMetrics)
    equity_curve: list[EquityPoint] = Field(default_factory=list)
    trades: list[TradeRecord] = Field(default_factory=list)
    per_strategy: dict[str, BacktestMetrics] = Field(default_factory=dict)
    per_regime: dict[str, BacktestMetrics] = Field(default_factory=dict)
    walk_forward: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    verdict: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- misc
class Alert(BaseModel):
    id: str
    t: int
    level: Literal["info", "success", "warning", "critical"] = "info"
    title: str
    message: str
    channel: str = "inapp"
    symbol: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class ModelInfo(BaseModel):
    version: str
    created_at: int
    method: str
    approved: bool
    horizons: list[int]
    metrics: dict[str, Any] = Field(default_factory=dict)
    features: int = 0
    samples: int = 0
    notes: str = ""


class HealthReport(BaseModel):
    status: str = "ok"
    version: str = "V1"
    env: str = "development"
    server_time: float
    virtual_time: float
    uptime_seconds: float
    feed_mode: str
    broker_health: dict[str, str] = Field(default_factory=dict)
    model: ModelInfo | None = None
    services: dict[str, str] = Field(default_factory=dict)
