from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from packages.shared_schemas.settings import get_settings
from services.api_gateway.deps import current_user, get_runtime
from services.api_gateway.state import TradingRuntime

router = APIRouter(prefix="/api/brokers", tags=["brokers"])


@router.get("")
def list_brokers(runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    settings = get_settings()
    return {
        "brokers": runtime.registry.describe_all(),
        "active": runtime.adapter.id,
        "profiles": settings.brokers.get("brokers", []),
        "note": ("Broker profiles are declared in config/brokers.yaml. Symbol specifications come from the "
                 "connected terminal when available, otherwise from the declared contract specs."),
    }


@router.post("/{broker_id}/activate")
def activate(broker_id: str, runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    try:
        adapter = runtime.registry.set_active(broker_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    runtime.db.audit(user["email"], "broker.activate", {"broker_id": broker_id})
    runtime.market.invalidate()
    return {"ok": True, "active": adapter.id, "health": adapter.health().value,
            "symbols": adapter.symbol_names(), "account": adapter.account_info().model_dump()}


@router.get("/{broker_id}/symbols")
def symbols(broker_id: str, runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    adapter = runtime.registry.get(broker_id)
    out = []
    for name in adapter.symbol_names():
        spec = adapter.symbol_spec(name)
        out.append(spec.model_dump())
    return {"broker_id": broker_id, "symbols": out}


@router.get("/{broker_id}/account")
def account(broker_id: str, runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    return runtime.registry.get(broker_id).account_info().model_dump()


@router.get("/{broker_id}/health")
def health(broker_id: str, runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    adapter = runtime.registry.get(broker_id)
    return {"broker_id": broker_id, "health": adapter.health().value,
            "adapter": adapter.adapter_type, "last_reconcile": runtime.last_reconcile}
