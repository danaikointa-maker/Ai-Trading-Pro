"""Normalize AI Agent Lens packets to source-attributed, non-executable evidence."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from packages.shared_schemas.tradingview import (
    ExternalAnalysisEvidence,
    TradingViewLensPacket,
)

TIMEFRAME_TO_NO7 = {
    "1": "M1", "3": "M3", "5": "M5", "15": "M15", "30": "M30",
    "60": "H1", "120": "H2", "240": "H4", "1440": "D1", "10080": "W1",
    "D": "D1", "W": "W1",
}


def canonical_no7_timeframe(value: str) -> str:
    """Normalize Lens aliases and No7 labels to one timeframe spelling."""
    normalized = value.strip().upper()
    return TIMEFRAME_TO_NO7.get(normalized, normalized)


def normalize_lens_packet(raw: dict[str, Any], *, mapped_symbol: str,
                          received_at: float | None = None) -> ExternalAnalysisEvidence:
    """Validate and project a Lens packet; deliberately drops its trade/risk map."""
    if not mapped_symbol or mapped_symbol.strip() != mapped_symbol:
        raise ValueError("an explicit canonical symbol mapping is required")
    packet = TradingViewLensPacket.model_validate(raw)
    canonical = json.dumps(packet.model_dump(mode="json", by_alias=True), sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    received = int(time.time() if received_at is None else received_at)
    # Only descriptive feature groups are carried forward. Lens trade levels are
    # intentionally omitted because they are not No7 plans or broker instructions.
    features = {
        "trend": packet.trend.model_dump(exclude_none=True),
        "momentum": packet.momentum.model_dump(exclude_none=True),
        "strength": packet.strength.model_dump(exclude_none=True),
        "volatility": packet.volatility.model_dump(exclude_none=True),
        "volume": packet.volume.model_dump(exclude_none=True),
        "structure": packet.structure.model_dump(exclude_none=True),
        "levels": packet.levels.model_dump(exclude_none=True),
    }
    return ExternalAnalysisEvidence(
        source_schema=packet.schema_version,
        event=packet.event,
        source_symbol=packet.symbol,
        mapped_symbol=mapped_symbol,
        timeframe=packet.timeframe,
        bar_close_utc=int(packet.time.timestamp()),
        received_at_utc=received,
        payload_sha256=digest,
        regime=packet.regime,
        candle=packet.candle,
        long_score=packet.scores.long,
        short_score=packet.scores.short,
        score_threshold=packet.scores.threshold,
        features=features,
    )
