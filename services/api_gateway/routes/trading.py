from __future__ import annotations

import json

import numpy as np
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
    return {
        "account": runtime.account(),
        "positions": [p.model_dump() for p in runtime.positions_cache],
        "risk": runtime.risk_state().model_dump(),
        "mode": runtime.mode.value,
        "reconcile": runtime.last_reconcile,
        "broker": runtime.adapter.describe(),
    }


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
    rows = runtime.db.query("SELECT payload FROM trades ORDER BY closed_at DESC LIMIT ?", (limit,))
    out = []
    for row in rows:
        try:
            out.append(json.loads(row["payload"]))
        except json.JSONDecodeError:
            continue
    return {"trades": out}


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
