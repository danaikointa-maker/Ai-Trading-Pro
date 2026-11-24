from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from integrations.brokers.fx import resolve_quote_rate
from packages.shared_schemas.models import Direction, TradeMode, TradeRecord
from services.api_gateway.deps import current_user, get_runtime
from services.api_gateway.roles import ADMIN, at_least
from services.api_gateway.state import TradingRuntime
from services.risk_engine.planner import (
    break_even_win_rate_calculator,
    build_plan_inputs,
    capital_growth_calculator,
    currency_conversion_calculator,
    drawdown_recovery_calculator,
    point_tick_converter,
    points_calculator,
    position_size_calculator,
    profit_loss_calculator,
    risk_reward_calculator,
    scenario_simulator,
    trading_costs_calculator,
)
from services.strategy_engine.confirmation import confirmation_movement_points

router = APIRouter(prefix="/api/risk", tags=["risk"])


class RiskUpdate(BaseModel):
    limits: dict | None = None
    full_auto_enabled: bool | None = None


class KillSwitchRequest(BaseModel):
    reason: str = "manual emergency stop"
    flatten: bool = False


class CalculatorScenarioSave(BaseModel):
    name: str
    tool: str
    inputs: dict[str, Any]


def _calculator_scenario_prefix(runtime: TradingRuntime, user: dict[str, Any]) -> str:
    identity = ":".join((runtime.db.workspace_id, str(user.get("tenant_id") or ""),
                         str(user.get("email") or "").strip().lower()))
    scope = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return f"calculator-scenario:v1:{scope}:"


@router.get("/calculator/scenarios")
def list_calculator_scenarios(runtime: TradingRuntime = Depends(get_runtime),
                              user=Depends(current_user)):
    prefix = _calculator_scenario_prefix(runtime, user)
    rows = runtime.db.query("SELECT key,value FROM kv WHERE key LIKE ? ORDER BY updated_at DESC LIMIT 101",
                            (prefix + "%",))
    scenarios = []
    for row in rows[:100]:
        try:
            item = json.loads(row["value"])
            if (isinstance(item, dict) and isinstance(item.get("id"), str)
                    and row["key"] == prefix + item["id"]):
                scenarios.append(item)
        except (TypeError, json.JSONDecodeError):
            continue
    return {"scenarios": scenarios, "count": len(scenarios), "limit": 100,
            "scope": "current_user_manual_inputs_only"}


@router.post("/calculator/scenarios")
def save_calculator_scenario(payload: CalculatorScenarioSave,
                             runtime: TradingRuntime = Depends(get_runtime),
                             user=Depends(current_user)):
    name = payload.name.strip()
    if not name or len(name) > 64 or re.search(r"[\x00-\x1f\x7f]", name):
        raise HTTPException(status_code=422, detail="scenario name must be 1–64 printable characters")
    allowed_inputs = {
        "scenario": {"manual_equity", "risk_pct", "win_rate_pct", "reward_risk",
                     "trades", "cost_per_trade", "runs", "seed"},
        "capital_growth": {"manual_equity", "low_return_pct", "base_return_pct",
                           "high_return_pct", "periods", "risk_pct", "loss_streak"},
    }
    keys = allowed_inputs.get(payload.tool)
    if keys is None:
        raise HTTPException(status_code=422, detail="only manual scenario and capital-growth inputs can be saved")
    if (not payload.inputs or len(payload.inputs) > len(keys)
            or set(payload.inputs) - keys):
        raise HTTPException(status_code=422, detail="scenario contains unsupported or empty inputs")
    for value in payload.inputs.values():
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(float(value))):
            raise HTTPException(status_code=422, detail="scenario inputs must be finite numeric assumptions")

    scenario_id = uuid.uuid4().hex
    created_at = time.time()
    item = {"id": scenario_id, "name": name, "tool": payload.tool,
            "inputs": payload.inputs, "created_at": created_at,
            "source": "manual_sandbox"}
    encoded = json.dumps(item, separators=(",", ":"), allow_nan=False)
    if len(encoded) > 4096:
        raise HTTPException(status_code=413, detail="scenario is too large")
    prefix = _calculator_scenario_prefix(runtime, user)
    try:
        with runtime.db.cursor() as cur:
            cur.execute("BEGIN IMMEDIATE")
            count = cur.execute("SELECT COUNT(*) FROM kv WHERE key LIKE ?",
                                (prefix + "%",)).fetchone()[0]
            if count >= 100:
                raise HTTPException(status_code=409, detail="scenario limit (100) reached; remove one first")
            cur.execute("INSERT INTO kv(key,value,updated_at) VALUES(?,?,?)",
                        (prefix + scenario_id, encoded, created_at))
    except HTTPException:
        raise
    runtime.db.audit(user["email"], "calculator.scenario.save",
                     {"id": scenario_id, "tool": payload.tool})
    return {"scenario": item}


@router.delete("/calculator/scenarios/{scenario_id}")
def delete_calculator_scenario(scenario_id: str,
                               runtime: TradingRuntime = Depends(get_runtime),
                               user=Depends(current_user)):
    if not re.fullmatch(r"[0-9a-f]{32}", scenario_id):
        raise HTTPException(status_code=404, detail="scenario not found")
    prefix = _calculator_scenario_prefix(runtime, user)
    with runtime.db.cursor() as cur:
        cur.execute("BEGIN IMMEDIATE")
        deleted = cur.execute("DELETE FROM kv WHERE key=?", (prefix + scenario_id,)).rowcount
        if deleted != 1:
            raise HTTPException(status_code=404, detail="scenario not found")
    runtime.db.audit(user["email"], "calculator.scenario.delete", {"id": scenario_id})
    return {"ok": True, "deleted": scenario_id}


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
               reference_price: float | None = None,
               trade_ticket: str | None = None,
               whatif_entry: float | None = None,
               whatif_stop_loss: float | None = None,
               whatif_take_profit: float | None = None,
               whatif_lot: float | None = None,
               win_rate_pct: float | None = None,
               reward_risk: float | None = None,
               trades: int = 50,
               cost_per_trade: float = 0.0,
               runs: int = 300,
               seed: int = 7,
               low_return_pct: float | None = None,
               base_return_pct: float | None = None,
               high_return_pct: float | None = None,
               periods: int = 12,
               loss_streak: int = 0,
               amount: float | None = None,
               from_currency: str | None = None,
               to_currency: str | None = None,
               runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    """Read-only calculators; only symbol metadata is sourced from the selected market feed."""
    allowed_tools = {None, "points", "size", "position_size", "risk_reward", "drawdown",
                     "point_tick", "profit_loss", "break_even", "trading_costs", "auto_sl_tp",
                     "margin", "confirmation_100pt", "scenario", "capital_growth", "currency_convert",
                     "trade_review_whatif"}
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

    if tool == "trade_review_whatif":
        if not trade_ticket or len(trade_ticket) > 128:
            raise HTTPException(status_code=422, detail="select a closed trade from the active account")
        row = runtime.db.query_one(
            "SELECT broker_id,payload FROM trades WHERE ticket=? AND broker_id=?",
            (trade_ticket, runtime.adapter.id))
        if row is None:
            raise HTTPException(status_code=404, detail="closed trade not found for the active account")
        try:
            trade = TradeRecord(**json.loads(row["payload"]))
            identity = runtime.gateway._account(runtime.adapter)
            owner = runtime.db.kv_get("account-owner:" + runtime.adapter.id)
        except Exception as exc:  # noqa: BLE001 - ambiguous account evidence fails closed
            raise HTTPException(status_code=409, detail="trade account identity is unresolved") from exc
        if row["broker_id"] != trade.broker_id or trade.broker_id != runtime.adapter.id:
            raise HTTPException(status_code=404, detail="closed trade not found for the active account")
        if owner != identity:
            raise HTTPException(status_code=409, detail="active account ownership is not verified")
        actual_values = (trade.volume, trade.entry, trade.exit, trade.gross_pnl,
                         trade.costs, trade.swap, trade.pnl, trade.r_multiple)
        if not all(math.isfinite(float(value)) for value in actual_values):
            raise HTTPException(status_code=409, detail="stored closed-trade values are invalid")
        for label, value in (("entry", whatif_entry), ("stop loss", whatif_stop_loss),
                             ("take profit", whatif_take_profit), ("lot", whatif_lot)):
            if value is not None and (not math.isfinite(value) or value <= 0):
                raise HTTPException(status_code=422, detail=f"what-if {label} must be finite and positive")
        try:
            spec = runtime.market.spec(trade.symbol)
        except Exception:  # noqa: BLE001 - missing specification is a non-executable preview
            return {"tool": tool, "result": {"status": "unavailable",
                    "reason": "selected feed symbol specification is unavailable",
                    "execution_approved": False}, "spec": None,
                    "provenance": {"broker_id": trade.broker_id,
                                   "trade_source": "account_scoped_closed_trade"},
                    "disclaimer": "ทบทวนผลจริงจากรายการปิดแล้วและสมมติฐาน What-if เท่านั้น; ไม่เขียนประวัติหรือส่งคำสั่ง"}
        side_value = "BUY" if trade.direction == Direction.up else "SELL"
        entry_value = whatif_entry if whatif_entry is not None else trade.entry
        stop_value = whatif_stop_loss if whatif_stop_loss is not None else (trade.sl or None)
        target_value = whatif_take_profit if whatif_take_profit is not None else (trade.tp or None)
        volume_value = whatif_lot if whatif_lot is not None else trade.volume
        rr = risk_reward_calculator(spec, entry_value, stop_value, target_value,
                                    side_value, volume_value)
        at_sl = (profit_loss_calculator(spec, entry_value, stop_value, side_value, volume_value)
                 if stop_value is not None else None)
        at_tp = (profit_loss_calculator(spec, entry_value, target_value, side_value, volume_value)
                 if target_value is not None else None)
        result = {
            "status": "ready" if spec.spec_complete and not spec.sizing_blocked else "unavailable",
            "source": "account_scoped_closed_trade_plus_manual_whatif",
            "actual": {
                "ticket": trade.ticket, "symbol": trade.symbol, "side": side_value,
                "volume": trade.volume, "entry": trade.entry, "exit": trade.exit,
                "stop_loss": trade.sl, "take_profit": trade.tp,
                "gross_pnl": trade.gross_pnl, "costs": trade.costs,
                "swap": trade.swap, "net_pnl": trade.pnl, "r_multiple": trade.r_multiple,
                "closed_at": trade.closed_at, "exit_reason": trade.exit_reason,
                "currency": spec.account_currency, "source": "recorded_closed_trade",
            },
            "whatif": {"entry": entry_value, "stop_loss": stop_value,
                       "take_profit": target_value, "volume": volume_value,
                       "side": side_value, "source": "manual_sandbox",
                       "risk_reward": rr, "at_stop": at_sl, "at_target": at_tp},
            "execution_approved": False,
            "limitations": ["What-if ใช้ typical spread/commission จากสเปกปัจจุบัน ไม่ใช่ค่าใช้จ่ายจริงของไม้เดิม",
                            "ไม่มีการจำลองลำดับแท่งหรือสรุปว่า SL/TP ใดจะถูกชนก่อน"],
        }
        return {"tool": tool, "result": result, "spec": spec.model_dump(),
                "provenance": {"broker_id": trade.broker_id,
                               "account_scope_verified": True,
                               "market_feed": runtime.market.effective_mode,
                               "spec_source": spec.source},
                "disclaimer": "ประวัติจริงแสดงแยกจากสมมติฐาน What-if; เป็นการทบทวน ไม่ใช่ผลย้อนหลังสมมติหรือคำสั่งซื้อขาย"}

    if tool == "margin":
        adapter = runtime.adapter
        calculator_fn = getattr(adapter, "calculate_margin", None)
        reason = None
        result = None
        if not callable(calculator_fn) or getattr(adapter, "adapter_type", "") != "mt5":
            reason = "MT5 order_calc_margin is unavailable on the selected broker adapter"
        elif side not in {"BUY", "SELL"} or not math.isfinite(float(lot)) or lot <= 0:
            reason = "enter BUY/SELL and a positive legal MT5 volume"
        else:
            try:
                identity = runtime.gateway._account(adapter)
                owner = runtime.db.kv_get("account-owner:" + adapter.id)
                if owner != identity:
                    reason = "current MT5 account ownership is not verified for this workspace"
                else:
                    result = calculator_fn(
                        side, symbol, lot,
                        max_quote_age_seconds=float(runtime.settings.risk_cfg().get(
                            "limits", {}).get("data_staleness_seconds", 30)))
            except Exception as exc:  # noqa: BLE001 - unavailable broker math must fail closed
                reason = str(exc) or "MT5 margin calculation is unavailable"
        if result is None:
            result = {"status": "unavailable", "source": "mt5_order_calc_margin",
                      "required_margin": None, "free_margin": None,
                      "projected_free_margin": None, "reason": reason,
                      "execution_approved": False}
        else:
            result = {**result, "execution_approved": False,
                      "reason": "read-only MT5 margin estimate; not an order preflight"}
        return {"tool": tool, "result": result, "spec": None,
                "provenance": {"broker_id": adapter.id,
                               "adapter": getattr(adapter, "adapter_type", "unknown"),
                               "account_scope_verified": result.get("status") != "unavailable"},
                "disclaimer": "คำนวณมาร์จินจาก MT5 ที่ผูกและยืนยันบัญชีแล้วเท่านั้น; ไม่ส่งคำสั่งและไม่รับประกันว่า Order จะผ่าน"}

    if tool == "confirmation_100pt":
        normalized_side = (side or "").strip().upper()
        if (reference_price is None or not math.isfinite(reference_price)
                or reference_price <= 0 or normalized_side not in {"BUY", "SELL"}):
            result = {"status": "invalid_input", "source": "manual_sandbox",
                      "blockers": ["กรอกราคาอ้างอิงและเลือก BUY หรือ SELL"],
                      "execution_approved": False}
            return {"tool": tool, "result": result, "spec": None, "provenance": None,
                    "disclaimer": "การคำนวณ 100 points เป็นเพียง preview ไม่ใช่สถานะยืนยันคำสั่ง"}
        try:
            ctx = runtime.analysis.snapshot(symbol)
            snap = ctx.snapshot
            quality = snap.data_quality or {}
            if quality.get("ok") is not True:
                raise ValueError(quality.get("reason") or "market quote is stale")
            tick = runtime.market.ticker(symbol, snap.broker_id)
            frame = ctx.frames.get("M1")
            if frame is None or frame.empty:
                raise ValueError("fresh closed M1 candle is unavailable")
            row = frame.iloc[-1]
            now = float(runtime.market.now())
            if not math.isfinite(now):
                raise ValueError("market clock is invalid")
            current_quote_time = float(tick.t)
            current_quote_age = now - current_quote_time
            max_quote_age = float(runtime.settings.risk_cfg().get("limits", {}).get(
                "data_staleness_seconds", 30))
            if (not math.isfinite(current_quote_time) or not math.isfinite(current_quote_age)
                    or not math.isfinite(max_quote_age) or max_quote_age <= 0
                    or current_quote_age < -2
                    or current_quote_age > max_quote_age):
                raise ValueError("current market quote is stale or from the future")
            closed_at = int(row["t"]) + 60
            m1_age = now - closed_at
            confirmation_cfg = runtime.settings.strategy_cfg().get("signal_confirmation_v4", {})
            threshold = (runtime.confirmation_gate.confirmation_points
                         if runtime.confirmation_gate else
                         float(confirmation_cfg.get("confirmation_points", 100)))
            max_chase = (runtime.confirmation_gate.max_chase_points
                         if runtime.confirmation_gate else
                         float(confirmation_cfg.get("max_chase_points", 30)))
            max_m1_age = (runtime.confirmation_gate.max_closed_m1_age_seconds
                          if runtime.confirmation_gate else
                          int(confirmation_cfg.get("max_closed_m1_age_seconds", 75)))
            if m1_age < -2 or m1_age > max_m1_age:
                raise ValueError("latest closed M1 candle is stale or from the future")
            point = float(snap.spec.point)
            if not math.isfinite(point) or point <= 0:
                raise ValueError("broker point size is invalid")
            direction = Direction.up if normalized_side == "BUY" else Direction.down
            bid, ask, closed_price = float(tick.bid), float(tick.ask), float(row["c"])
            current_price = ask if direction == Direction.up else bid
            if (not all(math.isfinite(value) and value > 0
                        for value in (bid, ask, current_price, closed_price, reference_price))
                    or ask < bid):
                raise ValueError("current quote or closed M1 price is invalid")
            closed_progress = confirmation_movement_points(
                direction, reference_price, closed_price, point)
            current_progress = confirmation_movement_points(
                direction, reference_price, current_price, point)
            chase = abs(current_price - closed_price) / point
            if not all(math.isfinite(value) for value in (closed_progress, current_progress, chase)):
                raise ValueError("100-point preview math is invalid")
            if (not math.isfinite(threshold) or threshold <= 0
                    or not math.isfinite(max_chase) or max_chase < 0
                    or not math.isfinite(float(max_m1_age)) or max_m1_age <= 0):
                raise ValueError("confirmation policy is invalid")
            m5 = next((reading for reading in snap.trend
                       if reading.timeframe.upper() == "M5"), None)
            m5_aligned = bool(m5 and m5.direction == direction)
            reasons = []
            if closed_progress < threshold:
                reasons.append(f"M1 close {closed_progress:.1f}/{threshold:.0f} points")
            if not m5_aligned:
                reasons.append("M5 direction is not aligned")
            if chase > max_chase:
                reasons.append(f"current price chase {chase:.1f}/{max_chase:.0f} points")
            result = {
                "status": "preview_match" if not reasons else "waiting",
                "source": "manual_reference_plus_fresh_market",
                "side": normalized_side, "reference_price": reference_price,
                "current_price": current_price, "closed_m1_close": closed_price,
                "point": point, "threshold_points": threshold,
                "target_price": reference_price + (threshold * point *
                    (1 if direction == Direction.up else -1)),
                "closed_m1_progress_points": round(closed_progress, 2),
                "current_progress_points": round(current_progress, 2),
                "remaining_points": round(max(0.0, threshold - closed_progress), 2),
                "chase_points": round(chase, 2), "max_chase_points": max_chase,
                "m5_aligned": m5_aligned, "closed_m1_age_seconds": round(m1_age, 2),
                "quote_age_seconds": round(max(0.0, current_quote_age), 2),
                "market_feed": quality.get("feed"), "spec_source": snap.spec.source,
                "blockers": reasons, "execution_approved": False,
                "persisted_confirmation_read": False,
            }
            return {"tool": tool, "result": result, "spec": snap.spec.model_dump(),
                    "provenance": {"market_feed": quality.get("feed"),
                                   "quote_staleness_seconds": quality.get("staleness_seconds"),
                                   "closed_m1_open_utc": int(row["t"]),
                                   "account_scope": "not read"},
                    "disclaimer": "preview ใช้เกณฑ์คำนวณเดียวกับ SignalConfirmationGate แต่ไม่อ่าน/เขียนสถานะ candidate และไม่อนุมัติคำสั่ง"}
        except (KeyError, ValueError, TypeError, OverflowError, RuntimeError) as exc:
            result = {"status": "unavailable", "source": "manual_reference_plus_fresh_market",
                      "blockers": [str(exc)], "execution_approved": False}
            return {"tool": tool, "result": result, "spec": None, "provenance": None,
                    "disclaimer": "ไม่มีข้อมูล M1/ราคาใหม่พอสำหรับ preview; ไม่มีการส่งคำสั่ง"}

    if tool == "scenario":
        result = scenario_simulator(manual_equity, risk_pct, win_rate_pct, reward_risk,
                                    trades, cost_per_trade, runs, seed)
        return {"tool": tool, "result": result, "spec": None, "provenance": None,
                "disclaimer": "ผลลัพธ์เป็น Monte Carlo จากสมมติฐานที่กรอก ไม่ใช่ backtest หรือการคาดการณ์"}

    if tool == "capital_growth":
        result = capital_growth_calculator(manual_equity, low_return_pct,
                                           base_return_pct, high_return_pct,
                                           periods,
                                           risk_pct if risk_pct is not None else 0.5,
                                           loss_streak)
        return {"tool": tool, "result": result, "spec": None, "provenance": None,
                "disclaimer": "ผลลัพธ์ใช้ผลตอบแทนสมมติที่ผู้ใช้กรอก ไม่มีการคาดการณ์จาก AI หรือข้อมูลบัญชี"}

    if tool == "currency_convert":
        amount_value = amount
        base, quote = (from_currency or "").strip().upper(), (to_currency or "").strip().upper()
        rate, rate_source, rate_pair, captured_at = 1.0, "unknown", None, None
        selected: dict[str, Any] = {}
        max_quote_age = float(runtime.settings.risk_cfg().get("limits", {}).get(
            "data_staleness_seconds", 30))
        if base and quote and base == quote:
            rate_source = "identity"
        elif base and quote:
            def price_of(pair: str) -> float | None:
                try:
                    tick = runtime.market.ticker(pair)
                    quality = runtime.market.data_quality(pair, "M1")
                    now = float(runtime.market.now())
                except Exception:  # noqa: BLE001 - pair may not be available on the selected feed
                    return None
                if quality.get("ok") is not True:
                    return None
                try:
                    bid, ask, captured = float(tick.bid), float(tick.ask), float(tick.t)
                    quote_age = float(quality.get("staleness_seconds"))
                except (AttributeError, TypeError, ValueError, OverflowError):
                    return None
                if (not all(math.isfinite(value) for value in (bid, ask, captured, quote_age, now))
                        or bid <= 0 or ask < bid or captured <= 0
                        or not math.isfinite(max_quote_age) or max_quote_age <= 0
                        or quote_age < 0 or quote_age > max_quote_age or captured > now + 2):
                    return None
                midpoint = (bid + ask) / 2
                if not math.isfinite(midpoint) or midpoint <= 0:
                    return None
                selected.update(pair=pair, captured_at=captured,
                                staleness_seconds=quote_age)
                return midpoint

            rate, rate_source = resolve_quote_rate(base, quote, price_of)
            rate_pair = selected.get("pair")
            captured_at = selected.get("captured_at")
        result = currency_conversion_calculator(
            amount_value, base, quote, rate, rate_source, captured_at)
        result["rate_pair"] = rate_pair
        result["staleness_seconds"] = selected.get("staleness_seconds") if base != quote else 0
        result["market_feed"] = runtime.market.effective_mode
        return {"tool": tool, "result": result, "spec": None,
                "provenance": {"market_feed": runtime.market.effective_mode,
                               "rate_pair": rate_pair, "rate_source": rate_source,
                               "captured_at": captured_at},
                "disclaimer": "ใช้อัตราตลาดสดจากคู่สกุลเงินที่ feed ปัจจุบันเปิดเผย; ถ้าไม่มีราคาใหม่จะไม่แทนด้วยเรตคงที่"}

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
