from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from packages.shared_schemas.settings import get_settings
from services.api_gateway.deps import current_user, get_runtime
from services.api_gateway.state import TradingRuntime
from services.market_data.simulator import candles_from_df
from services.risk_engine.planner import points_calculator

router = APIRouter(prefix="/api/market", tags=["market"])


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
            runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    try:
        df = runtime.market.candles(symbol, timeframe, limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    spec = runtime.adapter.symbol_spec(symbol)
    return {"symbol": symbol, "timeframe": timeframe, "spec": spec.model_dump(),
            "candles": [c.model_dump() for c in candles_from_df(df)],
            "ticker": runtime.market.ticker(symbol).model_dump()}


@router.get("/ticker")
def ticker(symbol: str = "XAUUSD", runtime: TradingRuntime = Depends(get_runtime),
           user=Depends(current_user)):
    return runtime.market.ticker(symbol).model_dump()


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
