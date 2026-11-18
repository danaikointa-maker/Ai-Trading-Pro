"""Read-only chart annotations from the displayed source's closed candles."""
from __future__ import annotations

import json
from functools import lru_cache
from types import SimpleNamespace

import numpy as np
import pandas as pd

from packages.indicators import core as ta
from packages.indicators.pipeline import enrich
from packages.market_structure.structure import detect_events, find_swings
from packages.strategy_rules.flip_readings import confirmed_flip_readings
from packages.strategy_rules.retracement import confirmed_fibonacci_band
from packages.strategy_rules.zones import ZoneEngineConfig, build_zones
from services.strategy_engine.analysis import _round_step


@lru_cache(maxsize=32)
def closed_chart_overlays(bars_json: str, spec_json: str, config_json: str, timeframe: str) -> dict:
    # Cache inputs contain only completed OHLCV bars: changes to the live quote
    # do not rerun the zone detectors, while a corrected closed bar invalidates it.
    frame = pd.DataFrame(json.loads(bars_json))
    empty = {"available": False, "supports": [], "resistances": [], "structure": [],
             "sr_flips": [], "fibonacci_band": None, "closed_only": True, "timeframe": timeframe}
    if len(frame) < 30:
        return {**empty, "reason": "ต้องมีแท่งปิดอย่างน้อย 30 แท่งเพื่อวิเคราะห์เครื่องมือกราฟ"}
    required = ["t", "o", "h", "l", "c", "v"]
    if not set(required).issubset(frame) or not np.isfinite(frame[required].to_numpy(float)).all():
        return {**empty, "reason": "ข้อมูลแท่งไม่ครบหรือมีค่าที่ใช้คำนวณไม่ได้"}
    if not ((frame.l <= frame.o) & (frame.o <= frame.h) & (frame.l <= frame.c) & (frame.c <= frame.h)).all():
        return {**empty, "reason": "ข้อมูล OHLC ไม่ถูกต้อง"}
    spec = SimpleNamespace(**json.loads(spec_json))
    cfg = ZoneEngineConfig(**json.loads(config_json))
    frame = enrich(frame)
    swings = find_swings(frame)
    events = detect_events(frame, swings)
    flips = confirmed_flip_readings(frame, swings, spec.point)
    fib = confirmed_fibonacci_band(frame, swings, spec.digits)
    price = float(frame.c.iloc[-1])
    last = frame.iloc[-1]
    vp = ta.volume_profile(frame.h.tail(240), frame.l.tail(240), frame.c.tail(240), frame.v.tail(240), bins=50)
    zones, _, _ = build_zones(frame, spec, price, swings, float(last.atr), {},
                              float(last.vwap), float(last.ema50), float(last.ema200), vp, cfg,
                              round_step=_round_step(price))
    confirmed = sorted((z for z in zones if z.status.value == "confirmed"), key=lambda z: z.distance_atr)
    return {**empty, "available": True, "reason": "", "as_of": int(last.t), "bars": len(frame),
            "supports": [z.model_dump() for z in confirmed if z.kind.value == "support"][:5],
            "resistances": [z.model_dump() for z in confirmed if z.kind.value == "resistance"][:5],
            "structure": [event.model_dump() for event in events[-12:]],
            "sr_flips": [{**event.model_dump(), "timeframe": timeframe} for event in flips],
            "fibonacci_band": {**fib.model_dump(), "timeframe": timeframe} if fib else None}
