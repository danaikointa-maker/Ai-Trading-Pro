from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from packages.shared_schemas.settings import get_settings
from services.api_gateway.auth import decode_token

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/live")
async def live_socket(ws: WebSocket, token: str | None = Query(default=None)):
    settings = get_settings()
    if settings.security.get("require_auth", True):
        payload = decode_token(settings, token or "")
        if not payload:
            await ws.close(code=4401)
            return
    await ws.accept()
    runtime = ws.app.state.runtime
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
            now = time.time()
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


@router.websocket("/ws")
async def alias_socket(ws: WebSocket, token: str | None = Query(default=None)):
    await live_socket(ws, token)
