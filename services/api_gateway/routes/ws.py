from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from packages.shared_schemas.settings import get_settings
from services.api_gateway.auth import decode_token
from services.api_gateway.roles import normalize_role

router = APIRouter(tags=["websocket"])


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
    identity, code = await asyncio.to_thread(_authority, runtime, settings, token)
    if code:
        await ws.close(code=code)
        return
    await ws.accept()
    # A "tick" frame is a light payload without analysis/forecast. Sending only
    # one full frame at connect meant those blocks never refreshed (and, before
    # the client merged frames, they vanished after the first second).
    # The cadence is time based on purpose: `runtime.version` bumps on every tick
    # cycle, so keying off it would send the heavy payload every single second.
    full_every_seconds = float(get_settings().app.get("ws", {}).get("full_snapshot_seconds", 5))
    try:
        full = True
        last_full = 0.0
        while True:
            current, code = await asyncio.to_thread(_authority, runtime, settings, token)
            if code or current != identity:
                await ws.close(code=code or 4403)
                return
            now = time.time()
            if full or (now - last_full) >= full_every_seconds:
                data = await asyncio.to_thread(runtime.live_payload, False)
                data["type"] = "snapshot"
                full, last_full = False, now
            else:
                data = await asyncio.to_thread(runtime.live_payload, True)
                data["type"] = "tick"
            # Payload generation can take time; recheck immediately before disclosure.
            current, code = await asyncio.to_thread(_authority, runtime, settings, token)
            if code or current != identity:
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


@router.websocket("/ws")
async def alias_socket(ws: WebSocket, token: str | None = Query(default=None)):
    await live_socket(ws, token)
