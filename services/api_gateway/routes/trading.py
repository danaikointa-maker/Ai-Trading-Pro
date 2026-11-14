from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from packages.shared_schemas.models import Direction, EquityPoint, TradeMode, TradeRecord
from packages.persistence.position_events import PositionEventLog
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


def _original_snapshot_for_trade(runtime: TradingRuntime, trade: TradeRecord) -> dict | None:
    """Link immutable pre-send evidence by broker ticket, or unique signal ID.

    Ambiguous links and mismatched account ownership never become historical
    facts. In particular this code never calls live analysis to reconstruct a
    zone or fills a missing entry plan from the current chart.
    """
    params = (trade.broker_id, trade.symbol, trade.ticket)
    rows = runtime.db.query(
        "SELECT p.payload FROM pre_order_snapshots p "
        "JOIN orders o ON o.id=p.order_id "
        "WHERE p.broker_id=? AND p.symbol=? AND o.broker_id=p.broker_id "
        "AND o.symbol=p.symbol "
        "AND json_extract(CASE WHEN json_valid(o.payload) THEN o.payload ELSE '{}' END, "
        "'$.result.ticket')=? LIMIT 2", params)
    if not rows and trade.signal_id:
        rows = runtime.db.query(
            "SELECT p.payload FROM pre_order_snapshots p "
            "JOIN orders o ON o.id=p.order_id "
            "WHERE p.broker_id=? AND p.symbol=? AND o.broker_id=p.broker_id "
            "AND o.symbol=p.symbol AND p.signal_id=? LIMIT 2",
            (trade.broker_id, trade.symbol, trade.signal_id))
    if len(rows) != 1:
        return None
    owner = runtime.db.query_one("SELECT value FROM kv WHERE key=?",
                                 ("account-owner:" + trade.broker_id,))
    if owner is None:
        return None
    try:
        payload = json.loads(rows[0]["payload"])
        identity = json.loads(owner["value"])
        request = payload["request"]
        if (payload.get("schema_version") != 1
                or payload.get("account_identity") != identity
                or request.get("broker_id") != trade.broker_id
                or request.get("symbol") != trade.symbol
                or (trade.signal_id and request.get("signal_id") != trade.signal_id)
                or (payload.get("original_signal") is not None
                    and (payload["original_signal"].get("id") != request.get("signal_id")
                         or payload["original_signal"].get("broker_id") != trade.broker_id
                         or payload["original_signal"].get("symbol") != trade.symbol))):
            return None
        return payload
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _account_scoped_evidence(runtime: TradingRuntime, ticket: str, broker_id: str) -> dict:
    """Read-only broker history. Ticket equality does not certify strategy attribution."""
    row = runtime.db.query_one("SELECT value FROM kv WHERE key=?", ("account-owner:" + broker_id,))
    if row is None:
        return {"events": [], "deals": [], "deal_attribution": "unavailable"}
    try:
        identity = json.loads(row["value"])
        if identity.get("broker_id") != broker_id or identity.get("workspace_id") != runtime.db.workspace_id:
            raise ValueError("account identity mismatch")
        from services.execution_gateway.history import DealLedger

        account_key = f"{identity['server']}:{identity['login']}"
        deals = [d for d in DealLedger(runtime.db).deals(broker_id, account_key)
                 if d.get("position_id") == ticket]
        events = PositionEventLog(runtime.db).for_ticket(
            broker_id=broker_id, ticket=ticket, account_identity=identity)
    except (TypeError, KeyError, ValueError, AttributeError):
        return {"events": [], "deals": [], "deal_attribution": "unavailable"}
    return {"events": events, "deals": deals,
            "deal_attribution": "broker_position_id_match_only" if deals else "no_matching_deals"}


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
    original_plan_snapshot = _original_snapshot_for_trade(runtime, trade)
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
    if original_plan_snapshot and original_plan_snapshot.get("original_signal"):
        # The signal row may be overwritten at fill time; this copy cannot be.
        entry_snapshot = original_plan_snapshot["original_signal"]
    outcome = "profitable" if trade.pnl > 0 else "loss" if trade.pnl < 0 else "breakeven"
    retrospective = {
        "outcome": outcome,
        "points": trade.points,
        "pnl": trade.pnl,
        "r_multiple": trade.r_multiple,
        "exit_reason": trade.exit_reason,
        "basis": "recorded trade result; not a new prediction",
        "limitations": ([] if original_plan_snapshot and original_plan_snapshot.get("original_signal")
                        else ["ไม่พบหลักฐานแผนก่อนส่งออเดอร์; สัญญาณเก่าหรือข้อมูลไม่ครบ"]),
        "suggestions": [],
    }
    if entry_snapshot:
        retrospective["suggestions"] = [
            "ทบทวนเหตุผลและเงื่อนไขความเสี่ยงที่บันทึกไว้ก่อนเข้าไม้ เทียบกับผลจริง; ผลครั้งเดียวไม่ยืนยันว่ากลยุทธ์ดีหรือไม่"
        ]
    return {"trade": trade.model_dump(), "entry_snapshot": entry_snapshot,
            "original_plan_snapshot": original_plan_snapshot,
            **_account_scoped_evidence(runtime, ticket, trade.broker_id),
            "retrospective": retrospective,
            "disclaimer": "เป็นการทบทวนข้อมูลในอดีต ไม่ใช่คำแนะนำลงทุนหรือการคาดการณ์ผลครั้งถัดไป"}


@router.get("/positions/{ticket}/review")
def position_review(ticket: str, runtime: TradingRuntime = Depends(get_runtime),
                    user=Depends(current_user)):
    """Snapshot of an *open* position, never a command or a live-zone reconstruction."""
    adapter = runtime.adapter
    try:
        runtime.gateway._assert_account(adapter)
        matches = [p for p in adapter.positions() if p.ticket == ticket]
        runtime.gateway._assert_account(adapter)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="broker position evidence unavailable") from exc
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail="ambiguous broker ticket; reconciliation required")
    if not matches or matches[0].broker_id != adapter.id:
        raise HTTPException(status_code=404, detail="open position not found")
    position = matches[0]
    # Same identity/link rules as a closed trade; this proxy has only read-only fields.
    from types import SimpleNamespace

    entry = _original_snapshot_for_trade(runtime, SimpleNamespace(
        broker_id=adapter.id, symbol=position.symbol, ticket=ticket, signal_id=position.signal_id))
    return {"position": position.model_dump(), "original_plan_snapshot": entry,
            **_account_scoped_evidence(runtime, ticket, adapter.id),
            "disclaimer": "เส้นจากบันทึกก่อนส่งออเดอร์เท่านั้น; สถานะโบรกเกอร์อาจเปลี่ยนหลังการอ่าน"}


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
