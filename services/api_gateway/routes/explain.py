from __future__ import annotations

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


@router.post("/explain")
def explain(payload: ExplainRequest, runtime: TradingRuntime = Depends(get_runtime),
            user=Depends(current_user)):
    symbol = payload.symbol or runtime.active_symbol
    signal = runtime.signals.get(symbol)
    if payload.signal_id:
        signal = runtime.plans.get(payload.signal_id, signal)
    snapshot = runtime.snapshot(symbol)
    forecast = runtime.cached_forecast(symbol)
    explainer = TradeExplainer(No7LocalAI())
    result = explainer.explain(payload.question, signal, snapshot, forecast)
    result["facts"] = explainer.fact_sheet(signal, snapshot, forecast)
    result["llm"] = No7LocalAI().describe()
    return result
