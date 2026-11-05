"""FastAPI dependencies."""
from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Query, Request, status

from packages.shared_schemas.settings import Settings, get_settings
from services.api_gateway.auth import decode_token
from services.api_gateway.state import TradingRuntime


def get_runtime(request: Request) -> TradingRuntime:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:  # pragma: no cover
        raise HTTPException(status_code=503, detail="runtime not ready")
    return runtime


def get_settings_dep() -> Settings:
    return get_settings()


async def current_user(request: Request, token: str | None = Query(default=None)) -> dict[str, Any]:
    settings: Settings = get_settings()
    if not settings.security.get("require_auth", True):
        return {"email": "anonymous", "role": "demo"}
    header = request.headers.get("authorization", "")
    raw = header[7:] if header.lower().startswith("bearer ") else (token or "")
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    payload = decode_token(settings, raw)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired token")
    return {"email": payload.get("sub"), "role": payload.get("role", "trader")}


User = Depends(current_user)
Runtime = Depends(get_runtime)
