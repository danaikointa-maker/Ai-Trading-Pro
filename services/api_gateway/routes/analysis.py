from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from services.api_gateway.deps import current_user, get_runtime
from services.api_gateway.state import TradingRuntime

router = APIRouter(prefix="/api", tags=["analysis"])


@router.get("/analysis/{symbol}")
def analysis(symbol: str, fresh: bool = False, runtime: TradingRuntime = Depends(get_runtime),
             user=Depends(current_user)):
    try:
        ctx = runtime.analysis.snapshot(symbol) if fresh else runtime.ensure_analysis(symbol)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "snapshot": ctx.snapshot.model_dump(),
        "structure_bias": ctx.bias.value,
        "bias_confidence": round(ctx.bias_confidence, 3),
        "alignment": round(ctx.alignment, 3),
        "alignment_notes": ctx.alignment_notes,
        "supports": [z.model_dump() for z in ctx.snapshot.supports],
        "resistances": [z.model_dump() for z in ctx.snapshot.resistances],
    }


@router.get("/analysis/{symbol}/zones")
def zones(symbol: str, runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    ctx = runtime.ensure_analysis(symbol)
    return {
        "price": ctx.snapshot.price,
        "atr_points": ctx.snapshot.indicators.atr_points,
        "zones": [z.model_dump() for z in ctx.snapshot.zones],
        "supports": [z.model_dump() for z in ctx.snapshot.supports],
        "resistances": [z.model_dump() for z in ctx.snapshot.resistances],
        "rules": {
            "min_independent_families": runtime.analysis.zone_cfg.high_quality_min_families,
            "confirmed_only": True,
            "note": "Candidate zones are projections without a closed-candle retest and are labelled as such.",
        },
    }


@router.get("/forecast/{symbol}")
def forecast(symbol: str, runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    bundle = runtime.forecast_for(symbol)
    if bundle is None:
        raise HTTPException(status_code=503, detail="forecast unavailable")
    return bundle.model_dump()


@router.get("/forecast")
def forecast_status(runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    return {
        "active": runtime.predictor.status().model_dump() if runtime.predictor.status() else None,
        "version": runtime.predictor.version,
        "approved": runtime.predictor.approved,
        "notes": runtime.predictor.notes,
        "training": runtime.training,
        "models": [m.model_dump() for m in runtime.model_registry.list()],
    }


@router.post("/forecast/train")
def train(payload: dict | None = None, runtime: TradingRuntime = Depends(get_runtime),
          user=Depends(current_user)):
    payload = payload or {}
    result = runtime.train_async(payload.get("symbol", runtime.active_symbol),
                                 force=bool(payload.get("force", True)))
    runtime.db.audit(user["email"], "model.train", payload)
    return result


@router.post("/forecast/models/{version}/approve")
def approve(version: str, payload: dict | None = None, runtime: TradingRuntime = Depends(get_runtime),
            user=Depends(current_user)):
    approved = True if payload is None else bool(payload.get("approved", True))
    runtime.model_registry.approve(version, approved)
    if approved:
        runtime.predictor.load_latest()
    return {"ok": True, "version": version, "approved": approved,
            "note": "Approval is a research action; the full-auto gate still requires every OOS check to pass."}
