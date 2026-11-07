from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from packages.shared_schemas.settings import get_settings
from services.api_gateway.netutil import client_ip, parse_networks
from services.api_gateway.auth import LoginThrottle, authenticate, ensure_demo_user
from services.api_gateway.deps import current_user, get_runtime
from services.api_gateway.state import TradingRuntime

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


def _client_ip(request: Request) -> str:
    """Behind a proxy the socket address is the proxy; the first XFF hop is the client.

    Only a *trusted* peer may supply that hop. Trusting it unconditionally let anyone
    reset the password-guessing throttle by rotating one header per attempt.
    """
    settings = get_settings()
    trusted = parse_networks(settings.trusted_proxies)
    return client_ip(request.scope, trusted)


def _throttle(runtime: TradingRuntime) -> LoginThrottle:
    security = get_settings().security
    return LoginThrottle(
        runtime.db,
        max_failures=int(security.get("login_max_failures", 5)),
        window_seconds=int(security.get("login_window_seconds", 900)),
        lock_seconds=int(security.get("login_lock_seconds", 300)),
        max_lock_seconds=int(security.get("login_max_lock_seconds", 3600)),
    )


@router.post("/login")
def login(payload: LoginRequest, request: Request,
          runtime: TradingRuntime = Depends(get_runtime)):
    settings = get_settings()
    ensure_demo_user(runtime.db, settings)
    throttle = _throttle(runtime)
    key = throttle.key_for(payload.email, _client_ip(request))

    locked, retry_after = throttle.check(key)
    if locked:
        runtime.db.audit(payload.email, "auth.throttled", {"retry_after": retry_after})
        raise HTTPException(status_code=429, detail="too many failed attempts",
                            headers={"Retry-After": str(retry_after)})

    result = authenticate(runtime.db, settings, payload.email, payload.password)
    if not result:
        # The attempt that reaches the limit still answers 401; the *next* one is
        # refused by the check above, so a legitimate typo never looks like a ban.
        lock = throttle.register_failure(key)
        runtime.db.audit(payload.email, "auth.failed", {"locked_for": lock})
        raise HTTPException(status_code=401, detail="invalid email or password")
    throttle.reset(key)
    # Never echo the configured credentials back: the response ends up in
    # browser devtools, proxy logs and screenshots.
    return result


@router.get("/me")
def me(user=Depends(current_user)):
    return {"user": user}
