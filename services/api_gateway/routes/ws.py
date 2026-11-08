from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from packages.shared_schemas.settings import get_settings
from services.api_gateway.auth import decode_token

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


@router.websocket("/ws/live")
async def live_socket(ws: WebSocket, token: str | None = Query(default=None)):
    settings = get_settings()
    require_auth = bool(settings.security.get("require_auth", True))
    payload = decode_token(settings, token or "") if token else None
    if require_auth and not payload:
        await ws.close(code=WS_UNAUTHORIZED)
        return

    quota = getattr(ws.app.state, "ws_quota", None)
    identity = _identity(ws, payload)
    lease = quota.acquire(identity) if quota is not None else None
    if quota is not None and lease is None:
        # Accept first, then close: a handshake rejection gives the browser nothing to
        # show, while a close code plus one frame tells the client what to fix.
        await ws.accept()
        held, total = quota.counts(identity)
        await ws.send_text(json.dumps({
            "type": "error", "code": WS_OVER_QUOTA,
            "error": "too many open connections",
            "detail": (f"{identity} already holds {held} of {quota.per_identity} live sockets "
                       f"({total} open in total, limit {quota.max_total_label()})"),
        }))
        await ws.close(code=WS_OVER_QUOTA)
        return

    await ws.accept()
    runtime = ws.app.state.runtime
    # A "tick" frame is a light payload without analysis/forecast. Sending only
    # one full frame at connect meant those blocks never refreshed (and, before
    # the client merged frames, they vanished after the first second).
    # The cadence is time based on purpose: `runtime.version` bumps on every tick
    # cycle, so keying off it would send the heavy payload every single second.
    full_every_seconds = float(settings.app.get("ws", {}).get("full_snapshot_seconds", 5))
    # Renew well before the lease expires, so one slow payload cannot drop the slot.
    renew_every = max(2.0, (lease.expires_at - time.time()) / 3) if lease else 1e9
    try:
        full = True
        last_full = 0.0
        last_renew = time.time()
        while True:
            now = time.time()
            # A token that expires mid-stream must end the stream: without this the
            # socket outlives the credential that opened it, for as long as it stays up.
            if payload and payload.get("exp") and now >= float(payload["exp"]):
                await ws.close(code=WS_UNAUTHORIZED)
                return
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
