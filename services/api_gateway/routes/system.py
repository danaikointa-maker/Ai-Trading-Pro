from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from packages.shared_schemas.settings import get_settings
from services.api_gateway.deps import current_user, get_runtime
from services.api_gateway.state import TradingRuntime

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
def health(runtime: TradingRuntime = Depends(get_runtime)):
    return runtime.health()


@router.get("/config")
def config(runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    settings = get_settings()
    return {
        "public": settings.as_public_dict(),
        "broker_default": runtime.adapter.id,
        "symbols": runtime.symbols(),
        "active_symbol": runtime.active_symbol,
        "mode": runtime.mode.value,
        "strategies": settings.strategy_cfg().get("strategies", []),
        "scoring": settings.strategy_cfg().get("scoring", {}),
        "zone_engine": settings.strategy_cfg().get("zone_engine", {}),
        "ai_horizons": settings.ai.get("horizons_minutes", []),
        "security": {
            "require_auth": settings.security.get("require_auth", True),
            "allow_full_auto": bool(settings.security.get("allow_full_auto")),
            "full_auto_enabled": bool(runtime.db.kv_get("full_auto_enabled", False)),
        },
        "server_time": time.time(),
    }


class SymbolRequest(BaseModel):
    symbol: str


@router.post("/symbol")
def switch_symbol(payload: SymbolRequest, runtime: TradingRuntime = Depends(get_runtime),
                  user=Depends(current_user)):
    if payload.symbol not in runtime.symbols():
        raise HTTPException(status_code=400, detail=f"unknown symbol {payload.symbol}")
    runtime.switch_symbol(payload.symbol)
    return {"ok": True, "active_symbol": runtime.active_symbol}


@router.get("/alerts")
def alerts(limit: int = Query(50, ge=1, le=200), runtime: TradingRuntime = Depends(get_runtime),
           user=Depends(current_user)):
    return {"alerts": runtime.alerts(limit)}


@router.post("/alerts/test")
def test_alert_channel(runtime: TradingRuntime = Depends(get_runtime),
                       user=Depends(current_user)):
    """Send a real message through every configured external channel.

    Without this the only way to learn that a Telegram token is wrong was to wait
    for something worth alerting about and then notice nothing arrived.
    """
    result = runtime.notifier.send_test()
    runtime.db.audit(user["email"], "alerts.test", {"ok": result["ok"]})
    return result


@router.get("/notify")
def notify_status(runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    return runtime.notifier.status()


@router.get("/audit")
def audit(limit: int = Query(100, ge=1, le=500), runtime: TradingRuntime = Depends(get_runtime),
          user=Depends(current_user)):
    rows = runtime.db.query("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))
    return {"audit": [dict(r) for r in rows]}


@router.get("/errors")
def errors(runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    return {"errors": list(runtime.errors)}
