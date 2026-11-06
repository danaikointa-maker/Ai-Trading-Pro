from __future__ import annotations

import json
import threading
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from packages.shared_schemas.models import BacktestRequest
from services.api_gateway.deps import current_user, get_runtime
from services.api_gateway.state import TradingRuntime

router = APIRouter(prefix="/api/backtests", tags=["backtest"])
JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


def _run_job(job_id: str, runtime: TradingRuntime, request: BacktestRequest, actor: str) -> None:
    from services.backtest_engine.backtester import Backtester

    with _LOCK:
        JOBS[job_id] = {"state": "running", "pct": 10, "message": "loading history", "started_at": time.time()}
    try:
        broker_id = request.broker_id or runtime.adapter.id
        adapter = runtime.registry.get(broker_id)
        spec = adapter.symbol_spec(request.symbol)
        m1 = adapter.candles(request.symbol, "M1", request.bars)
        with _LOCK:
            JOBS[job_id].update(pct=35, message="replaying bars through the decision engine")
        engine = Backtester(runtime.settings, runtime.risk, runtime.planner)
        report = engine.run(m1, spec, request, broker_id)
        runtime.db.execute(
            "INSERT OR REPLACE INTO backtests(id, created_at, symbol, strategy, payload) VALUES(?,?,?,?,?)",
            (report.id, report.created_at, report.symbol, report.strategy,
             json.dumps(report.model_dump(), default=str)),
        )
        runtime.db.audit(actor, "backtest.run", {"id": report.id, "bars": report.bars,
                                                "trades": report.metrics.trades})
        with _LOCK:
            JOBS[job_id] = {"state": "done", "pct": 100, "message": "finished",
                            "report_id": report.id, "metrics": report.metrics.model_dump(),
                            "verdict": report.verdict}
    except ValueError as exc:
        # Bad input (too few bars, unknown symbol) is the caller's problem, not a crash.
        with _LOCK:
            JOBS[job_id] = {"state": "error", "pct": 100, "message": str(exc),
                            "finished_at": time.time()}
        runtime.db.audit(actor, "backtest.error", {"bars": request.bars, "error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        with _LOCK:
            JOBS[job_id] = {"state": "error", "pct": 0, "message": str(exc)}


@router.post("")
def run(request: BacktestRequest, runtime: TradingRuntime = Depends(get_runtime),
        user=Depends(current_user)):
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
