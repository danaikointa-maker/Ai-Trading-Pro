from __future__ import annotations

import json
import time
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from integrations.brokers.base import BrokerError
from packages.shared_schemas.settings import get_settings
from services.api_gateway.deps import current_user, get_runtime
from services.api_gateway.market_access import chart_source, market_accounts
from services.api_gateway.state import TradingRuntime
from services.api_gateway.terminal_views import claim_terminal, private_positions
from services.market_data.chart_overlays import closed_chart_overlays
from services.market_data.simulator import candles_from_df
from services.risk_engine.planner import points_calculator

router = APIRouter(prefix="/api/market", tags=["market"])


class TerminalClaim(BaseModel):
    code: str = Field(min_length=20, max_length=64)


class TerminalLabel(BaseModel):
    label: str = Field(min_length=2, max_length=100)
    expected_label: str


@router.put("/terminal-links/{link_id}")
def rename_terminal(link_id: str, body: TerminalLabel, runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    label = " ".join(body.label.split())
    if len(label) < 2:
        raise HTTPException(400, "ชื่อบัญชีต้องยาว 2–100 ตัวอักษร")
    with runtime.db.cursor() as cur:
        row = cur.execute("SELECT label FROM terminal_view_links WHERE id=? AND tenant_id=? AND owner_email=?",
                          (link_id, user["tenant_id"], user["email"])).fetchone()
        if row is None:
            raise HTTPException(404, "terminal link not found")
        if row["label"] != body.expected_label:
            raise HTTPException(409, "ข้อมูลเปลี่ยนแล้ว กรุณา Refresh และลองใหม่")
        cur.execute("UPDATE terminal_view_links SET label=? WHERE id=?", (label, link_id))
        runtime.db.audit(user["email"], "terminal_view.rename", {"id": link_id})
    return {"ok": True, "label": label, "orders_sent": False}


@router.post("/terminal-links")
def link_terminal(body: TerminalClaim, runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    return claim_terminal(runtime, user, body.code)


@router.delete("/terminal-links/{link_id}")
def unlink_terminal(link_id: str, runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    removed = runtime.db.execute("DELETE FROM terminal_view_links WHERE id=? AND tenant_id=? AND owner_email=?",
                                 (link_id, user["tenant_id"], user["email"]))
    if not removed:
        raise HTTPException(404, "terminal link not found")
    runtime.db.audit(user["email"], "terminal_view.unlinked", {"id": link_id})
    return {"ok": True, "orders_sent": False}


@router.get("/positions")
def chart_positions(symbol: str = "XAUUSD", account_id: str | None = None,
                    runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    if not account_id:
        return {"available": False, "positions": [], "read_only": True,
                "reason": "กราฟตลาดกลางไม่แสดงไม้ส่วนตัว · ผูก terminal ในหน้า Brokers แล้วเลือกบัญชีบนกราฟ"}
    adapter, _ = chart_source(runtime, user, symbol, account_id)
    source_symbol = runtime.market.resolve_chart_symbol(adapter, symbol)
    result = private_positions(runtime, user, account_id, adapter.id, source_symbol)
    return {**result, "broker_id": adapter.id, "source_symbol": source_symbol}


def quote_freshness(tick_time: float, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    age = now - tick_time
    issue = "future_timestamp" if age < -5 else "stale_quote" if age > 30 else None
    return {"server_time": now, "quote_time": tick_time, "quote_age_seconds": age,
            "stale": issue is not None, "clock_issue": issue}


@router.get("/context")
def market_context(runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    return {"accounts": market_accounts(runtime, user), "default_source": "shared_market",
            "account_required_for_chart": False, "chart_read_only": True}


@router.get("/symbols")
def symbols(runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    out = []
    for name in runtime.symbols():
        spec = runtime.adapter.symbol_spec(name)
        out.append({"symbol": name, "description": spec.description, "digits": spec.digits,
                    "point": spec.point, "contract_size": spec.contract_size,
                    "spread_typical_points": spec.spread_typical_points,
                    "value_per_point_per_lot": spec.value_per_point_per_lot})
    return {"symbols": out, "broker_id": runtime.adapter.id}


@router.get("/candles")
def candles(symbol: str = "XAUUSD", timeframe: str = "M5", limit: int = Query(400, ge=20, le=2000),
            account_id: str | None = None,
            runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    adapter, feed = chart_source(runtime, user, symbol, account_id)
    source_symbol = runtime.market.resolve_chart_symbol(adapter, symbol)
    try:
        # The chart response contains OHLCV only. Strategy enrichment is costly
        # and adds no fields to this response; read the adapter's actual bars.
        df = adapter.candles(source_symbol, timeframe, limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BrokerError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        spec = adapter.symbol_spec(source_symbol)
        tick = runtime.market.ticker(source_symbol, broker_id=adapter.id)
    except BrokerError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"symbol": symbol, "source_symbol": source_symbol, "timeframe": timeframe, "broker_id": adapter.id,
            "feed": feed, "freshness": quote_freshness(tick.t) if feed == "mt5-live" else None,
            "spec": spec.model_dump(),
            "candles": [c.model_dump() for c in candles_from_df(df)],
            "ticker": tick.model_dump()}


@router.get("/ticker")
def ticker(symbol: str = "XAUUSD", account_id: str | None = None, runtime: TradingRuntime = Depends(get_runtime),
           user=Depends(current_user)):
    adapter, feed = chart_source(runtime, user, symbol, account_id)
    source_symbol = runtime.market.resolve_chart_symbol(adapter, symbol)
    quote = runtime.market.latest_quote(source_symbol, broker_id=adapter.id)
    if quote is None:
        raise HTTPException(status_code=503, detail="no quote available")
    quote["broker_id"] = adapter.id
    quote["feed"] = feed
    quote["symbol"] = source_symbol
    if feed == "mt5-live":
        freshness = quote_freshness(quote["tick"]["t"])
        quote["freshness"] = freshness
        quote["transport_stale"] = quote["stale"]
        quote["stale"] = quote["stale"] or freshness["stale"]
    return quote


@router.get("/overlays")
def chart_overlays(symbol: str = "XAUUSD", timeframe: str = "M5", limit: int = Query(400, ge=30, le=2000),
                   account_id: str | None = None, runtime: TradingRuntime = Depends(get_runtime),
                   user=Depends(current_user)):
    adapter, feed = chart_source(runtime, user, symbol, account_id)
    source_symbol = runtime.market.resolve_chart_symbol(adapter, symbol)
    try:
        # Use the selected source and timeframe exclusively; exclude its forming
        # final row rather than using the runtime's unrelated simulation clock.
        frame = adapter.candles(source_symbol, timeframe, limit).sort_values("t").drop_duplicates("t")
        closed = frame.iloc[:-1]
        spec = adapter.symbol_spec(source_symbol)
        result = closed_chart_overlays(closed.to_json(orient="records", double_precision=15),
                                       json.dumps({"digits": spec.digits, "point": spec.point}),
                                       json.dumps(asdict(runtime.analysis.zone_cfg)), timeframe)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BrokerError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"symbol": symbol, "source_symbol": source_symbol, "broker_id": adapter.id,
            "timeframe": timeframe, "feed": feed, "read_only": True, "analysis": result,
            "positions_available": False, "plan_available": False}


@router.get("/spec")
def spec(symbol: str = "XAUUSD", broker_id: str | None = None,
         runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    return runtime.registry.get(broker_id).symbol_spec(symbol).model_dump()


@router.get("/calculator")
def calculator(symbol: str = "XAUUSD", points: float = 750, lot: float = 0.01,
               runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    spec_obj = runtime.adapter.symbol_spec(symbol)
    return {"result": points_calculator(spec_obj, points, lot), "spec": spec_obj.model_dump(),
            "disclaimer": ("Gross estimate from the live contract specification. Excludes spread, "
                           "commission, swap and slippage. Not a profit guarantee.")}


@router.get("/specs")
def specs(runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    settings = get_settings()
    return {"brokers": settings.brokers.get("brokers", [])}
