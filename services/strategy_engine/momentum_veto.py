"""Experimental three-TF Stochastic veto PREVIEW, never an order authorization.

Activation requires real-data out-of-sample ablation and operator approval.
This module deliberately has no path to ExecutionGateway or StrategyEngine gate.
"""
from __future__ import annotations

from packages.shared_schemas.models import Direction, StochasticReading


def preview_stochastic_veto(readings: list[StochasticReading], direction: Direction) -> dict:
    expected = ("M5", "M15", "H1")
    by_tf = {reading.timeframe: reading for reading in readings}
    required = "bullish" if direction == Direction.up else "bearish" if direction == Direction.down else None
    blockers = []
    if required is None:
        blockers.append("no directional candidate")
    for tf in expected:
        reading = by_tf.get(tf)
        if reading is None or not reading.fresh or reading.k is None or reading.d is None:
            blockers.append(f"{tf}: confirmed momentum unavailable or stale")
        elif reading.direction != required:
            blockers.append(f"{tf}: momentum {reading.direction} conflicts with {required}")
    return {"would_block": bool(blockers), "reasons": blockers,
            "observed_timeframes": list(expected), "activated": False,
            "execution_effect": "none", "requires_real_oos_ablation": True}
