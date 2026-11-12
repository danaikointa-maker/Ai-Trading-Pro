"""Replay feed: imported candles driving the live pipeline.

The feed exists so the dashboard can be measured on real bars instead of the
synthetic walk. Two properties matter more than anything else: a tick must never
leave the bar it belongs to, and the feed must stop at the end of the file rather
than invent a continuation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.market_data.dataset import import_candles
from services.market_data.replay import ReplayError, ReplayFeed, build_feed


def frame(n: int = 400, start: int = 1793000000, base: float = 4200.0) -> pd.DataFrame:
    t0 = int(start - start % 60)
    times = t0 + np.arange(n, dtype=np.int64) * 60
    closes = base * np.cumprod(1 + np.sin(np.arange(n) / 9.0) * 0.0004)
    opens = np.concatenate([[base], closes[:-1]])
    highs = np.maximum(opens, closes) * 1.0004
    lows = np.minimum(opens, closes) * 0.9996
    return pd.DataFrame({"t": times, "o": opens.round(2), "h": highs.round(2),
                         "l": lows.round(2), "c": closes.round(2),
                         "v": np.linspace(100, 200, n)})


SYMBOLS = {"XAUUSD": {"point": 0.01, "digits": 2, "spread_typical_points": 25}}


def feed_for(n: int = 400, warmup: int = 120, **kwargs) -> ReplayFeed:
    return ReplayFeed({"XAUUSD": frame(n)}, SYMBOLS, warmup_bars=warmup,
                      speed_minutes_per_second=60.0, tick_seconds=1.0, **kwargs)


def test_warmup_history_is_what_analysis_sees_first():
    feed = feed_for(warmup=120)
    history = feed.warm_history("XAUUSD", 10_000)
    assert len(history) == 120
    assert list(history.columns) == ["t", "o", "h", "l", "c", "v"]
    assert history["t"].is_monotonic_increasing
    assert feed.last_bar_price("XAUUSD") == pytest.approx(float(history["c"].iloc[-1]))


def test_ticks_stay_inside_the_current_bar():
    feed = feed_for()
    for _ in range(feed.ticks_per_bar * 5):
        tick = feed.tick()["XAUUSD"]
        state = feed.state_of("XAUUSD")
        bar = state.bar
        if bar is None:            # the tick just closed a bar
            continue
        assert bar["l"] - 1e-9 <= tick.last <= bar["h"] + 1e-9, (tick, bar)
        assert tick.bid < tick.ask
        assert tick.spread_points >= 1.0


def test_clock_advances_and_bars_close():
    feed = feed_for(warmup=100)
    start_history = len(feed.warm_history("XAUUSD", 10_000))
    start_time = feed.end_time
    for _ in range(feed.ticks_per_bar):
        feed.tick()
        feed.advance_clock()
    assert feed.end_time > start_time
    assert len(feed.warm_history("XAUUSD", 10_000)) == start_history + 1
    assert feed.state_of("XAUUSD").index == 101


def test_feed_stops_at_the_end_instead_of_inventing_bars():
    feed = feed_for(n=200, warmup=150)
    guard = 0
    while not feed.exhausted and guard < 100_000:
        feed.tick()
        feed.advance_clock()
        guard += 1
    assert feed.exhausted, "the feed must run out when the file does"
    frozen_time = feed.end_time
    frozen_tick = feed.tick()["XAUUSD"]
    feed.advance_clock()
    assert feed.end_time == frozen_time, "a stopped feed must not keep moving the clock"
    again = feed.tick()["XAUUSD"]
    assert again.t == frozen_tick.t and again.last == frozen_tick.last
    status = feed.describe()
    assert status["exhausted"] is True
    assert status["symbols"]["XAUUSD"]["progress"] == pytest.approx(1.0)


def test_status_reports_progress_and_the_range_of_the_file():
    feed = feed_for(n=400, warmup=200)
    status = feed.describe()
    sym = status["symbols"]["XAUUSD"]
    assert status["mode"] == "replay"
    assert sym["bars_total"] == 400
    assert sym["bars_replayed"] == 0
    assert sym["from"].endswith("+00:00") and sym["to"].endswith("+00:00")
    for _ in range(feed.ticks_per_bar * 2):
        feed.tick()
        feed.advance_clock()
    assert feed.describe()["symbols"]["XAUUSD"]["bars_replayed"] == 2


def test_too_little_history_is_an_error_not_a_stub():
    with pytest.raises(ReplayError, match="not enough"):
        ReplayFeed({"XAUUSD": frame(50)}, SYMBOLS, warmup_bars=900)


def test_missing_columns_are_rejected():
    broken = frame(300).drop(columns=["h"])
    with pytest.raises(ReplayError, match="missing"):
        ReplayFeed({"XAUUSD": broken}, SYMBOLS, warmup_bars=100)


def test_two_feeds_with_the_same_seed_tick_identically():
    a, b = feed_for(warmup=100), feed_for(warmup=100)
    seq_a = [a.tick()["XAUUSD"].last for _ in range(a.ticks_per_bar * 3)]
    seq_b = [b.tick()["XAUUSD"].last for _ in range(b.ticks_per_bar * 3)]
    assert seq_a == seq_b


# ------------------------------------------------------------------- wiring
def _dataset(tmp_path, bars: int = 1000) -> None:
    df = frame(bars)
    csv = tmp_path / "src.csv"
    df.to_csv(csv, index=False)
    import_candles(csv, "XAUUSD", tmp_path / "datasets", tz="UTC")


def test_build_feed_uses_the_imported_data_when_asked(tmp_path, settings, monkeypatch):
    _dataset(tmp_path)
    monkeypatch.setitem(settings.paths, "datasets", tmp_path / "datasets")
    monkeypatch.setitem(settings.market_data, "feed_mode", "replay")
    monkeypatch.setitem(settings.market_data, "replay",
                        {"dataset_dir": str(tmp_path / "datasets"), "warmup_bars": 300})
    feed, mode, note = build_feed(settings, SYMBOLS)
    assert mode == "replay" and note is None
    assert isinstance(feed, ReplayFeed)
    assert len(feed.warm_history("XAUUSD", 10_000)) == 300


def test_build_feed_falls_back_loudly_when_replay_cannot_start(tmp_path, settings, monkeypatch):
    monkeypatch.setitem(settings.paths, "datasets", tmp_path / "empty")
    monkeypatch.setitem(settings.market_data, "feed_mode", "replay")
    monkeypatch.setitem(settings.market_data, "replay",
                        {"dataset_dir": str(tmp_path / "empty"), "warmup_bars": 300})
    feed, mode, note = build_feed(settings, SYMBOLS)
    assert mode == "simulate"
    assert note and "replay requested but unavailable" in note
    assert hasattr(feed, "warm_history") and not isinstance(feed, ReplayFeed)


def test_default_config_still_simulates(settings):
    feed, mode, note = build_feed(settings, SYMBOLS)
    assert mode == "simulate" and note is None


# ------------------------------------------------- what the UI is told about the feed
def test_market_candles_honour_the_requested_limit(runtime):
    """A cached 600-bar frame must not be shipped to a caller that asked for 20."""
    runtime.market.candles("XAUUSD", "M5", 600)
    df = runtime.market.candles("XAUUSD", "M5", 20)
    assert len(df) == 20


def test_data_quality_reports_the_real_feed_source(runtime):
    original = getattr(runtime.market, "feed_mode", None)
    runtime.market.feed_mode = "replay"
    try:
        quality = runtime.market.data_quality("XAUUSD")
        assert quality["feed"] == "replay"
    finally:
        runtime.market.feed_mode = original


def test_health_does_not_call_a_past_dated_feed_stale(runtime):
    """Replayed bars sit in the past; the heartbeat is the wall clock, not virtual time."""
    import time as _time

    runtime.last_tick_wall = _time.time()
    assert runtime.health()["services"]["feed"] == "ok"
    runtime.last_tick_wall = _time.time() - 60
    assert runtime.health()["services"]["feed"] == "stale"
    runtime.last_tick_wall = _time.time()
