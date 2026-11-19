from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from services.api_gateway.accounts import (
    AccountError,
    assign_broker_account,
    create_broker_account,
    delete_broker_account,
    get_broker_account,
    list_broker_accounts,
    unassign_broker_account,
    update_broker_account,
)
from services.api_gateway.credential_vault import CredentialVault, VaultError
from services.api_gateway.demo_validation import validate_demo_account
from services.api_gateway.deps import Runtime, current_user, require_admin
from services.api_gateway.state import TradingRuntime

router = APIRouter(prefix="/api/broker-accounts", tags=["broker-accounts"])


class CreateBrokerAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    label: str
    server: str
    account_type: Literal["demo", "live"]
    login: str
    password: str
    validation_symbol: str = "XAUUSD"


class AssignBrokerAccountRequest(BaseModel):
    team_id: str
    manager_email: str
    expected_version: int


class UpdateBrokerAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: float = Field(allow_inf_nan=False)
    label: str | None = Field(default=None, min_length=2, max_length=100)
    server: str | None = Field(default=None, min_length=1, max_length=200)
    account_type: Literal["demo", "live"] | None = None
    validation_symbol: str | None = Field(default=None, min_length=1, max_length=100)
    login: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, max_length=1024)


@router.put("/{account_id}")
def edit_account(account_id: str, payload: UpdateBrokerAccountRequest,
                 runtime: TradingRuntime = Runtime, user=Depends(current_user)):
    changes = payload.model_dump(exclude_none=True, exclude={"expected_updated_at"})
    try:
        return update_broker_account(runtime.db, user["tenant_id"], account_id, user,
                                     payload.expected_updated_at, changes)
    except AccountError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except VaultError as exc:
        raise HTTPException(503, "credential vault unavailable; account was not changed") from exc


@router.delete("/{account_id}")
def remove_account(account_id: str, expected_updated_at: float,
                   runtime: TradingRuntime = Runtime, user=Depends(current_user)):
    try:
        return delete_broker_account(runtime.db, user["tenant_id"], account_id, user, expected_updated_at)
    except AccountError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.get("")
def broker_accounts(runtime: TradingRuntime = Runtime, user=Depends(current_user)):
    return {"accounts": list_broker_accounts(runtime.db, user["tenant_id"], user)}


@router.post("")
def add_broker_account(payload: CreateBrokerAccountRequest,
                       runtime: TradingRuntime = Runtime, user=Depends(current_user)):
    try:
        vault = CredentialVault()
    except VaultError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        account = create_broker_account(
            runtime.db, vault, tenant_id=user["tenant_id"], owner_email=user["email"],
            provider=payload.provider, label=payload.label, server=payload.server,
            account_type=payload.account_type, login=payload.login, password=payload.password,
            created_by=user["email"],
            validation_symbol=payload.validation_symbol,
        )
    except AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    runtime.db.audit(user["email"], "broker_account.create",
                     {"account_id": account["id"], "provider": account["provider"],
                      "account_type": account["account_type"]})
    return account


@router.get("/{account_id}")
def broker_account(account_id: str, runtime: TradingRuntime = Runtime, user=Depends(current_user)):
    account = get_broker_account(runtime.db, user["tenant_id"], account_id, user)
    if account is None:
        raise HTTPException(status_code=404, detail="broker account not found")
    return account


@router.post("/{account_id}/assignment")
def assign(account_id: str, payload: AssignBrokerAccountRequest,
           runtime: TradingRuntime = Runtime, user=Depends(current_user)):
    try:
        account = assign_broker_account(runtime.db, user["tenant_id"], account_id,
                                        payload.team_id, payload.manager_email, user,
                                        payload.expected_version)
    except AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return account


@router.delete("/{account_id}/assignment")
def unassign(account_id: str, expected_version: int,
             runtime: TradingRuntime = Runtime, user=Depends(require_admin)):
    try:
        account = unassign_broker_account(runtime.db, user["tenant_id"], account_id,
                                          user, expected_version)
    except AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return account


@router.post("/{account_id}/validate-demo")
def validate_demo(account_id: str, runtime: TradingRuntime = Runtime,
                  user=Depends(current_user)):
    try:
        result = validate_demo_account(runtime.db, user["tenant_id"], account_id, user,
                                       relay=getattr(runtime, "bridge", None))
    except AccountError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    runtime.db.audit(user["email"], "broker_account.demo.validate",
                     {"account_id": account_id, "symbol": result.get("symbol"),
                      "read_only": True, "execution_enabled": False})
    return result
