from __future__ import annotations

import copy
import math

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from packages.shared_schemas.models import Direction, TradeMode
from services.api_gateway.deps import current_user, get_runtime
from services.api_gateway.roles import ADMIN, at_least
from services.api_gateway.state import TradingRuntime
from services.risk_engine.planner import (
    break_even_win_rate_calculator,
    build_plan_inputs,
    drawdown_recovery_calculator,
    point_tick_converter,
    points_calculator,
    position_size_calculator,
    profit_loss_calculator,
    risk_reward_calculator,
    trading_costs_calculator,
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
               gross_reward: float | None = None, gross_loss: float | None = None,
               estimated_cost: float | None = None,
               price: float | None = None, holding_nights: int = 0,
               triple_swap_nights: int = 0,
               price_delta: float | None = None,
               manual_equity: float | None = None,
               stop_mode: str = "atr_structure",
               fixed_sl_points: float | None = None,
               atr_multiplier: float = 1.5,
               structure_buffer_atr: float = 0.2,
               swing_lookback_bars: int = 10,
               target_mode: str = "adaptive",
               target_r: float = 2.0,
               runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    """Read-only calculators; only symbol metadata is sourced from the selected market feed."""
    allowed_tools = {None, "points", "size", "position_size", "risk_reward", "drawdown",
                     "point_tick", "profit_loss", "break_even", "trading_costs", "auto_sl_tp"}
    if tool not in allowed_tools:
        raise HTTPException(status_code=422, detail="unsupported calculator tool")

    if tool == "auto_sl_tp":
        # This is a manual calculator preview only. It consumes a fresh closed-M5
        # analysis and the shared planner; it never reads broker equity or calls
        # the execution gateway.
        normalized_side = (side or "").strip().upper()
        valid_numbers = (manual_equity, entry, risk_pct, atr_multiplier,
                         structure_buffer_atr)
        valid_numbers = all(value is not None and math.isfinite(float(value))
                            for value in valid_numbers)
        valid_fixed = (fixed_sl_points is None or
                       (math.isfinite(fixed_sl_points) and fixed_sl_points > 0))
        if (not valid_numbers or manual_equity <= 0 or entry <= 0
                or not 0 < risk_pct <= 100 or atr_multiplier <= 0
                or structure_buffer_atr < 0 or not valid_fixed
                or normalized_side not in {"BUY", "SELL"}
                or stop_mode not in {"fixed", "atr", "structure", "atr_structure"}
                or (stop_mode == "fixed" and fixed_sl_points is None)
                or not 1 <= swing_lookback_bars <= 100
                or target_mode not in {"adaptive", "fixed", "single_r"}
                or (target_mode == "single_r" and
                    (not math.isfinite(target_r) or not 0 < target_r <= 10))):
            result = {"status": "invalid_input", "source": "manual_sandbox",
                      "plan": None, "blockers": ["กรอกทุนจำลอง ราคาเข้า ความเสี่ยง และตัวเลือก SL/TP ให้ถูกต้อง"],
                      "execution_approved": False}
            return {"tool": tool, "result": result, "spec": None, "provenance": None,
                    "disclaimer": "ตัวอย่างแผนอ่านอย่างเดียว ไม่ได้อนุมัติหรือส่งคำสั่งซื้อขาย"}

        try:
            ctx = runtime.analysis.snapshot(symbol)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        snap = ctx.snapshot
        quality = snap.data_quality or {}
        bars = ctx.frames.get("M5")
        unavailable_reason = None
        if quality.get("ok") is not True:
            unavailable_reason = quality.get("reason") or "market quote freshness check failed"
        elif not snap.indicators.atr14_valid or snap.indicators.atr_points <= 0:
            unavailable_reason = "closed M5 ATR(14) is unavailable"
        elif bars is None or len(bars) < 14:
            unavailable_reason = "not enough closed M5 bars"
        elif not snap.spec.spec_complete or snap.spec.sizing_blocked:
            unavailable_reason = "complete broker symbol specification and account-currency valuation are required"

        closed_bar_open = int(bars["t"].iloc[-1]) if bars is not None and len(bars) else None
        closed_bar_close = closed_bar_open + 300 if closed_bar_open is not None else None
        now = float(runtime.market.now())
        closed_age = now - closed_bar_close if closed_bar_close is not None else None
        max_closed_age = float(runtime.settings.risk_cfg().get("limits", {}).get(
            "data_staleness_seconds", 30)) + 300
        if (unavailable_reason is None and
                (closed_age is None or closed_age < -2 or closed_age > max_closed_age)):
            unavailable_reason = "latest closed M5 candle is stale or from the future"
        spread_points = quality.get("spread_points")
        if unavailable_reason is None and (
                spread_points is None or not math.isfinite(float(spread_points))
                or float(spread_points) < 0):
            unavailable_reason = "fresh market spread is unavailable"

        provenance = {
            "market_feed": quality.get("feed"),
            "spec_source": snap.spec.source,
            "account_currency": snap.spec.account_currency,
            "entry_source": "manual",
            "equity_source": "manual_sandbox",
            "quote_staleness_seconds": quality.get("staleness_seconds"),
            "closed_m5_open_utc": closed_bar_open,
            "closed_m5_close_utc": closed_bar_close,
            "closed_m5_age_seconds": round(closed_age, 2) if closed_age is not None else None,
        }
        if unavailable_reason:
            result = {"status": "unavailable", "source": "manual_sandbox", "plan": None,
                      "blockers": [unavailable_reason], "execution_approved": False}
        else:
            risk_cfg = copy.deepcopy(runtime.settings.risk_cfg())
            risk_cfg.setdefault("plan_options", {}).update({
                "sl_policy": stop_mode,
                "sl_atr_multiplier": atr_multiplier,
                "sl_structure_buffer_atr": structure_buffer_atr,
                "swing_lookback_bars": swing_lookback_bars,
                "single_target_r": target_r if target_mode == "single_r" else None,
                "directional_tick_rounding": True,
            })
            if stop_mode == "fixed":
                risk_cfg["plan_options"]["fixed_sl_points"] = fixed_sl_points
            effective = runtime.risk.settings_view().model_copy(deep=True)
            limits = effective.limits.model_copy(update={"risk_per_trade_pct": risk_pct})
            effective = effective.model_copy(update={
                "limits": limits,
                "targets_mode": "fixed" if target_mode == "single_r" else target_mode,
            })
            direction = Direction.up if normalized_side == "BUY" else Direction.down
            swings = [{"kind": swing.kind, "price": swing.price, "idx": swing.idx}
                      for swing in ctx.swings if swing.confirmed]
            plan_inputs = build_plan_inputs(
                risk_cfg=risk_cfg, effective=effective,
                direction=direction, entry=entry, spec=snap.spec,
                atr_points=float(snap.indicators.atr_points), equity=manual_equity,
                spread_points=float(spread_points), supports=snap.supports,
                resistances=snap.resistances, swings=swings,
                m5_bar_count=len(bars),
            )
            if stop_mode == "fixed":
                plan_inputs.fixed_sl_points = fixed_sl_points
            plan_result = runtime.planner.build(plan_inputs)
            result = {
                "status": "ready" if plan_result.plan is not None else "blocked",
                "source": "manual_sandbox",
                "plan": plan_result.plan.model_dump(mode="json") if plan_result.plan else None,
                "blockers": plan_result.blockers,
                "blocker_codes": plan_result.blocker_codes,
                "notes": plan_result.notes,
                "risk_budget": manual_equity * risk_pct / 100,
                "risk_pct": risk_pct,
                "atr_points": float(snap.indicators.atr_points),
                "execution_approved": False,
            }
        return {
            "tool": tool, "result": result, "spec": snap.spec.model_dump(),
            "provenance": provenance,
            "disclaimer": ("แผนคำนวณจากทุนและราคาเข้าที่กรอก โดยใช้ข้อมูล M5 ปิดแล้วและสเปกตลาดที่ตรวจ freshness; "
                           "เป็นตัวอย่างอ่านอย่างเดียว ไม่ได้ผ่านการอนุมัติคำสั่ง ไม่อ่านยอดบัญชี และไม่ส่งคำสั่ง"),
        }

    # Use the same selected market-data specification as chart and points math.
    # This includes a fresh, allowlisted MT5 Demo publisher spec when configured.
    spec = runtime.market.spec(symbol)
    provenance = {"market_feed": runtime.market.effective_mode,
                  "spec_source": spec.source, "rate_source": spec.rate_source,
                  "account_currency": spec.account_currency,
                  "spec_complete": spec.spec_complete}
    disclaimer = ("ผลลัพธ์เป็นแบบจำลองจากข้อมูลที่กรอกและสเปกที่ระบุ ไม่ใช่คำสั่งซื้อขาย; "
                  "ค่ากำไร/ขาดทุนหักเฉพาะ spread ทั่วไปและ commission ไม่รวม slippage/swap")

    if tool in {"risk_reward", "drawdown", "point_tick", "profit_loss", "break_even", "trading_costs"}:
        if tool == "risk_reward":
            result = risk_reward_calculator(spec, entry, stop_loss, take_profit, side, lot)
        elif tool == "drawdown":
            result = drawdown_recovery_calculator(current_equity, peak_equity)
        elif tool == "point_tick":
            result = point_tick_converter(spec, price_delta)
        elif tool == "break_even":
            result = break_even_win_rate_calculator(gross_reward, gross_loss, estimated_cost)
        elif tool == "trading_costs":
            result = trading_costs_calculator(spec, side, price, lot, holding_nights, triple_swap_nights)
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
