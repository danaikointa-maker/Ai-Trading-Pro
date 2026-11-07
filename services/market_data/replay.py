"""Replay imported candles through the live pipeline.

`scripts/import_candles.py` + `scripts/evaluate_dataset.py` prove what the engine
does on real bars, but they run offline: the dashboard itself keeps ticking on the
synthetic feed. This feed closes that gap — it walks imported M1 bars at a
configurable speed and hands the rest of the system the same interface
`SyntheticFeed` provides, so analysis, forecasting, gating and the paper broker all
run unchanged on real prices.

Two things it deliberately does *not* do:

* invent bars past the end of the file. When the data runs out the clock stops,
  ticks freeze at the last close and the feed reports `exhausted` — the data-quality
  gate then blocks new decisions instead of trading on a fantasy continuation.
* pretend the intra-bar path is tick data. It is not: between a bar's open and close
  the price walks a deterministic path that stays inside the bar's own high/low, so
  SL/TP hits inside a bar remain an approximation (documented in LIMITATIONS).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from packages.shared_schemas.models import Tick

REQUIRED_COLUMNS = ("t", "o", "h", "l", "c")


class ReplayError(RuntimeError):
    """Raised when the imported data cannot drive a feed."""


@dataclass
class ReplayState:
    symbol: str
    bars: pd.DataFrame
    point: float
    digits: int
    spread_points_typical: float
    index: int = 0
    tick_in_bar: int = 0
    price: float = 0.0
    bar: dict[str, float] | None = None
    last_tick: Tick | None = None
    history: pd.DataFrame = field(default_factory=pd.DataFrame)
    exhausted: bool = False


class ReplayFeed:
    """An M1 stream read from imported candles, ticking inside each bar."""

    def __init__(self, frames: dict[str, pd.DataFrame], symbols: dict[str, dict[str, Any]],
                 speed_minutes_per_second: float = 6.0, tick_seconds: float = 0.5,
                 warmup_bars: int = 900, seed: int = 7, loop: bool = False) -> None:
        self.speed_minutes_per_second = max(0.1, float(speed_minutes_per_second))
        self.tick_seconds = max(0.05, float(tick_seconds))
        seconds_per_bar = 60.0 / self.speed_minutes_per_second
        self.ticks_per_bar = max(4, int(round(seconds_per_bar / self.tick_seconds)))
        self.virtual_seconds_per_tick = 60.0 / self.ticks_per_bar
        self.warmup_bars = max(60, int(warmup_bars))
        self.seed = int(seed)
        self.loop = bool(loop)
        self.states: dict[str, ReplayState] = {}
        self.exhausted = False
        self._build(frames, symbols)

    # ------------------------------------------------------------------ setup
    def _build(self, frames: dict[str, pd.DataFrame], symbols: dict[str, dict[str, Any]]) -> None:
        for idx, (symbol, frame) in enumerate(frames.items()):
            spec = symbols.get(symbol, {})
            bars = self._validate(symbol, frame)
            if len(bars) < self.warmup_bars + 2:
                raise ReplayError(
                    f"{symbol}: {len(bars)} bars is not enough for a {self.warmup_bars}-bar "
                    "warm-up plus replay — import more history or lower market_data.replay.warmup_bars")
            state = ReplayState(
                symbol=symbol,
                bars=bars,
                point=float(spec.get("point", 0.01)),
                digits=int(spec.get("digits", 2)),
                spread_points_typical=float(spec.get("spread_typical_points", 25)),
                index=self.warmup_bars,
                price=float(bars["c"].iloc[self.warmup_bars - 1]),
                history=bars.iloc[: self.warmup_bars].reset_index(drop=True),
            )
            state.history = state.history.astype({"t": "int64"})
            self.states[symbol] = state
            del idx
        if not self.states:
            raise ReplayError("no symbol has imported data to replay")
        self.end_time = float(
            min(state.bars["t"].iloc[state.index] for state in self.states.values()))
        self.history_bars = max(len(s.history) for s in self.states.values())
        self._rng = {sym: np.random.default_rng(self.seed + 17 * i)
                     for i, sym in enumerate(self.states)}

    @staticmethod
    def _validate(symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
        missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
        if missing:
            raise ReplayError(f"{symbol}: candle frame is missing {missing}")
        bars = frame.loc[:, ["t", "o", "h", "l", "c", "v"]].copy()
        bars["t"] = bars["t"].astype("int64")
        bars = bars.sort_values("t", kind="stable").drop_duplicates("t").reset_index(drop=True)
        if not bars["t"].is_monotonic_increasing:
            raise ReplayError(f"{symbol}: timestamps are not in order after sorting")
        return bars

    # ------------------------------------------------------------------- ticks
    def _spread_points(self, state: ReplayState) -> float:
        rng = self._rng[state.symbol]
        return max(1.0, state.spread_points_typical * rng.uniform(0.9, 1.25))

    def _intrabar_price(self, state: ReplayState) -> float:
        """A path from open to close that never leaves the bar's own range."""
        bar = state.bar
        assert bar is not None
        frac = min(1.0, (state.tick_in_bar + 1) / self.ticks_per_bar)
        walk = bar["o"] + (bar["c"] - bar["o"]) * frac
        span = max(bar["h"] - bar["l"], state.point)
        noise = self._rng[state.symbol].normal(0.0, span / 8.0)
        return float(min(bar["h"], max(bar["l"], walk + noise)))

    def tick(self) -> dict[str, Tick]:
        out: dict[str, Tick] = {}
        if self.exhausted:
            return {sym: state.last_tick for sym, state in self.states.items()
                    if state.last_tick is not None}
        for state in self.states.values():
            if state.exhausted:
                if state.last_tick is not None:
                    out[state.symbol] = state.last_tick
                continue
            if state.bar is None:
                row = state.bars.iloc[state.index]
                state.bar = {"t": float(row["t"]), "o": float(row["o"]), "h": float(row["h"]),
                             "l": float(row["l"]), "c": float(row["c"]), "v": float(row["v"])}
                state.tick_in_bar = 0

            price = self._intrabar_price(state)
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
        if all(state.exhausted for state in self.states.values()):
            self.exhausted = True
        return out

    def _close_bar(self, state: ReplayState) -> None:
        bar = state.bar
        assert bar is not None
        row = pd.DataFrame([{k: bar[k] for k in ("t", "o", "h", "l", "c", "v")}])
        row = row.round({"o": state.digits, "h": state.digits, "l": state.digits, "c": state.digits})
        state.history = pd.concat([state.history, row], ignore_index=True)
        state.history = state.history.astype({"t": "int64"})
        state.price = float(bar["c"])
        state.bar = None
        state.tick_in_bar = 0
        state.index += 1
        if state.index >= len(state.bars):
            if self.loop:
                state.index = self.warmup_bars
                state.history = state.bars.iloc[: self.warmup_bars].reset_index(drop=True)
            else:
                state.exhausted = True

    def advance_clock(self) -> None:
        if not self.exhausted:
            self.end_time += self.virtual_seconds_per_tick

    # ------------------------------------------------------------------ reads
    def warm_history(self, symbol: str, bars: int) -> pd.DataFrame:
        state = self.states[symbol]
        return state.history.tail(bars).reset_index(drop=True).copy()

    def ticker(self, symbol: str) -> Tick:
        state = self.states[symbol]
        if state.last_tick is not None:
            return state.last_tick
        spread = self._spread_points(state)
        half = spread * state.point / 2.0
        return Tick(t=round(self.end_time, 3), bid=round(state.price - half, state.digits),
                    ask=round(state.price + half, state.digits),
                    spread_points=round(spread, 1), last=round(state.price, state.digits))

    def state_of(self, symbol: str) -> ReplayState:
        return self.states[symbol]

    def last_bar_price(self, symbol: str) -> float:
        return float(self.states[symbol].history["c"].iloc[-1])

    def inject_shock(self, symbol: str, bps: float = 25.0) -> None:
        """No-op: replay never invents a price the file does not contain."""
        del symbol, bps

    # ----------------------------------------------------------------- status
    @property
    def symbols(self) -> list[str]:
        return list(self.states)

    def describe(self) -> dict[str, Any]:
        out: dict[str, Any] = {"mode": "replay", "exhausted": self.exhausted,
                               "loop": self.loop,
                               "virtual_time": round(self.end_time, 1), "symbols": {}}
        for symbol, state in self.states.items():
            total = max(1, len(state.bars) - self.warmup_bars)
            out["symbols"][symbol] = {
                "bars_total": int(len(state.bars)),
                "warmup_bars": int(self.warmup_bars),
                "bars_replayed": int(state.index - self.warmup_bars),
                "progress": round(min(1.0, (state.index - self.warmup_bars) / total), 4),
                "exhausted": state.exhausted,
                "from": pd.Timestamp(int(state.bars["t"].iloc[0]), unit="s", tz="UTC").isoformat(),
                "to": pd.Timestamp(int(state.bars["t"].iloc[-1]), unit="s", tz="UTC").isoformat(),
            }
        return out


def build_feed(settings: Any, symbols: dict[str, dict[str, Any]],
               required: list[str] | tuple[str, ...] | None = None):
    """Pick the feed the runtime should use, and say what actually happened.

    Returns ``(feed, mode, note)``. A requested replay that cannot start (no
    imported file, too few bars) falls back to the simulated feed **and says so** —
    a silent fallback would make the dashboard's numbers look like real data.

    ``required`` names the symbols the active broker actually trades: those must
    have imported data. Symbols belonging only to other broker profiles are used
    when their file exists and skipped when it does not, instead of blocking
    replay on data the running configuration never reads.
    """
    from services.market_data.dataset import DatasetError, load_dataset
    from services.market_data.simulator import SyntheticFeed

    md = settings.market_data
    sim = md.get("simulation", {})
    mode_requested = str(md.get("feed_mode", "simulate")).lower()

    def simulated() -> Any:
        return SyntheticFeed(
            symbols=symbols or {"XAUUSD": settings.symbol_spec("connext-demo", "XAUUSD")},
            history_bars=int(md.get("history_bars", 60000)),
            seed=int(sim.get("seed", 7)),
            start_price=float(sim.get("start_price", 4180.0)),
            annual_vol=float(sim.get("annual_volatility", 0.16)),
            speed_minutes_per_second=float(sim.get("speed_minutes_per_second", 6.0)),
            tick_seconds=float(sim.get("tick_seconds", 0.5)),
            news_shock_probability=float(sim.get("news_shock_probability", 0.0015)),
        )

    if mode_requested != "replay":
        return simulated(), "simulate", None

    replay_cfg = md.get("replay", {}) or {}
    dataset_dir = replay_cfg.get("dataset_dir", str(settings.paths["datasets"]))
    timeframe = str(replay_cfg.get("timeframe", "M1"))
    must_have = set(required or symbols)
    try:
        frames: dict[str, Any] = {}
        missing: list[str] = []
        for symbol in symbols:
            try:
                frames[symbol] = load_dataset(dataset_dir, symbol, timeframe)
            except DatasetError as exc:
                if symbol in must_have:
                    raise
                missing.append(f"{symbol} ({exc})")
        if not frames:
            raise DatasetError("no imported datasets match the configured symbols")
        feed = ReplayFeed(
            frames=frames,
            symbols={k: v for k, v in symbols.items() if k in frames},
            speed_minutes_per_second=float(replay_cfg.get("speed_minutes_per_second", 6.0)),
            tick_seconds=float(replay_cfg.get("tick_seconds", 0.5)),
            warmup_bars=int(replay_cfg.get("warmup_bars", 900)),
            seed=int(sim.get("seed", 7)),
            loop=bool(replay_cfg.get("loop", False)),
        )
    except (DatasetError, ReplayError) as exc:
        return simulated(), "simulate", f"replay requested but unavailable ({exc}); using the simulated feed"
    note = (f"replay covers {sorted(frames)}; no imported data for {missing} "
            "(symbols of other broker profiles, not traded by the active one)") if missing else None
    return feed, "replay", note
