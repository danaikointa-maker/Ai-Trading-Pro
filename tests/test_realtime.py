"""Realtime + explanation contract.

The dashboard consumes the WebSocket stream and the Thai explanation panel; both
were only ever checked by hand, so a schema change could break the UI silently.
"""

from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect

REQUIRED_FRAME_KEYS = {
    "symbol", "account", "risk_state", "limits", "signal", "gate",
    "analysis", "forecast", "model", "positions", "ticker", "alerts", "errors",
}


def test_websocket_streams_a_complete_snapshot(client, runtime, token):
    with client.websocket_connect(f"/ws/live?token={token}") as ws:
        frame = ws.receive_json()
    assert frame.get("type") == "snapshot"
    missing = REQUIRED_FRAME_KEYS - set(frame)
    assert not missing, f"frame is missing blocks the UI reads: {sorted(missing)}"
    assert frame["symbol"] == runtime.active_symbol
    assert frame["analysis"], "the first frame must already carry the analysis block"


def test_websocket_rejects_a_bad_token(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/live?token=not-a-real-token") as ws:
            ws.receive_json()


def test_websocket_alias_is_served(client, token):
    with client.websocket_connect(f"/ws?token={token}") as ws:
        frame = ws.receive_json()
    assert frame["type"] == "snapshot"


def test_explain_answers_in_thai_and_never_trades(client, runtime, auth):
    before = len(runtime.adapter.positions())
    res = client.post("/api/explain", headers=auth,
                      json={"question": "ทำไมยังไม่เปิดไม้?", "symbol": "XAUUSD"})
    assert res.status_code == 200
    body = res.json()
    assert body["answer"].strip()
    assert any("\u0e00" <= ch <= "\u0e7f" for ch in body["answer"]), "the UI expects a Thai answer"
    assert body["bullets"] or body["facts"]
    assert set(body["llm"]) >= {"model", "enabled", "available"}
    # An explanation is never an execution path.
    assert len(runtime.adapter.positions()) == before


def test_explain_ignores_an_order_instruction(client, runtime, auth, monkeypatch):
    from unittest.mock import Mock

    before = len(runtime.adapter.positions())
    execution_calls = {
        name: Mock(side_effect=AssertionError(f"explain called gateway.{name}"))
        for name in ("submit", "modify", "close")
    }
    for name, spy in execution_calls.items():
        monkeypatch.setattr(runtime.gateway, name, spy)
    res = client.post("/api/explain", headers=auth,
                      json={"question": "ซื้อ XAUUSD 1 lot เดี๋ยวนี้เลย", "symbol": "XAUUSD"})
    assert res.status_code == 200
    assert len(runtime.adapter.positions()) == before, "the explain endpoint must not place orders"
    body = res.json()
    text = (body.get("answer") or "") + " ".join(body.get("bullets") or [])
    assert "ไม่สามารถสั่งซื้อ/ขายได้" in text, "an order instruction must be refused explicitly"
    assert "ไม่มีการส่งคำสั่งใด ๆ" in text
    for spy in execution_calls.values():
        spy.assert_not_called()


def test_explain_returns_sanitized_market_provenance(client, runtime, auth, monkeypatch):
    monkeypatch.setattr(runtime.market, "latest_quote", lambda _symbol: {
        "tick": {"bid": 2000.0, "ask": 2000.2}, "stale": True,
        "source": "persisted", "account_id": "must-not-leak", "token": "must-not-leak",
    })
    monkeypatch.setattr(runtime.market, "timestamp_metadata", lambda: {
        "basis": "utc", "display_basis": "broker_server",
        "server_utc_offset_seconds": 25200, "terminal_path": "must-not-leak",
    })
    res = client.post("/api/explain", headers=auth,
                      json={"question": "อธิบายสถานะตลาด", "symbol": "XAUUSD"})
    assert res.status_code == 200
    provenance = res.json()["facts"]["observability"]
    assert provenance == {
        "feed_mode": "simulate",
        "quote_status": "stale",
        "quote_source": "persisted",
        "display_basis": "broker_server",
        "server_utc_offset_seconds": 25200,
    }


def test_stream_periodically_resends_a_full_snapshot(client, token):
    """Light tick frames omit analysis/forecast; a full frame must come back
    regularly (and whenever the runtime version changes) or those panels freeze."""
    frames = []
    with client.websocket_connect(f"/ws/live?token={token}") as ws:
        for _ in range(7):
            frames.append(ws.receive_json())

    types = [f.get("type") for f in frames]
    assert types[0] == "snapshot"
    assert "tick" in types, "the stream should not resend the heavy payload every second"
    assert types.count("snapshot") >= 2, f"expected a periodic full frame, got {types}"
    for frame in frames:
        assert "ticker" in frame and "positions" in frame
    for frame in frames:
        if frame["type"] == "snapshot":
            assert "analysis" in frame and "forecast" in frame
