"""User management (admin only).

Creating accounts, changing roles and disabling people are exactly the operations a
compromised trader account must not be able to perform, so every route here depends
on `require_admin` rather than the ordinary login check.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from packages.shared_schemas.settings import get_settings
from services.api_gateway.deps import current_user, get_runtime, require_admin
from services.api_gateway.roles import describe_roles
from services.api_gateway.state import TradingRuntime
from services.api_gateway.users import (UserError, create_user, delete_user, list_users,
                                        update_user)

router = APIRouter(prefix="/api/users", tags=["users"])


class CreateUserRequest(BaseModel):
    email: str
    password: str
    role: str = "viewer"


class UpdateUserRequest(BaseModel):
    role: str | None = None
    active: bool | None = None
    password: str | None = None


@router.get("")
def users(runtime: TradingRuntime = Depends(get_runtime), user=Depends(require_admin)):
    return {"users": list_users(runtime.db), "roles": describe_roles(),
            "require_auth": bool(get_settings().security.get("require_auth", True))}


@router.post("")
def add(payload: CreateUserRequest, runtime: TradingRuntime = Depends(get_runtime),
        user=Depends(require_admin)):
    try:
        created = create_user(runtime.db, payload.email, payload.password, payload.role)
    except UserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    runtime.db.audit(user["email"], "users.create",
                     {"email": created["email"], "role": created["role"]})
    return created


@router.patch("/{email}")
def edit(email: str, payload: UpdateUserRequest, runtime: TradingRuntime = Depends(get_runtime),
         user=Depends(require_admin)):
    try:
        updated = update_user(runtime.db, email, role=payload.role, active=payload.active,
                              password=payload.password)
    except UserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    changed: dict[str, Any] = {key: value for key, value in payload.model_dump().items()
                               if value is not None and key != "password"}
    if payload.password is not None:
        changed["password"] = "changed"
    runtime.db.audit(user["email"], "users.update", {"email": updated["email"], **changed})
    return updated


@router.delete("/{email}")
def remove(email: str, runtime: TradingRuntime = Depends(get_runtime),
           user=Depends(require_admin)):
    if email.strip().lower() == str(user["email"]).lower():
        raise HTTPException(status_code=400,
                            detail="you cannot delete the account you are signed in as")
    try:
        delete_user(runtime.db, email)
    except UserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    runtime.db.audit(user["email"], "users.delete", {"email": email.strip().lower()})
    return {"ok": True, "deleted": email.strip().lower()}


@router.get("/me/permissions")
def my_permissions(user=Depends(current_user)):
    """What this account may do — the UI uses it to disable buttons honestly."""
    from services.api_gateway.roles import ADMIN, ROLE_RANK, TRADER, VIEWER

    role = user.get("role", VIEWER)
    rank = ROLE_RANK.get(role, 1)
    return {
        "email": user.get("email"),
        "role": role,
        "can_trade": rank >= ROLE_RANK[TRADER],
        "can_manage_users": rank >= ROLE_RANK[ADMIN],
        "roles": describe_roles(),
    }
