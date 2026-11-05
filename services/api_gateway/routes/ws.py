from __future__ import annotations

import asyncio
import json

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
    try:
        full = True
        while True:
            data = await asyncio.to_thread(runtime.live_payload, not full)
            data["type"] = "snapshot" if full else "tick"
            await ws.send_text(json.dumps(data, default=str))
            full = False
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
