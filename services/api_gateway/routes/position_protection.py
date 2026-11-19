from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from packages.persistence.position_events import PositionEventLog
from packages.shared_schemas.models import Direction, Signal
from services.api_gateway.deps import current_user, get_runtime, require_trader
from services.api_gateway.state import TradingRuntime
from services.risk_engine.manager import PositionAction
from services.risk_engine.protection_profile import load_v1_1_profile

router = APIRouter(prefix="/api/position-protection", tags=["position-protection"])
MODES = {"MANUAL", "SEMI_AUTO", "FULL_AUTO", "HYBRID"}


class ModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["MANUAL", "SEMI_AUTO", "FULL_AUTO", "HYBRID"]


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket: str = Field(min_length=1, max_length=128)
    action: Literal["break_even", "trailing"]
    mode: Literal["MANUAL", "SEMI_AUTO", "FULL_AUTO", "HYBRID"] = "MANUAL"


class ApplyRequest(PreviewRequest):
    expected_position_version: str = Field(min_length=32, max_length=64)
    expected_sl: float = Field(gt=0, allow_inf_nan=False)
    idempotency_key: str = Field(min_length=16, max_length=128)


class ControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="operator", min_length=1, max_length=160)


def _identity(runtime: TradingRuntime) -> dict[str, str]:
    try:
        return runtime.gateway._assert_account(runtime.adapter)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, "ยืนยันบัญชีและ workspace ของ position ไม่ได้") from exc


def _scope_key(identity: dict[str, str]) -> str:
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return f"position_protection:{identity['broker_id']}:{digest}"


def _position_version(position) -> str:
    values = {"ticket": str(position.ticket), "broker_id": position.broker_id,
              "symbol": position.symbol, "direction": position.direction.value,
              "volume": position.volume, "entry": position.entry,
              "sl": position.sl, "tp": position.tp}
    return hashlib.sha256(json.dumps(values, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _current_position(runtime: TradingRuntime, ticket: str):
    identity = _identity(runtime)
    rows = [p for p in runtime.adapter.positions()
            if str(p.ticket) == str(ticket) and p.broker_id == identity["broker_id"]]
    if len(rows) != 1:
        raise HTTPException(404, "ไม่พบ position ที่เปิดอยู่และยืนยันตัวตนได้")
    return identity, rows[0]


def _frozen_plan(runtime: TradingRuntime, position, identity: dict[str, str]):
    """Load only the immutable pre-order signal snapshot for this broker ticket."""
    ledger = PositionEventLog(runtime.db)
    order_id = ledger.linked_order(identity["broker_id"], str(position.ticket), identity)
    if not order_id:
        return None
    row = runtime.db.query_one("SELECT payload FROM pre_order_snapshots WHERE order_id=? AND broker_id=?",
                               (order_id, identity["broker_id"]))
    if row is None:
        return None
    try:
        payload = json.loads(row["payload"])
        signal_data = payload.get("original_signal")
        if (payload.get("schema_version") != 1 or payload.get("account_identity") != identity
                or not isinstance(signal_data, dict)):
            return None
        signal = Signal(**signal_data)
        if (signal.broker_id != identity["broker_id"] or signal.symbol != position.symbol
                or signal.id != position.signal_id or signal.plan is None):
            return None
        return signal
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None


def _preview(runtime: TradingRuntime, ticket: str, requested_action: str):
    identity, position = _current_position(runtime, ticket)
    try:
        tick = runtime.adapter.ticker(position.symbol)
        spec = runtime.adapter.symbol_spec(position.symbol)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, "อ่านราคาและข้อกำหนดโบรกเกอร์ปัจจุบันไม่ได้") from exc
    now = time.time()
    if (not math.isfinite(tick.t) or abs(now - tick.t) > 5
            or not math.isfinite(tick.bid) or not math.isfinite(tick.ask)
            or tick.bid <= 0 or tick.ask < tick.bid):
        raise HTTPException(409, "ราคา broker เก่า/ไม่ถูกต้อง · ยกเลิก preview")
    close_price = tick.bid if position.direction == Direction.up else tick.ask
    plan = _frozen_plan(runtime, position, identity)
    profile = load_v1_1_profile()
    context = runtime.contexts.get(position.symbol)
    atr_points = None
    atr_age_seconds = None
    atr_closed = False
    if context is not None and context.snapshot.timeframe == "M5":
        bar_open = int(context.snapshot.server_time)
        close_at = bar_open + 5 * 60
        age = now - close_at
        if 0 <= age <= float(profile["trailing"].get("max_atr_age_seconds", 90)):
            atr_points = float(context.snapshot.indicators.atr_points)
            atr_age_seconds = age
            atr_closed = True
    candidate, blockers = runtime.manager.protection_candidate(
        position, spec, plan, profile, close_price=close_price,
        atr_points=atr_points, atr_is_closed=atr_closed,
        atr_age_seconds=atr_age_seconds, requested_action=requested_action,
    )
    return {"identity": identity, "position": position, "profile": profile,
            "candidate": candidate, "blockers": blockers,
            "current_price": close_price, "tick_time": tick.t,
            "spec": spec, "version": _position_version(position)}


@router.get("")
def protection_state(runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    identity = _identity(runtime)
    scope = _scope_key(identity)
    try:
        positions = [p for p in runtime.adapter.positions() if p.broker_id == identity["broker_id"]]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, "อ่าน positions จาก broker ไม่ได้") from exc
    profile = load_v1_1_profile()
    mode = runtime.db.kv_get(f"{scope}:mode", profile["default_mode"])
    paused = bool(runtime.db.kv_get(f"{scope}:paused", False))
    log = PositionEventLog(runtime.db)
    out = []
    for pos in positions:
        try:
            events = log.for_ticket(broker_id=identity["broker_id"], ticket=str(pos.ticket),
                                    account_identity=identity)
        except Exception:
            events = []
        out.append({"position": pos.model_dump(mode="json"), "version": _position_version(pos),
                    "events": events[-10:]})
    return {"profile": profile, "mode": mode, "paused": paused,
            "broker_id": identity["broker_id"], "workspace_id": identity["workspace_id"],
            "account_type": runtime.adapter.account_type,
            "execution": "paper" if runtime.adapter.adapter_type in {"simulated_mt5", "paper"} else "read_only",
            "positions": out, "live_auto_enabled": False}


@router.put("/mode")
def set_protection_mode(payload: ModeRequest, runtime: TradingRuntime = Depends(get_runtime),
                        user=Depends(require_trader)):
    identity = _identity(runtime)
    scope = _scope_key(identity)
    if payload.mode in {"FULL_AUTO", "HYBRID"}:
        raise HTTPException(403, "V1.1 auto modification is locked until Demo approval and reconciliation gates pass")
    runtime.db.kv_set(f"{scope}:mode", payload.mode)
    runtime.db.audit(user["email"], "position_protection.mode",
                     {"broker_id": identity["broker_id"], "mode": payload.mode,
                      "profile": "position-protection-v1.1"})
    return {"mode": payload.mode, "saved": True, "auto_enabled": False}


@router.post("/preview")
def preview(payload: PreviewRequest, runtime: TradingRuntime = Depends(get_runtime),
            user=Depends(current_user)):
    identity = _identity(runtime)
    saved_mode = runtime.db.kv_get(f"{_scope_key(identity)}:mode", "MANUAL")
    if payload.mode not in {"MANUAL", "SEMI_AUTO"} or payload.mode != saved_mode:
        raise HTTPException(409, "โหมดป้องกันเปลี่ยนหรือยังไม่ได้รับอนุญาต · โหลดสถานะใหม่")
    result = _preview(runtime, payload.ticket, payload.action)
    candidate = result["candidate"]
    return {
        "status": "proposed" if candidate else "blocked",
        "broker_id": result["identity"]["broker_id"], "ticket": payload.ticket,
        "action": payload.action, "mode": payload.mode,
        "profile": result["profile"]["id"], "profile_status": result["profile"]["status"],
        "position_version": result["version"], "entry": result["position"].entry,
        "current_sl": result["position"].sl, "tp": result["position"].tp,
        "proposed_sl": candidate.new_sl if candidate else None,
        "initial_r_price": (candidate.metadata or {}).get("initial_r_price") if candidate else None,
        "current_close_price": result["current_price"],
        "tick_time": result["tick_time"], "blockers": result["blockers"],
        "execution_status": "preview_only",
    }


@router.post("/apply")
def apply(payload: ApplyRequest, runtime: TradingRuntime = Depends(get_runtime),
          user=Depends(require_trader)):
    adapter = runtime.adapter
    if adapter.adapter_type not in {"simulated_mt5", "paper"}:
        raise HTTPException(403, "การ Apply V1.1 อนุญาตเฉพาะ PAPER ก่อน · Demo ยังรออนุมัติ")
    scope = _scope_key(_identity(runtime))
    if runtime.db.kv_get(f"{scope}:paused", False):
        raise HTTPException(409, "Position Protection ถูก pause อยู่")
    if (payload.mode not in {"MANUAL", "SEMI_AUTO"}
            or runtime.db.kv_get(f"{scope}:mode", "MANUAL") != payload.mode):
        raise HTTPException(403, "FULL_AUTO/HYBRID ยังล็อกอยู่")
    preview_data = _preview(runtime, payload.ticket, payload.action)
    if preview_data["version"] != payload.expected_position_version:
        raise HTTPException(409, "position เปลี่ยนหลัง preview · โหลดใหม่และประเมินซ้ำ")
    candidate = preview_data["candidate"]
    if candidate is None:
        raise HTTPException(409, "ไม่มี candidate ที่ผ่านกฎป้องกัน: " + "; ".join(preview_data["blockers"]))
    spec = preview_data["spec"]
    if not math.isclose(candidate.new_sl, payload.expected_sl, rel_tol=0,
                        abs_tol=spec.tick_size / 2):
        raise HTTPException(409, "ระดับ SL เปลี่ยนจาก preview · ประเมินใหม่ก่อน Apply")
    # The request key is recorded in audit; ExecutionGateway derives a durable
    # identity/ticket/SL/TP key and will not resend an ambiguous operation.
    current = runtime.db.query_one(
        "SELECT operation_id,status FROM position_modification_intents "
        "WHERE broker_id=? AND ticket=? AND status IN ('requested','accepted_unverified','unknown')",
        (adapter.id, str(payload.ticket)))
    if current:
        raise HTTPException(409, "มี SL modification ที่ยังไม่ reconcile · ห้ามสั่งซ้ำ")
    ok = runtime.gateway.modify(adapter, payload.ticket, sl=candidate.new_sl,
                                reason=f"position-protection-v1.1:{payload.action}",
                                idempotency_key=payload.idempotency_key)
    runtime.db.audit(user["email"], "position_protection.apply",
                     {"broker_id": adapter.id, "ticket": payload.ticket,
                      "request_key": payload.idempotency_key, "action": payload.action,
                      "profile": "position-protection-v1.1", "accepted": bool(ok)})
    try:
        runtime.notifier.emit("info" if ok else "warning",
                              "Position protection request accepted" if ok else "Position protection unresolved",
                              f"Ticket {payload.ticket}; inspect the refreshed broker SL/TP before another change.",
                              meta={"broker_id": adapter.id, "ticket": payload.ticket}, dedupe_seconds=0)
    except Exception as exc:  # noqa: BLE001
        runtime._log_error("position_protection_notification", exc)
    if not ok:
        raise HTTPException(503, "ผลการส่ง/ยืนยันยังไม่ชัดเจน · ระบบล็อกการส่งซ้ำจน reconcile")
    return {"status": "accepted_or_confirmed", "ticket": payload.ticket,
            "broker_id": adapter.id, "sl": candidate.new_sl,
            "note": "ตรวจ snapshot MT5 ล่าสุดเพื่อยืนยัน broker-confirmed state"}


@router.post("/pause")
def pause(payload: ControlRequest, runtime: TradingRuntime = Depends(get_runtime),
          user=Depends(require_trader)):
    identity = _identity(runtime)
    scope = _scope_key(identity)
    runtime.db.kv_set(f"{scope}:paused", True)
    runtime.db.audit(user["email"], "position_protection.pause",
                     {"broker_id": identity["broker_id"], "reason": payload.reason})
    return {"paused": True, "broker_id": identity["broker_id"]}


@router.post("/resume")
def resume(payload: ControlRequest, runtime: TradingRuntime = Depends(get_runtime),
           user=Depends(require_trader)):
    identity = _identity(runtime)
    scope = _scope_key(identity)
    runtime.db.kv_set(f"{scope}:paused", False)
    runtime.db.audit(user["email"], "position_protection.resume",
                     {"broker_id": identity["broker_id"], "reason": payload.reason})
    return {"paused": False, "broker_id": identity["broker_id"], "auto_enabled": False}


@router.get("/analyzer")
def protection_analyzer(limit: int = Query(200, ge=1, le=1000),
                        runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    """Read-only event counts; this is telemetry, not causal performance evidence."""
    identity = _identity(runtime)
    rows = runtime.db.query(
        "SELECT kind,status,COUNT(*) AS n FROM position_events WHERE broker_id=? "
        "AND kind IN ('modify','protection_preview') GROUP BY kind,status ORDER BY kind,status LIMIT ?",
        (identity["broker_id"], limit))
    return {"broker_id": identity["broker_id"], "events": [dict(row) for row in rows],
            "status": "telemetry_only",
            "causal_comparison": "NOT_AVAILABLE: matched-entry backtest/replay and Demo outcome study not implemented",
            "live_data_used": False}
