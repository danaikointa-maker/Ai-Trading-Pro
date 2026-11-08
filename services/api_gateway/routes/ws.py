from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from packages.shared_schemas.settings import get_settings
from services.api_gateway.auth import decode_token
from services.api_gateway.roles import normalize_role

router = APIRouter(tags=["websocket"])

# Close codes in the private range (4000-4999) so a client can tell them apart:
WS_UNAUTHORIZED = 4401   # no usable token at connect, or it expired while streaming
WS_OVER_QUOTA = 4429     # too many live sockets for this identity (or in total)


def _identity(ws: WebSocket, payload: dict | None) -> str:
    """Who is being charged for this socket.

    The account when there is one — an authenticated user is the thing worth limiting,
    and NAT means many people can share an address. Falls back to the peer address
    when auth is switched off, so an open deployment still cannot be flooded by one host.
    """
    if payload and payload.get("sub"):
        return f"user:{payload['sub']}"
    client = ws.client
    return f"ip:{client.host if client else 'unknown'}"


def _authority(runtime, settings, token):
    """Return a current identity/role, or a close code. Never trust token roles."""
    if not settings.security.get("require_auth", True):
        return ("anonymous", "anonymous"), None
    payload = decode_token(settings, token or "")
    if not payload or not payload.get("sub"):
        return None, 4401
    try:
        row = runtime.db.query_one("SELECT email, role, active FROM users WHERE email = ?",
                                   (str(payload["sub"]).lower(),))
    except Exception:  # noqa: BLE001 - no frames when authority cannot be verified
        return None, 1011
    if row is None:
        return None, 4401
    if not bool(row["active"] if row["active"] is not None else 1):
        return None, 4403
    return (row["email"], normalize_role(row["role"])), None


@router.websocket("/ws/live")
async def live_socket(ws: WebSocket, token: str | None = Query(default=None)):
    settings = get_settings()
    runtime = ws.app.state.runtime
    authority, code = await asyncio.to_thread(_authority, runtime, settings, token)
    if code:
        await ws.close(code=code)
        return
    quota = getattr(ws.app.state, "ws_quota", None)
    payload = {"sub": authority[0]} if settings.security.get("require_auth", True) else None
    quota_identity = _identity(ws, payload) if quota is not None else ""
    lease = quota.acquire(quota_identity) if quota is not None else None
    if quota is not None and lease is None:
        await ws.accept()
        held, total = quota.counts(quota_identity)
        await ws.send_text(json.dumps({
            "type": "error", "code": WS_OVER_QUOTA,
            "error": "too many open connections",
            "detail": (f"{quota_identity} already holds {held} of {quota.per_identity} live sockets "
                       f"({total} open in total, limit {quota.max_total_label()})"),
        }))
        await ws.close(code=WS_OVER_QUOTA)
        return
    # A "tick" frame is a light payload without analysis/forecast. Sending only
    # one full frame at connect meant those blocks never refreshed (and, before
    # the client merged frames, they vanished after the first second).
    # The cadence is time based on purpose: `runtime.version` bumps on every tick
    # cycle, so keying off it would send the heavy payload every single second.
    try:
        full_every_seconds = float(settings.app.get("ws", {}).get("full_snapshot_seconds", 5))
        # Configuration/accept failures must release the reserved lease too.
        renew_every = max(2.0, (lease.expires_at - time.time()) / 3) if lease else 1e9
        await ws.accept()
        full = True
        last_full = 0.0
        last_renew = time.time()
        while True:
            current, code = await asyncio.to_thread(_authority, runtime, settings, token)
            if code or current != authority:
                await ws.close(code=code or 4403)
                return
            now = time.time()
            if lease is not None and now - last_renew >= renew_every:
                if not quota.renew(lease):
                    await ws.close(code=WS_OVER_QUOTA)
                    return
                last_renew = now
            if full or (now - last_full) >= full_every_seconds:
                data = await asyncio.to_thread(runtime.live_payload, False)
                data["type"] = "snapshot"
                full, last_full = False, now
            else:
                data = await asyncio.to_thread(runtime.live_payload, True)
                data["type"] = "tick"
            # Payload generation can take time; recheck immediately before disclosure.
            current, code = await asyncio.to_thread(_authority, runtime, settings, token)
            if code or current != authority:
                await ws.close(code=code or 4403)
                return
            await ws.send_text(json.dumps(data, default=str))
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return
    except Exception:  # noqa: BLE001
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
    finally:
        # Every exit path, including the ones above that `return`: a slot that is not
        # released here is only freed when its lease expires, and that is a slot the
        # user cannot use in the meantime.
        if quota is not None and lease is not None:
            quota.release(lease)


@router.websocket("/ws")
async def alias_socket(ws: WebSocket, token: str | None = Query(default=None)):
    await live_socket(ws, token)
