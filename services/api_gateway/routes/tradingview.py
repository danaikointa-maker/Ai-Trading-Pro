"""Disabled-by-default inbound adapter for read-only TradingView Lens evidence."""
from __future__ import annotations

import hmac
import json
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from integrations.tradingview.normalizer import normalize_lens_packet
from services.api_gateway.deps import current_user, get_runtime
from services.api_gateway.state import TradingRuntime

router = APIRouter(prefix="/api/integrations/tradingview", tags=["tradingview"])
MAX_BODY_BYTES = 65536
_NO7_TIMEFRAMES = {
    "1": "M1", "3": "M3", "5": "M5", "15": "M15", "30": "M30",
    "60": "H1", "120": "H2", "240": "H4", "1440": "D1", "10080": "W1",
    "D": "D1", "W": "W1",
}
_TV_TIMEFRAMES = {value: key for key, value in _NO7_TIMEFRAMES.items()}


def _timeframe_seconds(value: str) -> int:
    if value == "D":
        return 86400
    if value == "W":
        return 604800
    if value.isdigit() and int(value) > 0:
        return int(value) * 60
    raise HTTPException(status_code=422, detail="unsupported TradingView timeframe")


def _max_age_seconds(timeframe: str) -> int:
    return max(300, min(2 * _timeframe_seconds(timeframe), 604800))


def _canonical_no7_timeframe(value: str) -> str:
    normalized = value.strip().upper()
    return _NO7_TIMEFRAMES.get(normalized, normalized)


async def _read_limited(request: Request) -> bytes:
    length = request.headers.get("content-length")
    if length:
        try:
            if int(length) > MAX_BODY_BYTES:
                raise HTTPException(status_code=413, detail="webhook payload is too large")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid content length") from exc
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="webhook payload is too large")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/ai-agent-lens", status_code=202)
async def ingest_lens(request: Request, runtime: TradingRuntime = Depends(get_runtime)):
    """Accept an authenticated packet into bounded shadow storage only."""
    if os.environ.get("NO7_TRADINGVIEW_ENABLED", "false").strip().lower() not in {"1", "true", "yes"}:
        raise HTTPException(status_code=503, detail="TradingView adapter is disabled")
    expected = os.environ.get("NO7_TRADINGVIEW_WEBHOOK_TOKEN", "")
    if len(expected) < 32:
        raise HTTPException(status_code=503, detail="TradingView adapter credential is not configured")
    if "application/json" not in request.headers.get("content-type", "").lower():
        raise HTTPException(status_code=415, detail="application/json required")

    body = await _read_limited(request)
    try:
        envelope = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="invalid JSON envelope") from exc
    if not isinstance(envelope, dict) or set(envelope) != {"token", "packet"}:
        raise HTTPException(status_code=422, detail="expected token and packet fields")
    supplied = envelope.get("token")
    if not isinstance(supplied, str) or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid TradingView credential")

    try:
        packet = envelope["packet"]
        if not isinstance(packet, dict):
            raise ValueError("packet must be an object")
        symbol_map = json.loads(os.environ.get("NO7_TRADINGVIEW_SYMBOL_MAP", "{}"))
        if not isinstance(symbol_map, dict):
            raise ValueError("symbol map must be an object")
        mapped_symbol = symbol_map.get(packet.get("symbol"))
        if not isinstance(mapped_symbol, str) or mapped_symbol not in runtime.market.symbols():
            raise ValueError("TradingView symbol has no configured No7 market mapping")
        evidence = normalize_lens_packet(packet, mapped_symbol=mapped_symbol,
                                         received_at=time.time())
        now = int(time.time())
        age = now - evidence.bar_close_utc
        max_age = _max_age_seconds(evidence.timeframe)
        if age < -10 or age > max_age:
            raise ValueError("TradingView candle close is future-dated or stale")
    except HTTPException:
        raise
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="invalid TradingView packet") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="invalid TradingView symbol map") from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    inserted = runtime.db.store_tradingview_evidence(evidence.model_dump(mode="json"))
    # Do not persist or echo the credential, raw packet, or Lens trade/risk levels.
    runtime.db.audit("tradingview-webhook", "tradingview.evidence",
                     {"hash": evidence.payload_sha256, "symbol": evidence.mapped_symbol,
                      "timeframe": evidence.timeframe, "inserted": inserted})
    return {"accepted": True, "duplicate": not inserted, "quality": "shadow_only",
            "source": evidence.source, "symbol": evidence.mapped_symbol,
            "timeframe": evidence.timeframe, "bar_close_utc": evidence.bar_close_utc}


@router.get("/ai-agent-lens/latest")
def latest_lens(symbol: str, timeframe: str, limit: int = 20,
                runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    """Read-only view of normalized Lens evidence; never a trade decision."""
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
    stored_timeframe = _TV_TIMEFRAMES.get(timeframe.upper(), timeframe.upper())
    rows = runtime.db.query(
        "SELECT payload FROM tradingview_evidence WHERE mapped_symbol=? AND timeframe=? "
        "ORDER BY bar_close_utc DESC LIMIT ?", (symbol, stored_timeframe, limit))
    evidence_rows = [json.loads(row["payload"]) for row in rows]
    no7_timeframe = _canonical_no7_timeframe(timeframe)
    for evidence in evidence_rows:
        age = int(time.time()) - int(evidence["bar_close_utc"])
        max_age = _max_age_seconds(evidence["timeframe"])
        evidence["freshness"] = {
            "status": "fresh" if 0 <= age <= max_age else "stale",
            "age_seconds": age,
            "max_age_seconds": max_age,
        }
        candidates = runtime.db.query(
            "SELECT payload FROM signals WHERE symbol=? AND t=?",
            (symbol, evidence["bar_close_utc"]))
        signal = None
        for candidate in candidates:
            if not candidate["payload"]:
                continue
            try:
                candidate_signal = json.loads(candidate["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            if (isinstance(candidate_signal, dict)
                    and _canonical_no7_timeframe(str(candidate_signal.get("timeframe", "")))
                    == no7_timeframe):
                signal = candidate_signal
                break
        if signal is not None:
            evidence["comparison"] = {
                "status": "exact_bar_match",
                "no7_action": signal.get("action"),
                "no7_score": signal.get("score"),
                "no7_status": signal.get("status"),
                "scores_are_separate": True,
            }
        else:
            evidence["comparison"] = {
                "status": "no_exact_no7_bar_match",
                "no7_action": None,
                "no7_score": None,
                "scores_are_separate": True,
            }
    return {"source": "tradingview_ai_agent_lens", "quality": "shadow_only",
            "evidence": evidence_rows}
