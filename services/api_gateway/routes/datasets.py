"""Dataset snapshots: list them, pin the current feed, inspect one manifest."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from services.api_gateway.deps import current_user, get_runtime
from services.api_gateway.state import TradingRuntime
from services.market_data.snapshots import (SnapshotError, describe_source, list_snapshots,
                                           load_snapshot, save_snapshot)

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


class SnapshotRequest(BaseModel):
    symbol: str = "XAUUSD"
    timeframe: str = "M1"
    bars: int = Field(default=8000, ge=100, le=100000)
    broker_id: str | None = None


@router.get("")
def snapshots(limit: int = Query(50, ge=1, le=200),
              runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    return {"snapshots": list_snapshots(runtime.settings.paths["datasets"], limit)}


@router.post("")
def pin(payload: SnapshotRequest, runtime: TradingRuntime = Depends(get_runtime),
        user=Depends(current_user)):
    """Freeze the bars the feed serves right now, so a later backtest can be repeated."""
    adapter = runtime.registry.get(payload.broker_id or runtime.adapter.id)
    if payload.symbol not in adapter.symbol_names():
        raise HTTPException(status_code=400, detail=f"unknown symbol {payload.symbol}")
    frame = adapter.candles(payload.symbol, payload.timeframe, payload.bars)
    feed_mode = (getattr(runtime, "feed_mode", None)
                 or runtime.settings.market_data.get("feed_mode", "simulate"))
    source = describe_source(str(feed_mode),
                             seed=runtime.settings.market_data.get("simulation", {}).get("seed"),
                             adapter_id=adapter.id)
    try:
        snapshot = save_snapshot(runtime.settings.paths["datasets"], payload.symbol,
                                 payload.timeframe, frame, source)
    except SnapshotError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    runtime.db.audit(user["email"], "datasets.pin",
                     {"id": snapshot.id, "rows": snapshot.rows, "symbol": snapshot.symbol})
    return snapshot.as_dict()


@router.get("/{snapshot_id}")
def snapshot(snapshot_id: str, runtime: TradingRuntime = Depends(get_runtime),
             user=Depends(current_user)):
    try:
        manifest, frame = load_snapshot(runtime.settings.paths["datasets"], snapshot_id)
    except SnapshotError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {**manifest.as_dict(), "verified": True,
            "sample": frame.head(3).to_dict(orient="records")}
