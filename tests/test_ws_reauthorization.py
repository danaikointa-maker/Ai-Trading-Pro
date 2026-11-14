"""Authorization is checked before every frame, not only at handshake."""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from services.api_gateway.routes import ws as routes


@pytest.mark.parametrize("change,code", [("disabled", 4403), ("deleted", 4401),
                                        ("expired", 4401), ("role", 4403), ("db", 1011)])
def test_stream_stops_after_authority_changes(monkeypatch, change, code):
    row = {"email": "test@example.invalid", "role": "admin", "active": 1}
    db = Mock()
    db.workspace_id = "local"
    db.query_one.side_effect = lambda *_: row
    quota = Mock()
    quota.acquire.return_value = SimpleNamespace(expires_at=9999999999)
    claims = {"sub": row["email"], "role": "admin", "exp": 9999999999}
    monkeypatch.setattr(routes, "decode_token", lambda *_: claims)
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(security={"require_auth": True}, app={}))

    async def immediate(_):
        pass

    monkeypatch.setattr(routes.asyncio, "sleep", immediate)

    class Socket:
        app = SimpleNamespace(state=SimpleNamespace(ws_quota=quota, runtime=SimpleNamespace(
            db=db, live_payload=lambda *_: {"safe": True})))
        frames = 0
        closed = None

        async def accept(self):
            pass

        async def close(self, code=1000):
            self.closed = code

        async def send_text(self, _):
            self.frames += 1
            assert self.frames == 1, "a revoked session received another frame"
            if change == "disabled":
                row["active"] = 0
            elif change == "deleted":
                db.query_one.side_effect = lambda *_: None
            elif change == "expired":
                claims.clear()
            elif change == "role":
                row["role"] = "viewer"
            else:
                db.query_one.side_effect = RuntimeError("database offline")

    socket = Socket()
    asyncio.run(routes.live_socket(socket, "test-token"))
    assert socket.frames == 1
    assert socket.closed == code
    quota.release.assert_called_once_with(quota.acquire.return_value)


def test_accept_failure_releases_reserved_lease(monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(security={"require_auth": True}, app={}))
    monkeypatch.setattr(routes, "decode_token", lambda *_: {"sub": "test", "exp": 9999999999})
    quota = Mock()
    quota.acquire.return_value = SimpleNamespace(expires_at=9999999999)
    socket = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ws_quota=quota,
        runtime=SimpleNamespace(db=SimpleNamespace(workspace_id="local", query_one=lambda *_: {
            "email": "test", "role": "viewer", "active": 1})))),
        accept=AsyncMock(side_effect=RuntimeError("disconnect")), close=AsyncMock())
    asyncio.run(routes.live_socket(socket, "token"))
    quota.release.assert_called_once_with(quota.acquire.return_value)


def test_missing_user_is_rejected_before_accept(monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(security={"require_auth": True}, app={}))
    monkeypatch.setattr(routes, "decode_token", lambda *_: {"sub": "missing", "exp": 9999999999})
    from unittest.mock import AsyncMock

    socket = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=SimpleNamespace(
        db=SimpleNamespace(workspace_id="local", query_one=lambda *_: None)))), accept=AsyncMock(), close=AsyncMock())
    asyncio.run(routes.live_socket(socket, "test-token"))
    socket.accept.assert_not_called()
    socket.close.assert_awaited_once_with(code=4401)


def test_disabled_account_rejected_over_websocket(client, runtime):
    from starlette.websockets import WebSocketDisconnect

    from services.api_gateway.auth import create_token

    email = "ws-disabled@example.invalid"
    runtime.db.execute("INSERT OR REPLACE INTO users(email,password_hash,role,created_at,active) "
                       "VALUES(?,?,'viewer',0,0)", (email, "unused"))
    try:
        token, _ = create_token(runtime.settings, email, "admin")
        with pytest.raises(WebSocketDisconnect), client.websocket_connect(f"/ws/live?token={token}") as socket:
            socket.receive_json()
    finally:
        runtime.db.execute("DELETE FROM users WHERE email=?", (email,))