"""Dataset snapshots: list them, pin the current feed, inspect one manifest."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from services.api_gateway.deps import current_user, get_runtime, require_admin
from services.api_gateway.state import TradingRuntime
from services.market_data.snapshots import (SnapshotError, describe_source, list_snapshots,
                                           load_snapshot, save_snapshot)
from services.market_data.tick_store import (TickStoreError, available_days, coverage,
                                             prune_days, symbol_dir)
from services.market_data.ticks import tick_layout, tick_summary

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


def _tick_symbols(datasets: Path, symbol: str) -> list[str]:
    """Every symbol with stored ticks, in either layout — not just the legacy one."""
    if symbol:
        symbol_dir(datasets, symbol)
        return [symbol.upper()]
    # Validate the root and ancestors before enumerating any foreign directory.
    symbol_dir(datasets, "INVENTORY")
    names = {p.name[:-len("_ticks.json")] for p in (datasets / "ticks").glob("*_ticks.json")} \
        if (datasets / "ticks").exists() else set()
    folder = datasets / "ticks"
    if folder.is_dir():
        names.update(p.name for p in folder.iterdir() if p.is_dir())
    return sorted(names)


@router.get("/ticks/status")
def tick_status(symbol: str = Query("", description="empty = every symbol with ticks"),
                runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    """Is real tick data available, and exactly which days does it cover?

    Backtests use ticks to settle bars that touch both the stop and a target; this is
    how you find out whether that is happening or whether the conservative
    stop-first assumption is still in force. `gaps` lists interior days with no file,
    which is the difference between "we have ticks" and "we have ticks everywhere".
    """
    datasets = runtime.settings.paths["datasets"]
    out = []
    for name in _tick_symbols(datasets, symbol):
        try:
            layout = tick_layout(datasets, name)
            manifest = tick_summary(datasets, name)
            cov = coverage(datasets, name)
        except TickStoreError:
            out.append({"symbol": name.upper(), "available": False, "layout": None,
                        "status": "quarantined", "reason": "tick artifact validation failed"})
            continue
        if manifest is None or layout is None:
            out.append({"symbol": name.upper(), "available": False, "layout": None})
            continue
        days = [d["day"] for d in cov["days"]]
        gaps: list[str] = []
        if len(days) > 1:
            span = pd.date_range(days[0], days[-1], freq="D").strftime("%Y-%m-%d")
            gaps = [d for d in span if d not in set(days)]
        out.append({
            "symbol": name.upper(),
            "available": True,
            "layout": layout,
            "format": (cov["days"][0]["format"] if cov["days"] else None),
            "rows": cov["rows"],
            "days_covered": cov["days_covered"],
            "first_t": cov["first_t"],
            "last_t": cov["last_t"],
            "first_iso": _iso(cov["first_t"]),
            "last_iso": _iso(cov["last_t"]),
            "days": cov["days"],
            "gaps": gaps,
            "rows_loaded": 0,   # nothing is read to answer this: the manifest is enough
            "source": (manifest or {}).get("source", {}).get("file"),
            "dropped": (manifest or {}).get("dropped", {}),
            "stored_rows": (manifest or {}).get("stored_rows", cov["rows"]),
        })
    return {"ticks": out, "used_for_intra_bar_ordering": any(t["available"] for t in out)}


def _iso(epoch: int | None) -> str | None:
    if epoch is None:
        return None
    return pd.Timestamp(int(epoch), unit="s", tz="UTC").isoformat()


def _referenced_days(runtime: TradingRuntime) -> dict[str, set[str]]:
    """Days a stored backtest actually read, per symbol — pruning must not break them."""
    used: dict[str, set[str]] = {}
    for row in runtime.db.query("SELECT payload FROM backtests"):
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError, IndexError):
            continue
        ticks = ((payload.get("dataset") or {}).get("ticks") or {})
        days = ticks.get("days_used") or []
        symbol = str(ticks.get("symbol") or payload.get("symbol") or "").upper()
        if symbol and days:
            used.setdefault(symbol, set()).update(str(d) for d in days)
    return used


@router.post("/ticks/prune")
def prune_tick_days(symbol: str = Query(..., description="symbol to prune"),
                    keep_days: int = Query(..., ge=1, le=3650,
                                           description="newest N days to keep"),
                    force: bool = Query(False, description="delete even days a backtest used"),
                    runtime: TradingRuntime = Depends(get_runtime),
                    user=Depends(require_admin)):
    """Delete the oldest daily tick files. Admin only, audited, and refused by default
    when a stored backtest read one of those days — deleting it would make that
    report unreproducible."""
    datasets = runtime.settings.paths["datasets"]
    name = symbol.upper()
    if tick_layout(datasets, name) != "daily":
        raise HTTPException(status_code=400,
                            detail=f"no daily tick files for {name}; nothing to prune")
    days = available_days(datasets, name)
    doomed = days[:-keep_days] if len(days) > keep_days else []
    referenced = sorted(set(doomed) & _referenced_days(runtime).get(name, set()))
    if referenced and not force:
        raise HTTPException(
            status_code=409,
            detail=f"refusing to delete {referenced}: stored backtests read these days. "
                   f"Re-run those backtests or pass force=true.")
    try:
        result = prune_days(datasets, name, keep_days)
    except TickStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    runtime.db.audit(user["email"], "datasets.ticks_prune",
                     {"symbol": name, "keep_days": keep_days, "removed": len(result["removed"]),
                      "forced": bool(force), "referenced": referenced})
    return {"symbol": name, "keep_days": keep_days, **result,
            "rows_after": coverage(datasets, name)["rows"]}


@router.get("/{snapshot_id}")
def snapshot(snapshot_id: str, runtime: TradingRuntime = Depends(get_runtime),
             user=Depends(current_user)):
    try:
        manifest, frame = load_snapshot(runtime.settings.paths["datasets"], snapshot_id)
    except SnapshotError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {**manifest.as_dict(), "verified": True,
            "sample": frame.head(3).to_dict(orient="records")}
