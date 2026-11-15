from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.api_gateway.deps import get_runtime, require_platform_super_admin
from services.api_gateway.state import TradingRuntime
from services.api_gateway.tenants import TenantError, create_tenant, list_tenants, set_tenant_status

router = APIRouter(prefix="/api/platform", tags=["platform"])


class CreateTenantRequest(BaseModel):
    name: str
    admin_email: str
    admin_password: str


class TenantStatusRequest(BaseModel):
    status: Literal["active", "suspended"]


@router.get("/tenants")
def tenants(runtime: TradingRuntime = Depends(get_runtime),
            user=Depends(require_platform_super_admin)):
    return {"tenants": list_tenants(runtime.db)}


@router.post("/tenants")
def add_tenant(payload: CreateTenantRequest, runtime: TradingRuntime = Depends(get_runtime),
               user=Depends(require_platform_super_admin)):
    try:
        created = create_tenant(runtime.db, payload.name, payload.admin_email,
                                payload.admin_password, user["email"])
    except TenantError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    runtime.db.audit(user["email"], "platform.tenant.create",
                     {"tenant_id": created["tenant"]["id"],
                      "admin_email": created["admin"]["email"]})
    return created


@router.patch("/tenants/{tenant_id}")
def edit_tenant(tenant_id: str, payload: TenantStatusRequest,
                runtime: TradingRuntime = Depends(get_runtime),
                user=Depends(require_platform_super_admin)):
    try:
        tenant = set_tenant_status(runtime.db, tenant_id, payload.status)
    except TenantError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    runtime.db.audit(user["email"], "platform.tenant.status",
                     {"tenant_id": tenant_id, "status": tenant["status"]})
    return tenant