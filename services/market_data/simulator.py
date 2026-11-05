"""Deterministic synthetic XAUUSD-style feed used when no MT5 terminal exists.

The generator is a regime-switching diffusion with intrabar wicks, volume
clustering and occasional news shocks. It exists so the whole pipeline
(analysis -> forecast -> signal -> risk -> execution -> journal) can be
exercised and demonstrated on Linux, and it is clearly labelled as SIMULATED
everywhere it surfaces. Swap ``NO7_FEED_MODE=mt5`` to use the real terminal.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from packages.shared_schemas.models import Candle, Tick


@dataclass
class RegimeParams:
    name: str
    drift_bps: float
    vol_bps: float
    duration: int


REGIMES = [
    RegimeParams("trend_up", 0.55, 6.5, 420),
    RegimeParams("trend_up_strong", 1.15, 8.0, 220),
    RegimeParams("trend_down", -0.60, 7.0, 400),
    RegimeParams("trend_down_strong", -1.20, 9.0, 200),
    RegimeParams("range", 0.0, 5.0, 520),
    RegimeParams("range_tight", 0.0, 3.0, 300),
    RegimeParams("volatile", 0.0, 14.0, 160),
]


@dataclass
class SymbolState:
    symbol: str
    point: float
    digits: int
    spread_points_typical: float
    price: float
    rng: np.random.Generator
    regime: RegimeParams
    regime_left: int
    history: pd.DataFrame = field(default_factory=pd.DataFrame)
    bar: dict | None = None
    tick_in_bar: int = 0
    last_tick: Tick | None = None


class SyntheticFeed:
    """One M1 bar stream per symbol plus a tick-level last price."""

    def __init__(
        self,
        symbols: dict[str, dict],
        history_bars: int = 20000,
        seed: int = 7,
        start_price: float = 4180.0,
        annual_vol: float = 0.22,
        speed_minutes_per_second: float = 6.0,
        tick_seconds: float = 0.5,
        news_shock_probability: float = 0.0015,
        end_time: float | None = None,
    ) -> None:
        self.history_bars = max(600, int(history_bars))
        self.seed = int(seed)
        self.start_price = float(start_price)
        self.annual_vol = float(annual_vol)
        self.tick_seconds = float(tick_seconds)
        seconds_per_bar = 60.0 / max(0.1, speed_minutes_per_second)
        self.ticks_per_bar = max(4, int(round(seconds_per_bar / self.tick_seconds)))
        self.virtual_seconds_per_tick = 60.0 / self.ticks_per_bar
        self.news_shock_probability = float(news_shock_probability)
        self.states: dict[str, SymbolState] = {}
        self.end_time = float(end_time if end_time is not None else time.time())
        self._build(symbols)

    # ------------------------------------------------------------------ setup
    def _build(self, symbols: dict[str, dict]) -> None:
        for idx, (symbol, spec) in enumerate(symbols.items()):
            rng = np.random.default_rng(self.seed + 17 * idx)
            price = self.start_price * (1.0 + 0.02 * idx) if symbol.upper().startswith("XAU") else 1.0850
            if symbol.upper().startswith("XAG"):
                price = 52.0
            state = SymbolState(
                symbol=symbol,
                point=float(spec["point"]),
                digits=int(spec["digits"]),
                spread_points_typical=float(spec.get("spread_typical_points", 25)),
                price=price,
                rng=rng,
                regime=REGIMES[4],
                regime_left=REGIMES[4].duration,
            )
            state.history = self._generate_history(state, self.history_bars)
            state.price = float(state.history["c"].iloc[-1])
            self.states[symbol] = state

    def _pick_regime(self, rng: np.random.Generator) -> RegimeParams:
        base = REGIMES[int(rng.integers(0, len(REGIMES)))]
        return RegimeParams(base.name, base.drift_bps, base.vol_bps,
                            int(base.duration * rng.uniform(0.6, 1.4)))

    def _generate_history(self, state: SymbolState, bars: int) -> pd.DataFrame:
        rng = state.rng
        start = self.end_time - bars * 60
        start = float(int(start // 60) * 60)
        # Scale the diffusion so the realised annualised vol roughly matches config.
        bar_vol_scale = self.annual_vol / math.sqrt(525600) / 1e-4  # bps per minute
        times = np.arange(start, start + bars * 60, 60, dtype=np.int64)
        o = np.empty(bars)
        h = np.empty(bars)
        l = np.empty(bars)
        c = np.empty(bars)
        v = np.empty(bars)
        price = state.price
        regime = state.regime
        left = state.regime_left
        for i in range(bars):
            if left <= 0:
                regime = self._pick_regime(rng)
                left = regime.duration
            left -= 1
            vol = max(0.6, regime.vol_bps * bar_vol_scale / 6.0)
            ret = regime.drift_bps * 1e-4 * (bar_vol_scale / 6.0) + vol * 1e-4 * rng.standard_normal()
            if rng.random() < self.news_shock_probability:
                ret += rng.choice([-1, 1]) * rng.uniform(4, 12) * 1e-4
            prev = price
            price = max(0.01, prev * (1.0 + ret))
            wick = abs(rng.standard_normal()) * vol * 1e-4 * price
            hi = max(prev, price) + wick * 0.45
            lo = min(prev, price) - wick * 0.45
            o[i] = prev
            c[i] = price
            h[i] = hi
            l[i] = lo
            v[i] = float(max(1.0, rng.lognormal(mean=5.2, sigma=0.55) * (1 + abs(ret) * 400)))
        state.regime = regime
        state.regime_left = left
        df = pd.DataFrame({"t": times, "o": o, "h": h, "l": l, "c": c, "v": v})
        return df.round({k: state.digits for k in ("o", "h", "l", "c")})

    # ------------------------------------------------------------------- tick
    def _spread_points(self, state: SymbolState) -> float:
        rng = state.rng
        vol_factor = 1.0 + (0.6 if state.regime.name == "volatile" else 0.0)
        return max(1.0, state.spread_points_typical * vol_factor * rng.uniform(0.85, 1.35))

    def tick(self) -> dict[str, Tick]:
        out: dict[str, Tick] = {}
        for state in self.states.values():
            rng = state.rng
            if state.bar is None:
                minute = float(int(self.end_time // 60) * 60)
                state.bar = {"t": int(minute), "o": state.price, "h": state.price,
                             "l": state.price, "c": state.price, "v": 0.0}
                state.tick_in_bar = 0
            if state.regime_left <= 0:
                state.regime = self._pick_regime(rng)
                state.regime_left = state.regime.duration
            bar_vol_scale = self.annual_vol / math.sqrt(525600) / 1e-4
            vol = max(0.6, state.regime.vol_bps * bar_vol_scale / 6.0)
            dt = 1.0 / self.ticks_per_bar
            ret = state.regime.drift_bps * 1e-4 * (bar_vol_scale / 6.0) * dt + vol * 1e-4 * math.sqrt(dt) * rng.standard_normal()
            state.bar["c"] = max(0.01, state.bar["c"] * (1.0 + ret))
            price = state.bar["c"]
            state.bar["h"] = max(state.bar["h"], price)
            state.bar["l"] = min(state.bar["l"], price)
            state.bar["v"] += float(abs(rng.normal(1.0, 0.4)) * 10)
            state.tick_in_bar += 1

            spread_pts = self._spread_points(state)
            half = spread_pts * state.point / 2.0
            tick = Tick(
                t=round(self.end_time, 3),
                bid=round(price - half, state.digits),
                ask=round(price + half, state.digits),
                spread_points=round(spread_pts, 1),
                last=round(price, state.digits),
            )
            state.last_tick = tick
            out[state.symbol] = tick

            if state.tick_in_bar >= self.ticks_per_bar:
                self._close_bar(state)
        return out

    def _close_bar(self, state: SymbolState) -> None:
        bar = state.bar
        assert bar is not None
        row = pd.DataFrame([{k: bar[k] for k in ("t", "o", "h", "l", "c", "v")}])
        row = row.round({"o": state.digits, "h": state.digits, "l": state.digits, "c": state.digits})
        state.history = pd.concat([state.history.iloc[-self.history_bars:], row], ignore_index=True)
        state.history = state.history.astype({"t": "int64"})
        state.price = float(bar["c"])
        state.bar = None
        state.tick_in_bar = 0
        state.regime_left -= 1 if state.regime_left > 0 else 0

    def advance_clock(self) -> None:
        self.end_time += self.virtual_seconds_per_tick

    def warm_history(self, symbol: str, bars: int) -> pd.DataFrame:
        """Deep copy of the tail of the M1 history for analysis/backtests."""
        state = self.states[symbol]
        return state.history.tail(bars).reset_index(drop=True).copy()

    def ticker(self, symbol: str) -> Tick:
        state = self.states[symbol]
        if state.last_tick is not None:
            return state.last_tick
        spread = self._spread_points(state)
        half = spread * state.point / 2
        return Tick(t=round(self.end_time, 3), bid=round(state.price - half, state.digits),
                    ask=round(state.price + half, state.digits),
                    spread_points=round(spread, 1), last=round(state.price, state.digits))

    def state_of(self, symbol: str) -> SymbolState:
        return self.states[symbol]

    def last_bar_price(self, symbol: str) -> float:
        return float(self.states[symbol].history["c"].iloc[-1])

    def inject_shock(self, symbol: str, bps: float = 25.0) -> None:
        """Manual shock for demos/tests (e.g. simulate a CPI spike)."""
        state = self.states[symbol]
        state.bar = state.bar or {"t": int(self.end_time // 60) * 60, "o": state.price,
                                  "h": state.price, "l": state.price, "c": state.price, "v": 0.0}
        move = state.bar["c"] * bps * 1e-4
        state.bar["c"] += move
        state.bar["h"] = max(state.bar["h"], state.bar["c"])
        state.bar["l"] = min(state.bar["l"], state.bar["c"])
        state.bar["v"] *= 1.6


TIMEFRAME_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400,
}


def resample(m1: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Aggregate M1 candles into a higher timeframe, aligned to epoch boundaries."""
    seconds = TIMEFRAME_SECONDS[timeframe]
    if seconds == 60:
        return m1.copy()
    df = m1.copy()
    df["bucket"] = (df["t"] // seconds) * seconds
    agg = df.groupby("bucket", as_index=False).agg(
        o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last"), v=("v", "sum")
    )
    return agg.rename(columns={"bucket": "t"})


def candles_from_df(df: pd.DataFrame, limit: int | None = None) -> list[Candle]:
    if limit:
        df = df.tail(limit)
    return [
        Candle(t=int(r.t), o=float(r.o), h=float(r.h), l=float(r.l), c=float(r.c), v=float(r.v))
        for r in df.itertuples(index=False)
    ]
