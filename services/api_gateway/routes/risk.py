from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from packages.shared_schemas.models import TradeMode
from services.api_gateway.deps import current_user, get_runtime
from services.api_gateway.roles import ADMIN, at_least
from services.api_gateway.state import TradingRuntime
from services.risk_engine.planner import (
    drawdown_recovery_calculator,
    point_tick_converter,
    points_calculator,
    position_size_calculator,
    profit_loss_calculator,
    risk_reward_calculator,
)

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
    # Changing the deployment-level Full Auto posture is an admin-only action.
    # Check this before applying any other fields so a mixed payload is atomic
    # with respect to authorization.
    if payload.full_auto_enabled is not None and not at_least(user.get("role"), ADMIN):
        raise HTTPException(status_code=403,
                            detail="changing the Full Auto security flag requires admin role")
    if (payload.full_auto_enabled is True
            and not runtime.settings.security.get("allow_full_auto")):
        raise HTTPException(status_code=400,
                            detail="NO7_ALLOW_FULL_AUTO is false in the environment — full auto is locked")
    if payload.limits:
        runtime.risk.update_limits(payload.limits, actor=user["email"])
    if payload.full_auto_enabled is not None:
        runtime.db.kv_set("full_auto_enabled", bool(payload.full_auto_enabled))
        runtime.db.audit(user["email"], "risk.full_auto", {"enabled": payload.full_auto_enabled})
        if not payload.full_auto_enabled and runtime.mode == TradeMode.full_auto:
            runtime.set_mode(TradeMode.manual, actor=user["email"])
    return {"ok": True, "limits": runtime.risk.limits().model_dump(),
            "full_auto_enabled": bool(runtime.db.kv_get("full_auto_enabled", False)),
            "mode": runtime.mode.value}


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


@router.post("/loss-streak/release")
def loss_streak_release(runtime: TradingRuntime = Depends(get_runtime),
                        user=Depends(current_user)):
    """Lift the hard stop that three consecutive losses put in place.

    The rule is "stopped until a winning trade", and no winning trade can be
    opened from inside the app while the stop holds — every order path runs
    through the same gate. This is the operator's way out. It writes a
    watermark instead of editing the ledger: the losing trades keep their P&L,
    and the release is audited.
    """
    released_at = runtime.risk.release_losing_streak(user["email"])
    state = runtime.risk_state()
    return {"ok": True, "released_at": released_at,
            "consecutive_losses": state.consecutive_losses,
            "note": "losses closed before this moment no longer count toward the streak"}


@router.get("/calculator")
def calculator(symbol: str = "XAUUSD", points: float = 750, lot: float = 0.01,
               balance: float | None = None, risk_pct: float | None = None,
               sl_points: float | None = None,
               tool: str | None = None, entry: float | None = None,
               stop_loss: float | None = None, take_profit: float | None = None,
               side: str | None = None, exit_price: float | None = None,
               current_equity: float | None = None, peak_equity: float | None = None,
               price_delta: float | None = None,
               runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    """Read-only calculators; only symbol metadata is sourced from the selected market feed."""
    allowed_tools = {None, "points", "size", "position_size", "risk_reward", "drawdown",
                     "point_tick", "profit_loss"}
    if tool not in allowed_tools:
        raise HTTPException(status_code=422, detail="unsupported calculator tool")
    # Use the same selected market-data specification as chart and points math.
    # This includes a fresh, allowlisted MT5 Demo publisher spec when configured.
    spec = runtime.market.spec(symbol)
    provenance = {"market_feed": runtime.market.effective_mode,
                  "spec_source": spec.source, "rate_source": spec.rate_source,
                  "account_currency": spec.account_currency,
                  "spec_complete": spec.spec_complete}
    disclaimer = ("ผลลัพธ์เป็นแบบจำลองจากข้อมูลที่กรอกและสเปกที่ระบุ ไม่ใช่คำสั่งซื้อขาย; "
                  "ค่ากำไร/ขาดทุนหักเฉพาะ spread ทั่วไปและ commission ไม่รวม slippage/swap")

    if tool in {"risk_reward", "drawdown", "point_tick", "profit_loss"}:
        if tool == "risk_reward":
            result = risk_reward_calculator(spec, entry, stop_loss, take_profit, side, lot)
        elif tool == "drawdown":
            result = drawdown_recovery_calculator(current_equity, peak_equity)
        elif tool == "point_tick":
            result = point_tick_converter(spec, price_delta)
        else:
            result = profit_loss_calculator(spec, entry, exit_price, side, lot)
        return {"tool": tool, "result": result, "spec": spec.model_dump(),
                "provenance": provenance, "disclaimer": disclaimer}

    out = {"points": points_calculator(spec, points, lot), "spec": spec.model_dump(),
           "provenance": provenance}
    sizing_inputs = (balance, risk_pct, sl_points)
    if tool in {"size", "position_size"} and any(value is None for value in sizing_inputs):
        raise HTTPException(status_code=422, detail="size tool requires balance, risk_pct, and sl_points")
    if any(value is not None for value in sizing_inputs):
        if not all(value is not None for value in sizing_inputs):
            raise HTTPException(status_code=422,
                                detail="balance, risk_pct, and sl_points must be supplied together")
        size = position_size_calculator(spec, balance, risk_pct, sl_points)
        # This input is a manual sandbox value; the route never reads account equity.
        out["position_size"] = {**size, "source": "manual_sandbox"}
        out["lot_for_risk"] = size["lot"]
    out["disclaimer"] = disclaimer
    return out
