"""EA bridge endpoints — the wire protocol the MQL5 Expert Advisor speaks.

These are the only routes an EA calls, and they do not use a user JWT: the EA holds a
per-account bridge token, which is checked against the configured one in constant time.
Everything here is about *delivering exactly one* command and learning what happened,
never about re-sending.

Protocol (one round trip per poll interval, ~1s):
    POST /api/bridge/register  -> {session_id, poll_interval_ms, ...}
    POST /api/bridge/poll      -> {commands: [...], results: [...], expired_unacked: [...]}
    GET  /api/bridge/status    -> operator view (admin JWT)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from services.api_gateway.deps import current_user, get_runtime, require_admin
from services.api_gateway.state import TradingRuntime
from services.bridge.relay import BridgeError, BridgeTokenError

router = APIRouter(prefix="/api/bridge", tags=["bridge"])


class RegisterBody(BaseModel):
    account_id: str = Field(min_length=1)
    session_id: str = ""
    terminal: dict[str, Any] = Field(default_factory=dict)
    symbols: list[str] = Field(default_factory=list)


class PollBody(BaseModel):
    session_id: str = Field(min_length=1)
    snapshot: dict[str, Any] | None = None
    results: list[dict[str, Any]] = Field(default_factory=list)


def _token(authorization: str | None) -> str:
    raw = (authorization or "").strip()
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return raw


def _relay(runtime: TradingRuntime):
    relay = getattr(runtime, "bridge", None)
    if relay is None:  # pragma: no cover - runtime always builds one
        raise HTTPException(status_code=503, detail="bridge relay is not available")
    return relay


@router.post("/register")
def register(body: RegisterBody, authorization: str | None = Header(default=None),
             runtime: TradingRuntime = Depends(get_runtime)):
    relay = _relay(runtime)
    try:
        out = relay.register(body.account_id, _token(authorization), body.session_id,
                             terminal=body.terminal, symbols=body.symbols)
    except BridgeTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except BridgeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return out


@router.post("/poll")
def poll(body: PollBody, authorization: str | None = Header(default=None),
         runtime: TradingRuntime = Depends(get_runtime)):
    """Authenticated with the bridge token *and* the session id.

    The session id alone is not enough: a poll can inject quotes/positions and
    acknowledge orders, so guessing one must not be sufficient.
    """
    relay = _relay(runtime)
    token = _token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="bridge token required")
    try:
        return relay.poll(body.session_id, snapshot=body.snapshot, results=body.results,
                          token=token)
    except BridgeTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except BridgeError as exc:
        # 409 so the EA knows to re-register rather than retry the same session forever.
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/status")
def status(runtime: TradingRuntime = Depends(get_runtime), user=Depends(require_admin)):
    """Operator view: who is connected, how fresh, what is queued, what expired."""
    relay = _relay(runtime)
    out = relay.status()
    out["tokens"] = {account: relay.token_fingerprint(account)
                     for account in relay.accounts}
    out["account_roles"] = {"viewer_of_status": user.get("role")}
    return out


@router.post("/cancel")
def cancel_pending(runtime: TradingRuntime = Depends(get_runtime), user=Depends(require_admin)):
    """Drop everything not yet delivered — the money-side kill switch for the queue."""
    relay = _relay(runtime)
    dropped = {account: relay.cancel_pending(account, reason=f"cancelled by {user['email']}")
               for account in relay.accounts}
    runtime.db.audit(user["email"], "bridge.cancel_pending", dropped)
    return {"dropped": dropped}


@router.get("/session")
def my_session(runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
    """Light view for the dashboard: is an EA attached, and how old is its data?"""
    relay = _relay(runtime)
    rows = []
    for adapter in runtime.registry.all():
        if getattr(adapter, "adapter_type", "") != "bridge":
            continue
        account = getattr(adapter, "account_id", adapter.id)
        rows.append({
            "broker_id": adapter.id,
            "account": account,
            "health": adapter.health().value,
            "session_id": (session.session_id if (session := relay.get(account)) else None),
            "last_seen_age_seconds": relay.age(account),
            "snapshot_age_seconds": relay.snapshot_age(account),
            "symbols": getattr(adapter, "symbol_names", lambda: [])(),
        })
    return {"enabled": relay.enabled, "read_only": relay.read_only,
            "require_demo_identity": relay.require_demo_identity, "fresh_seconds": relay.fresh_seconds,
            "stale_seconds": relay.stale_seconds, "bridges": rows}
