from __future__ import annotations

import json
import threading
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from packages.shared_schemas.models import BacktestRequest
from services.backtest_engine.backtester import MIN_M1_BARS
from services.market_data.snapshots import (SnapshotError, bar_data_note, describe_source,
                                           load_snapshot, save_snapshot)
from services.api_gateway.deps import current_user, get_runtime
from services.api_gateway.state import TradingRuntime

router = APIRouter(prefix="/api/backtests", tags=["backtest"])
JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()
MAX_JOBS = 40  # finished jobs are kept only long enough for a client to poll them


def _prune_jobs() -> None:
    """Drop the oldest finished jobs so a long-running server cannot leak them."""
    if len(JOBS) <= MAX_JOBS:
        return
    finished = [(k, v) for k, v in JOBS.items() if v.get("state") in ("done", "error")]
    finished.sort(key=lambda kv: float(kv[1].get("started_at") or 0))
    for key, _ in finished[: len(JOBS) - MAX_JOBS]:
        JOBS.pop(key, None)


def _run_job(job_id: str, runtime: TradingRuntime, request: BacktestRequest, actor: str) -> None:
    from services.backtest_engine.backtester import Backtester

    with _LOCK:
        _prune_jobs()
        JOBS[job_id] = {"state": "running", "pct": 10, "message": "loading history",
                        "started_at": time.time()}
    try:
        broker_id = request.broker_id or runtime.adapter.id
        adapter = runtime.registry.get(broker_id)
        spec = adapter.symbol_spec(request.symbol)
        datasets_dir = runtime.settings.paths["datasets"]
        feed_mode = (getattr(runtime, "feed_mode", None)
                     or runtime.settings.market_data.get("feed_mode", "simulate"))
        source = describe_source(str(feed_mode),
                                 seed=runtime.settings.market_data.get("simulation", {}).get("seed"),
                                 adapter_id=adapter.id)

        if request.snapshot_id:
            # Reproduce: same bars, verified against the recorded hash.
            snapshot, m1 = load_snapshot(datasets_dir, request.snapshot_id)
            source = snapshot.source
            symbol = snapshot.symbol
            request = request.model_copy(update={"symbol": symbol, "bars": snapshot.rows})
            spec = adapter.symbol_spec(symbol)
            with _LOCK:
                JOBS[job_id].update(pct=25, message=f"replaying snapshot {snapshot.id}")
        else:
            m1 = adapter.candles(request.symbol, "M1", request.bars)
            symbol = request.symbol
            snapshot = save_snapshot(datasets_dir, symbol, "M1", m1, source)

        with _LOCK:
            JOBS[job_id].update(pct=35, message="replaying bars through the decision engine")
        engine = Backtester(runtime.settings, runtime.risk, runtime.planner)
        report = engine.run(m1, spec, request, broker_id,
                            data_note=bar_data_note(source),
                            dataset={**snapshot.as_dict(),
                                     "feed_mode": feed_mode,
                                     "reproducible": True,
                                     "reproduce_with": {"snapshot_id": snapshot.id}})
        runtime.db.execute(
            "INSERT OR REPLACE INTO backtests(id, created_at, symbol, strategy, payload) VALUES(?,?,?,?,?)",
            (report.id, report.created_at, report.symbol, report.strategy,
             json.dumps(report.model_dump(), default=str)),
        )
        runtime.db.audit(actor, "backtest.run", {"id": report.id, "bars": report.bars,
                                                "trades": report.metrics.trades})
        with _LOCK:
            JOBS[job_id] = {"state": "done", "pct": 100, "message": "finished",
                            "started_at": JOBS.get(job_id, {}).get("started_at", time.time()),
                            "report_id": report.id, "metrics": report.metrics.model_dump(),
                            "verdict": report.verdict}
    except Exception as exc:  # noqa: BLE001
        with _LOCK:
            JOBS[job_id] = {"state": "error", "pct": 0, "message": str(exc)}


@router.post("")
def run(request: BacktestRequest, runtime: TradingRuntime = Depends(get_runtime),
        user=Depends(current_user)):
    if not request.snapshot_id and request.bars < MIN_M1_BARS:
        raise HTTPException(
            status_code=400,
            detail=f"bars={request.bars} is too few: the engine needs at least {MIN_M1_BARS} "
                   f"M1 bars to warm up 320 M5 bars. Raise `bars` or pass a `snapshot_id`.")
    if request.snapshot_id:
        # Fail here rather than inside the worker: a missing or edited snapshot is
        # a user-visible error, not a mysterious job that never finishes.
        try:
            load_snapshot(runtime.settings.paths["datasets"], request.snapshot_id)
        except SnapshotError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    job_id = f"JOB-{uuid.uuid4().hex[:8].upper()}"
    threading.Thread(target=_run_job, args=(job_id, runtime, request, user["email"]), daemon=True).start()
    return {"job_id": job_id, "state": "started"}


@router.get("/jobs/{job_id}")
def job(job_id: str, runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    with _LOCK:
        data = JOBS.get(job_id)
    if data is None:
        raise HTTPException(status_code=404, detail="job not found")
    return data


@router.get("")
def list_reports(limit: int = Query(20, ge=1, le=100), runtime: TradingRuntime = Depends(get_runtime),
                 user=Depends(current_user)):
    rows = runtime.db.query("SELECT id, created_at, symbol, strategy, payload FROM backtests "
                            "ORDER BY created_at DESC LIMIT ?", (limit,))
    out = []
    for row in rows:
        try:
            data = json.loads(row["payload"])
        except json.JSONDecodeError:
            continue
        out.append({"id": data.get("id"), "created_at": data.get("created_at"),
                    "symbol": data.get("symbol"), "strategy": data.get("strategy"),
                    "bars": data.get("bars"), "metrics": data.get("metrics"),
                    "verdict": data.get("verdict")})
    return {"reports": out}


@router.get("/{report_id}")
def get_report(report_id: str, runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    row = runtime.db.query_one("SELECT payload FROM backtests WHERE id = ?", (report_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="report not found")
    return json.loads(row["payload"])
