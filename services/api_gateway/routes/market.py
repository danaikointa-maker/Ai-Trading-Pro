from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from packages.shared_schemas.settings import get_settings
from services.api_gateway.deps import current_user, get_runtime
from services.api_gateway.state import TradingRuntime
from services.market_data.simulator import candles_from_df
from services.market_data.service import StaleDataError
from services.risk_engine.planner import points_calculator

router = APIRouter(prefix="/api/market", tags=["market"])


class MT5MarketSnapshot(BaseModel):
    """Data-only PC publisher payload. Trading/account state has no schema here."""
    model_config = ConfigDict(extra="forbid")
    identity: dict
    captured_at: float
    time_basis: Literal["utc", "broker_server"] = "broker_server"
    server_time: float
    utc_time: float
    quotes: dict
    rates: dict = Field(default_factory=dict)
    specs: dict = Field(default_factory=dict)


@router.post("/publish/mt5")
def publish_mt5_market(body: MT5MarketSnapshot,
                       authorization: str | None = Header(default=None),
                       runtime: TradingRuntime = Depends(get_runtime)):
    cfg = runtime.market.publisher
    expected = str(cfg.get("token") or "")
    raw = (authorization or "").strip()
    token = raw[7:].strip() if raw.lower().startswith("bearer ") else raw
    if (not cfg.get("enabled") or not expected or not cfg.get("expected_login")
            or not cfg.get("expected_server") or not cfg.get("symbols")):
        raise HTTPException(status_code=503, detail="MT5 market publisher is disabled")
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="invalid market publisher credential")
    try:
        return runtime.market.publish_mt5_snapshot(body.model_dump())
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/symbols")
def symbols(runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    out = []
    for name in runtime.symbols():
        spec = runtime.market.spec(name)
        out.append({"symbol": name, "description": spec.description, "digits": spec.digits,
                    "point": spec.point, "contract_size": spec.contract_size,
                    "spread_typical_points": spec.spread_typical_points,
                    "value_per_point_per_lot": spec.value_per_point_per_lot})
    return {"symbols": out, "broker_id": runtime.adapter.id}


@router.get("/candles")
def candles(symbol: str = "XAUUSD", timeframe: str = "M5", limit: int = Query(400, ge=20, le=2000),
            runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    try:
        df = runtime.market.candles(symbol, timeframe, limit)
    except StaleDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    spec = runtime.market.spec(symbol)
    time_info = (runtime.market.timestamp_metadata()
                 if hasattr(runtime.market, "timestamp_metadata")
                 else runtime.adapter.timestamp_metadata()
                 if hasattr(runtime.adapter, "timestamp_metadata")
                 else {"basis": "utc", "display_basis": "utc",
                       "server_utc_offset_seconds": 0})
    return {"symbol": symbol, "timeframe": timeframe, "spec": spec.model_dump(),
            "candles": [c.model_dump() for c in candles_from_df(df)],
            "ticker": runtime.market.ticker(symbol).model_dump(), "time": time_info}


@router.get("/ticker")
def ticker(symbol: str = "XAUUSD", runtime: TradingRuntime = Depends(get_runtime),
           user=Depends(current_user)):
    quote = runtime.market.latest_quote(symbol)
    if quote is None:
        raise HTTPException(status_code=503, detail="no quote available")
    return quote


@router.get("/spec")
def spec(symbol: str = "XAUUSD", broker_id: str | None = None,
         runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    return runtime.market.spec(symbol, broker_id).model_dump()


@router.get("/calculator")
def calculator(symbol: str = "XAUUSD", points: float = 750, lot: float = 0.01,
               runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    spec_obj = runtime.market.spec(symbol)
    return {"result": points_calculator(spec_obj, points, lot), "spec": spec_obj.model_dump(),
            "disclaimer": ("Uses the current runtime market specification, not an account-specific terminal link. "
                           "net_profit deducts commission only; spread_cost is reported separately and is not "
                           "deducted. Swap and slippage are excluded. Not a profit guarantee.")}


@router.get("/specs")
def specs(runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    settings = get_settings()
    return {"brokers": settings.brokers.get("brokers", [])}
