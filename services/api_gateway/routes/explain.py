from __future__ import annotations

import hashlib
import json
import math
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from integrations.no7_local_ai.client import No7LocalAI
from services.api_gateway.deps import current_user, get_runtime
from services.api_gateway.state import TradingRuntime
from services.strategy_engine.explainer import TradeExplainer

router = APIRouter(prefix="/api", tags=["explain"])


class ExplainRequest(BaseModel):
    question: str = "why buy?"
    symbol: str | None = None
    signal_id: str | None = None


def _research_observability(runtime: TradingRuntime, symbol: str) -> dict:
    """Expose only market-feed provenance needed to interpret research facts."""
    try:
        quote = runtime.market.latest_quote(symbol)
    except Exception:  # noqa: BLE001 - unavailable feed is still reportable
        quote = None
    try:
        clock = runtime.market.timestamp_metadata()
    except Exception:  # noqa: BLE001 - never let optional metadata break explain
        clock = {}

    usable_quote = quote if isinstance(quote, dict) else None
    tick = usable_quote.get("tick") if usable_quote is not None else None
    raw_source = usable_quote.get("source") if usable_quote is not None else None
    source = (raw_source if isinstance(raw_source, str)
              and raw_source in {"broker", "persisted", "mt5_demo_publisher"} else "unavailable")
    if usable_quote is None:
        status = "unavailable"
    elif usable_quote.get("stale") is True:
        status = "stale"
    elif usable_quote.get("stale") is not False or not isinstance(tick, dict) or not tick:
        status = "unavailable"
    elif source == "unavailable":
        status = "unavailable"
    else:
        status = "fresh"

    basis = clock.get("display_basis") if isinstance(clock, dict) else None
    basis = basis if isinstance(basis, str) and basis in {"utc", "broker_server"} else "unknown"
    raw_offset = clock.get("server_utc_offset_seconds") if isinstance(clock, dict) else None
    try:
        offset_value = float(raw_offset) if raw_offset is not None else None
        if (isinstance(raw_offset, bool) or offset_value is None or not math.isfinite(offset_value)
                or not offset_value.is_integer() or abs(offset_value) > 14 * 3600):
            offset = None
        else:
            offset = int(offset_value)
    except (TypeError, ValueError, OverflowError):
        offset = None
    try:
        raw_mode = str(runtime.market.effective_mode)
    except Exception:  # noqa: BLE001 - avoid leaking internal exception details
        raw_mode = "unknown"
    feed_mode = raw_mode if raw_mode in {
        "simulate", "simulated", "replay", "mt5", "mt5-live",
        "mt5_demo_publisher", "mt5_demo_publisher_stale",
    } else "unknown"
    return {
        "feed_mode": feed_mode,
        "quote_status": status,
        "quote_source": source,
        "display_basis": basis,
        "server_utc_offset_seconds": offset,
    }


@router.post("/explain")
def explain(payload: ExplainRequest, runtime: TradingRuntime = Depends(get_runtime),
            user=Depends(current_user)):
    symbol = payload.symbol or runtime.active_symbol
    signal = runtime.signals.get(symbol)
    if payload.signal_id:
        signal = runtime.plans.get(payload.signal_id, signal)
    snapshot = runtime.snapshot(symbol)
    forecast = runtime.cached_forecast(symbol)
    observability = _research_observability(runtime, symbol)
    explainer = TradeExplainer(No7LocalAI())
    result = explainer.explain(payload.question, signal, snapshot, forecast, observability)
    facts = explainer.fact_sheet(signal, snapshot, forecast, observability)
    officer_team = explainer.officer_team(facts, snapshot.server_time if snapshot else None)
    request_id = uuid.uuid4().hex
    officer_team["request_id"] = request_id
    output_hash = hashlib.sha256(json.dumps(
        officer_team["officers"], sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    workspace_id = str(getattr(runtime.db, "workspace_id", "unknown"))
    scope_seed = "\0".join((str(user.get("tenant_id") or "unassigned"), workspace_id,
                            str(snapshot.broker_id if snapshot else "unknown"), symbol))
    runtime_scope_ref = hashlib.sha256(scope_seed.encode("utf-8")).hexdigest()[:20]
    runtime.db.audit(user.get("email", "unknown"), "ai.trader_officer_brief", {
        "request_id": request_id,
        "runtime_scope_ref": runtime_scope_ref,
        "source_timestamp": snapshot.server_time if snapshot else None,
        "freshness": observability.get("quote_status", "unavailable"),
        "officer_set_version": officer_team["version"],
        "output_hash": output_hash,
        "safety_outcome": "read_only_no_execution_capability",
    })
    result["facts"] = facts
    result["officer_team"] = officer_team
    result["llm"] = No7LocalAI().describe()
    return result
