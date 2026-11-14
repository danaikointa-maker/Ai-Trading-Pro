from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from packages.shared_schemas.models import Direction, EquityPoint, TradeMode, TradeRecord
from services.api_gateway.deps import current_user, get_runtime
from services.api_gateway.state import TradingRuntime
from services.backtest_engine.metrics import compute_metrics

router = APIRouter(prefix="/api/trading", tags=["trading"])


class ManualOrder(BaseModel):
    symbol: str = "XAUUSD"
    direction: Direction


class CloseRequest(BaseModel):
    ticket: str
    volume: float | None = None


class ModeRequest(BaseModel):
    mode: TradeMode


@router.get("/state")
def state(runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    payload = {
        "account": runtime.account(),
        "risk": runtime.risk_state().model_dump(),
        "mode": runtime.mode.value,
        "reconcile": runtime.last_reconcile,
        "broker": runtime.adapter.describe(),
    }
    payload.update(runtime.position_view())
    return payload


@router.get("/live")
def live(runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    """Full live snapshot (same contract as the websocket frame).

    The dashboard uses this when a websocket cannot be established (corporate
    proxy, iframe sandbox) so the terminal never degrades to a partial view.
    """
    payload = runtime.live_payload()
    payload["type"] = "live"
    return payload


@router.post("/order")
def manual_order(payload: ManualOrder, runtime: TradingRuntime = Depends(get_runtime),
                 user=Depends(current_user)):
    result = runtime.manual_trade(payload.symbol, payload.direction, actor=user["email"])
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result)
    return result


@router.post("/close")
def close(payload: CloseRequest, runtime: TradingRuntime = Depends(get_runtime),
          user=Depends(current_user)):
    result = runtime.close_ticket(payload.ticket, payload.volume)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result)
    return result


@router.post("/close-all")
def close_all(runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    return runtime.close_all()


@router.post("/mode")
def set_mode(payload: ModeRequest, runtime: TradingRuntime = Depends(get_runtime),
             user=Depends(current_user)):
    result = runtime.set_mode(payload.mode, actor=user["email"])
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result)
    return result


@router.get("/trades")
def trades(limit: int = Query(50, ge=1, le=500), runtime: TradingRuntime = Depends(get_runtime),
          user=Depends(current_user)):
    rows = runtime.db.query("SELECT payload FROM trades WHERE broker_id=? ORDER BY closed_at DESC LIMIT ?",
                            (runtime.adapter.id, limit))
    out = []
    for row in rows:
        try:
            out.append(json.loads(row["payload"]))
        except json.JSONDecodeError:
            continue
    return {"trades": out}


@router.get("/trades/{ticket}/review")
def trade_review(ticket: str, runtime: TradingRuntime = Depends(get_runtime),
                 user=Depends(current_user)):
    row = runtime.db.query_one("SELECT broker_id,payload FROM trades WHERE ticket=?", (ticket,))
    if row is None:
        raise HTTPException(status_code=404, detail="trade not found")
    try:
        trade = TradeRecord(**json.loads(row["payload"]))
    except Exception as exc:  # noqa: BLE001 - don't expose corrupt stored payload
        raise HTTPException(status_code=409, detail="stored trade evidence is invalid") from exc
    if row["broker_id"] != runtime.adapter.id or trade.broker_id != runtime.adapter.id:
        raise HTTPException(status_code=404, detail="trade not found")
    signal_row = (runtime.db.query_one("SELECT payload FROM signals WHERE id=?", (trade.signal_id,))
                  if trade.signal_id else None)
    entry_snapshot = None
    if signal_row:
        try:
            signal_payload = json.loads(signal_row["payload"])
            if signal_payload.get("broker_id") == trade.broker_id and signal_payload.get("symbol") == trade.symbol:
                entry_snapshot = signal_payload
        except (TypeError, json.JSONDecodeError):
            entry_snapshot = None
    outcome = "profitable" if trade.pnl > 0 else "loss" if trade.pnl < 0 else "breakeven"
    retrospective = {
        "outcome": outcome,
        "points": trade.points,
        "pnl": trade.pnl,
        "r_multiple": trade.r_multiple,
        "exit_reason": trade.exit_reason,
        "basis": "recorded trade result; not a new prediction",
        "limitations": ([] if entry_snapshot else ["ไม่มี snapshot สัญญาณตอนเข้าไม้ที่เชื่อมโยงได้"]),
        "suggestions": [],
    }
    if entry_snapshot:
        retrospective["suggestions"] = [
            "ทบทวนเหตุผลและเงื่อนไขความเสี่ยงที่บันทึกไว้ก่อนเข้าไม้ เทียบกับผลจริง; ผลครั้งเดียวไม่ยืนยันว่ากลยุทธ์ดีหรือไม่"
        ]
    return {"trade": trade.model_dump(), "entry_snapshot": entry_snapshot,
            "retrospective": retrospective,
            "disclaimer": "เป็นการทบทวนข้อมูลในอดีต ไม่ใช่คำแนะนำลงทุนหรือการคาดการณ์ผลครั้งถัดไป"}


@router.get("/deals")
def deals(limit: int = Query(500, ge=1, le=5000), runtime: TradingRuntime = Depends(get_runtime),
          user=Depends(current_user)):
    from services.execution_gateway.history import DealLedger

    from integrations.brokers.base import BrokerError

    try:
        identity = runtime.gateway._assert_account(runtime.adapter)
    except BrokerError as exc:
        raise HTTPException(status_code=409, detail="broker history account is unresolved") from exc
    account_key = f"{identity['server']}:{identity['login']}"
    ledger = DealLedger(runtime.db)
    rows = ledger.deals(runtime.adapter.id, account_key)
    rows = list(reversed(rows[-limit:]))
    return {"deals": rows, "count": len(rows), "broker_id": runtime.adapter.id,
            "account_key": account_key, "attribution": "broker deal evidence; not strategy ownership"}


@router.get("/journal")
def journal(limit: int = Query(20, ge=1, le=200), runtime: TradingRuntime = Depends(get_runtime),
            user=Depends(current_user)):
    rows = runtime.db.query("SELECT payload FROM journal ORDER BY created_at DESC LIMIT ?", (limit,))
    entries = []
    for row in rows:
        try:
            entries.append(json.loads(row["payload"]))
        except json.JSONDecodeError:
            continue
    return {"entries": entries}


@router.get("/performance")
def performance(runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    rows = runtime.db.query("SELECT payload FROM trades ORDER BY closed_at")
    trades_list: list[TradeRecord] = []
    for row in rows:
        try:
            trades_list.append(TradeRecord(**json.loads(row["payload"])))
        except Exception:  # noqa: BLE001
            continue
    eq_rows = runtime.db.query("SELECT t, equity, balance FROM equity ORDER BY t")
    curve = [EquityPoint(t=int(r["t"]), equity=float(r["equity"]), balance=float(r["balance"]))
             for r in eq_rows]
    if not curve:
        info = runtime.adapter.account_info()
        curve = [EquityPoint(t=int(runtime.market.now()), equity=info.equity, balance=info.balance)]
    starting = float(getattr(runtime.adapter, "starting_balance", 10000.0))
    metrics = compute_metrics(trades_list, curve, max(1, len(trades_list) * 3), starting)
    by_exit: dict[str, dict] = {}
    for trade in trades_list:
        bucket = by_exit.setdefault(trade.exit_reason or "unknown", {"count": 0, "pnl": 0.0})
        bucket["count"] += 1
        bucket["pnl"] = round(bucket["pnl"] + trade.pnl, 2)
    r_multiples = [t.r_multiple for t in trades_list]
    return {
        "metrics": metrics.model_dump(),
        "equity_curve": [p.model_dump() for p in curve[-500:]],
        "by_exit_reason": by_exit,
        "r_multiples": r_multiples[-100:],
        "daily": runtime.risk.daily_report(runtime.market.now()),
        "trades": len(trades_list),
        "note": ("Live metrics count only closed trades in this account. They are not a claim of "
                 "future performance."),
    }


@router.get("/daily")
def daily(runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    return runtime.risk.daily_report(runtime.market.now())
