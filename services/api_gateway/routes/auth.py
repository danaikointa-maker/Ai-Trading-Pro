from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from packages.shared_schemas.settings import get_settings
from services.api_gateway.auth import authenticate, ensure_demo_user
from services.api_gateway.deps import current_user, get_runtime
from services.api_gateway.state import TradingRuntime

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(payload: LoginRequest, runtime: TradingRuntime = Depends(get_runtime)):
    settings = get_settings()
    ensure_demo_user(runtime.db, settings)
    result = authenticate(runtime.db, settings, payload.email, payload.password)
    if not result:
        runtime.db.audit(payload.email, "auth.failed", {})
        raise HTTPException(status_code=401, detail="invalid email or password")
    # Never echo the configured credentials back: the response ends up in
    # browser devtools, proxy logs and screenshots.
    return result


@router.get("/me")
def me(user=Depends(current_user)):
    return {"user": user}
