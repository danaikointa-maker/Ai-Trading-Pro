from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query

from services.api_gateway.deps import current_user, get_runtime
from services.api_gateway.state import TradingRuntime

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("/latest")
def latest(symbol: str | None = None, runtime: TradingRuntime = Depends(get_runtime),
           user=Depends(current_user)):
    sym = symbol or runtime.active_symbol
    signal = runtime.signals.get(sym)
    with_lock = runtime.lock
    with with_lock:
        gate = runtime.gates.get(sym)
        forecast = runtime.forecasts.get(sym)
    return {"signal": signal.model_dump() if signal else None,
            "gate": gate,
            "forecast": forecast.model_dump() if forecast else None,
            "mode": runtime.mode.value}


@router.get("/history")
def history(limit: int = Query(30, ge=1, le=200), symbol: str | None = None,
            runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    rows = runtime.db.query(
        "SELECT payload FROM signals ORDER BY t DESC LIMIT ?", (limit * 4,))
    out = []
    for row in rows:
        try:
            data = json.loads(row["payload"])
        except json.JSONDecodeError:
            continue
        if symbol and data.get("symbol") != symbol:
            continue
        out.append({"id": data.get("id"), "t": data.get("t"), "symbol": data.get("symbol"),
                    "action": data.get("action"), "status": data.get("status"),
                    "score": data.get("score"), "strategy": data.get("strategy"),
                    "plan": data.get("plan"), "blockers": data.get("blockers", [])[:4]})
        if len(out) >= limit:
            break
    return {"signals": out}


@router.post("/{signal_id}/approve")
def approve(signal_id: str, runtime: TradingRuntime = Depends(get_runtime),
            user=Depends(current_user)):
    result = runtime.execute_signal(signal_id, actor=user["email"])
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result)
    return result


@router.post("/{signal_id}/reject")
def reject(signal_id: str, payload: dict | None = None,
           runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    reason = (payload or {}).get("reason", "rejected by user")
    return runtime.reject_signal(signal_id, reason)
