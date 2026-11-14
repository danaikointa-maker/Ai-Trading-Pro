"""FastAPI dependencies."""
from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Query, Request, status

from packages.shared_schemas.settings import Settings, get_settings
from services.api_gateway.auth import decode_token
from services.api_gateway.roles import (ADMIN, MUTATING_METHODS, TRADER, at_least,
                                        normalize_role)
from services.api_gateway.state import TradingRuntime


def get_runtime(request: Request) -> TradingRuntime:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:  # pragma: no cover
        raise HTTPException(status_code=503, detail="runtime not ready")
    if getattr(runtime.db, "workspace_id", None) != get_settings().security.get("workspace_id", "local"):
        raise HTTPException(status_code=503, detail="runtime workspace identity mismatch")
    return runtime


def get_settings_dep() -> Settings:
    return get_settings()


async def current_user(request: Request, token: str | None = Query(default=None)) -> dict[str, Any]:
    """Identify the caller from the token, then take their authority from the database.

    The token only says *who* you are. Reading the `users` row on every request is
    what makes "disable this account" and "demote this person" take effect
    immediately instead of whenever their 12-hour token happens to expire.

    The write guard lives here on purpose: every mutating route already depends on
    this function, so a forgotten `Depends` on some future endpoint cannot leave an
    endpoint writable by a read-only account.
    """
    settings: Settings = get_settings()
    runtime = getattr(request.app.state, "runtime", None)
    if (runtime is None or getattr(runtime.db, "workspace_id", None)
            != settings.security.get("workspace_id", "local")):
        raise HTTPException(status_code=503, detail="runtime workspace identity mismatch")
    if not settings.security.get("require_auth", True):
        return {"email": "anonymous", "role": ADMIN, "demo": True}
    header = request.headers.get("authorization", "")
    raw = header[7:] if header.lower().startswith("bearer ") else (token or "")
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    payload = decode_token(settings, raw)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired token")

    email = str(payload.get("sub") or "").lower()
    db = getattr(getattr(request.app.state, "runtime", None), "db", None)
    row = db.query_one("SELECT email, role, active FROM users WHERE email = ?", (email,)) if db else None
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="account no longer exists — sign in again")
    if not bool(row["active"] if row["active"] is not None else 1):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="account is disabled")

    role = normalize_role(row["role"])
    user = {"email": row["email"], "role": role, "token_role": payload.get("role")}

    if request.method in MUTATING_METHODS and not at_least(role, TRADER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"role '{role}' is read-only: {request.method} {request.url.path} "
                   f"needs role '{TRADER}' or '{ADMIN}'")
    return user


def require_role(minimum: str):
    """Dependency factory for endpoints that need more than the write guard."""
    async def _dep(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        if not at_least(user.get("role"), minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role '{user.get('role')}' cannot do this — needs '{minimum}'")
        return user
    return _dep


require_admin = require_role(ADMIN)
require_trader = require_role(TRADER)


User = Depends(current_user)
Runtime = Depends(get_runtime)
