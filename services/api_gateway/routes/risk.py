from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.api_gateway.deps import current_user, get_runtime
from services.api_gateway.state import TradingRuntime
from services.risk_engine.planner import points_calculator

router = APIRouter(prefix="/api/risk", tags=["risk"])


class RiskUpdate(BaseModel):
    limits: dict | None = None
    full_auto_enabled: bool | None = None


class KillSwitchRequest(BaseModel):
    reason: str = "manual emergency stop"
    flatten: bool = False


@router.get("/settings")
def settings_view(runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    return {
        "settings": runtime.risk.settings_view().model_dump(),
        "limits": runtime.risk.limits().model_dump(),
        "state": runtime.risk_state().model_dump(),
        "management": runtime.settings.risk_cfg().get("management", {}),
        "stops": runtime.settings.risk_cfg().get("stops", {}),
        "targets": runtime.settings.risk_cfg().get("targets", {}),
        "full_auto": {
            "enabled": bool(runtime.db.kv_get("full_auto_enabled", False)),
            "allowed_by_env": bool(runtime.settings.security.get("allow_full_auto")),
            "requirements": ["demo account", "score >= 85", "calibrated model approved",
                             "TP-before-SL probability >= 55%"],
        },
    }


@router.put("/settings")
def update(payload: RiskUpdate, runtime: TradingRuntime = Depends(get_runtime),
           user=Depends(current_user)):
    if payload.limits:
        runtime.risk.update_limits(payload.limits, actor=user["email"])
    if payload.full_auto_enabled is not None:
        if payload.full_auto_enabled and not runtime.settings.security.get("allow_full_auto"):
            raise HTTPException(status_code=400,
                                detail="NO7_ALLOW_FULL_AUTO is false in the environment — full auto is locked")
        runtime.db.kv_set("full_auto_enabled", bool(payload.full_auto_enabled))
        runtime.db.audit(user["email"], "risk.full_auto", {"enabled": payload.full_auto_enabled})
    return {"ok": True, "limits": runtime.risk.limits().model_dump(),
            "full_auto_enabled": bool(runtime.db.kv_get("full_auto_enabled", False))}


@router.post("/kill-switch")
def kill_engage(payload: KillSwitchRequest, runtime: TradingRuntime = Depends(get_runtime),
                user=Depends(current_user)):
    runtime.risk.engage_kill_switch(payload.reason)
    result = runtime.close_all() if payload.flatten else None
    return {"ok": True, "kill_switch": True, "flattened": result}


@router.delete("/kill-switch")
def kill_reset(runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    runtime.risk.reset_kill_switch(user["email"])
    return {"ok": True, "kill_switch": False}


@router.get("/calculator")
def calculator(symbol: str = "XAUUSD", points: float = 750, lot: float = 0.01,
               balance: float | None = None, risk_pct: float | None = None,
               sl_points: float | None = None,
               runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    spec = runtime.adapter.symbol_spec(symbol)
    out = {"points": points_calculator(spec, points, lot), "spec": spec.model_dump()}
    if balance is not None and risk_pct is not None and sl_points:
        out["lot_for_risk"] = runtime.planner.lot_for_risk(spec, balance, risk_pct, sl_points)
    out["disclaimer"] = ("Uses the symbol's actual point / tick size / contract size from the connected "
                         "account. Excludes spread, commission and swap.")
    return out
