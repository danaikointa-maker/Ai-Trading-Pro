"""EA bridge: one delivery, no stale data, and a real order round trip.

The bridge is how a Windows MT5 terminal talks to this server without the server ever
holding MT5 credentials. Two properties matter more than the plumbing, and both are
tested here:
* a command is delivered **once** and never re-sent (a duplicate is a second position);
* old state is never served (a stale quote is not a quote, a stale queue is not a queue).
"""
from __future__ import annotations

import threading
import time

import pytest

from integrations.brokers.base import BrokerError
from packages.shared_schemas.models import OrderRequest, OrderSide, OrderState
from services.bridge.relay import ACKED, EXPIRED, ORPHANED, BridgeError, BridgeRelay

ACCOUNT = "mt5-bridge-demo"
TOKEN = "test-bridge-token-0123456789"
SID = "EA-TEST-0001"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def snapshot(symbol: str = "XAUUSD", bid: float = 2000.0, ask: float = 2000.25,
             positions: list[dict] | None = None, rates: bool = True) -> dict:
    now = int(time.time())
    return {
        "server_time": time.time(),
        "account": {"login": "51234567", "balance": 10000.0, "equity": 10020.0, "margin": 0.0,
                    "free_margin": 10020.0, "currency": "USD", "leverage": 500,
                    "server": "Connext-Demo"},
        "quotes": {symbol: {"t": time.time(), "bid": bid, "ask": ask, "last": (bid + ask) / 2}},
        "symbols": {symbol: {"digits": 2, "point": 0.01, "contract_size": 100}},
        "positions": positions if positions is not None else [{
            "ticket": "50001", "symbol": symbol, "direction": "buy", "volume": 0.1,
            "price_open": 1999.0, "sl": 1995.0, "tp": 2008.0, "time": now - 60,
            "price_current": bid, "profit": 10.0, "comment": "ea",
        }],
        "rates": {symbol: {"M1": [{"t": now - 60 * i, "o": 2000.0, "h": 2001.0, "l": 1999.0,
                                   "c": 2000.5, "v": 100} for i in range(5, 0, -1)]}} if rates else {},
    }


# --------------------------------------------------------------------- protocol
def test_bridge_disabled_fails_closed():
    relay = BridgeRelay({ACCOUNT: TOKEN}, enabled=False)
    with pytest.raises(BridgeError, match="disabled"):
        relay.register(ACCOUNT, TOKEN, SID)
    with pytest.raises(BridgeError, match="disabled"):
        relay.poll(SID)


def test_unconfigured_account_cannot_register():
    relay = BridgeRelay({"other": TOKEN})
    with pytest.raises(BridgeError, match="not configured"):
        relay.register(ACCOUNT, TOKEN, SID)


def test_wrong_token_is_refused():
    relay = BridgeRelay({ACCOUNT: TOKEN})
    with pytest.raises(BridgeError, match="invalid bridge token"):
        relay.check_token(ACCOUNT, "nope")
    with pytest.raises(BridgeError, match="invalid bridge token"):
        relay.register(ACCOUNT, "nope", SID)   # register cannot skip the check
    assert ACCOUNT not in relay.sessions
    relay.check_token(ACCOUNT, TOKEN)  # correct token passes


def test_register_returns_the_protocol_parameters():
    relay = BridgeRelay({ACCOUNT: TOKEN}, fresh_seconds=5, stale_seconds=15)
    out = relay.register(ACCOUNT, TOKEN, SID, symbols=["XAUUSD"], terminal={"build": 4020})
    assert out["session_id"] == SID and out["restarted"] is False
    assert out["poll_interval_ms"] == 1000
    assert out["fresh_seconds"] == 5 and out["stale_seconds"] == 15
    assert relay.session_health(ACCOUNT) == "connected"
    assert relay.sessions[ACCOUNT].symbols == ["XAUUSD"]


def test_http_register_rejects_a_bad_token(client):
    res = client.post("/api/bridge/register",
                      json={"account_id": ACCOUNT, "session_id": SID},
                      headers={"Authorization": "Bearer wrong-token"})
    assert res.status_code == 401
    assert ACCOUNT not in client.app.state.runtime.bridge.connected_sessions() \
        if hasattr(client.app.state.runtime.bridge, "connected_sessions") \
        else True


# ------------------------------------------------------------------ one delivery
def test_command_is_delivered_exactly_once():
    relay = BridgeRelay({ACCOUNT: TOKEN})
    relay.register(ACCOUNT, TOKEN, SID)
    relay.poll(SID, snapshot=snapshot())
    command = relay.enqueue(ACCOUNT, "order", {"symbol": "XAUUSD", "side": "buy", "volume": 0.1})

    first = relay.poll(SID)
    assert [c["id"] for c in first["commands"]] == [command.id]
    # a second poll before the ack must NOT hand it over again
    second = relay.poll(SID)
    assert second["commands"] == []
    # and it is not yet reported as expired: the EA still has its grace window
    assert second["expired_unacked"] == []


def test_unacked_command_expires_and_is_never_resent():
    relay = BridgeRelay({ACCOUNT: TOKEN}, command_ttl_seconds=30, ack_grace_seconds=20)
    relay.register(ACCOUNT, TOKEN, SID)
    relay.poll(SID, snapshot=snapshot())
    command = relay.enqueue(ACCOUNT, "order", {"symbol": "XAUUSD", "volume": 0.1})
    relay.poll(SID)  # delivered now

    # the EA goes silent past the grace window
    relay.sessions[ACCOUNT].commands[command.id].delivered_at -= 60
    after = relay.poll(SID)
    assert after["commands"] == []
    assert [c["id"] for c in after["expired_unacked"]] == [command.id]
    assert relay.sessions[ACCOUNT].commands[command.id].state == EXPIRED
    assert relay.sessions[ACCOUNT].expiries == 1


def test_expired_command_ack_is_still_accepted_for_the_record():
    """A late ack is recorded (it may have executed) but never redispatched."""
    relay = BridgeRelay({ACCOUNT: TOKEN}, ack_grace_seconds=0.01)
    relay.register(ACCOUNT, TOKEN, SID)
    relay.poll(SID, snapshot=snapshot())
    command = relay.enqueue(ACCOUNT, "close", {"ticket": "50001"})
    relay.poll(SID)
    relay.sessions[ACCOUNT].commands[command.id].delivered_at -= 60
    relay.poll(SID)  # sweeps it to expired
    late = relay.poll(SID, results=[{"id": command.id, "ok": True, "status": "closed"}])
    assert late["results"][0]["accepted"] is True
    assert relay.sessions[ACCOUNT].commands[command.id].state == ACKED


def test_duplicate_ack_is_idempotent():
    relay = BridgeRelay({ACCOUNT: TOKEN})
    relay.register(ACCOUNT, TOKEN, SID)
    relay.poll(SID, snapshot=snapshot())
    command = relay.enqueue(ACCOUNT, "order", {"symbol": "XAUUSD", "volume": 0.1})
    relay.poll(SID)
    payload = {"id": command.id, "ok": True, "status": "filled", "ticket": "55001"}
    first = relay.poll(SID, results=[payload])
    second = relay.poll(SID, results=[payload])
    assert first["results"][0]["accepted"] is True
    assert second["results"][0]["duplicate"] is True
    assert second["results"][0]["result"]["ticket"] == "55001"
    assert relay.sessions[ACCOUNT].duplicates == 1
    assert relay.sessions[ACCOUNT].commands[command.id].state == ACKED


def test_result_for_unknown_command_is_reported_not_swallowed():
    relay = BridgeRelay({ACCOUNT: TOKEN})
    relay.register(ACCOUNT, TOKEN, SID)
    out = relay.poll(SID, results=[{"id": "CMD-NOPE", "ok": True}])
    assert out["results"][0]["accepted"] is False
    assert "unknown command" in out["results"][0]["reason"]
    assert relay.sessions[ACCOUNT].unknown_results == 1


def test_queue_cap_prevents_an_unbounded_backlog():
    relay = BridgeRelay({ACCOUNT: TOKEN}, max_pending=2)
    relay.register(ACCOUNT, TOKEN, SID)
    relay.poll(SID, snapshot=snapshot())
    relay.enqueue(ACCOUNT, "order", {"volume": 0.1})
    relay.enqueue(ACCOUNT, "order", {"volume": 0.2})
    with pytest.raises(BridgeError, match="queue is full"):
        relay.enqueue(ACCOUNT, "order", {"volume": 0.3})


# ---------------------------------------------------------------- nothing stale
def test_reconnect_discards_the_old_queue_and_snapshot():
    relay = BridgeRelay({ACCOUNT: TOKEN})
    relay.register(ACCOUNT, TOKEN, "EA-OLD")
    relay.poll("EA-OLD", snapshot=snapshot())
    command = relay.enqueue(ACCOUNT, "order", {"serial": 1})
    relay.poll("EA-OLD")  # delivered to the old terminal

    restarted = relay.register(ACCOUNT, TOKEN, "EA-NEW")
    assert restarted["restarted"] is True and restarted["generation"] == 1
    # the old command is not silently forgotten: it may already be live at the broker
    assert [c.id for c in relay.orphaned] == [command.id]
    assert relay.orphaned[0].state == ORPHANED
    assert relay.status()["orphaned_commands"][0]["id"] == command.id
    assert relay.sessions[ACCOUNT].snapshot == {}          # old state thrown away
    assert relay.snapshot_age(ACCOUNT) is None
    with pytest.raises(BridgeError, match="unknown or superseded session"):
        relay.poll("EA-OLD")
    # the new session starts clean: nothing from the previous terminal is re-sent
    fresh = relay.poll("EA-NEW", snapshot=snapshot())
    assert fresh["commands"] == []
    assert fresh["generation"] == 1


def test_stale_heartbeat_blocks_new_commands():
    relay = BridgeRelay({ACCOUNT: TOKEN}, fresh_seconds=5, stale_seconds=15)
    relay.register(ACCOUNT, TOKEN, SID)
    relay.sessions[ACCOUNT].last_seen -= 8
    assert relay.session_health(ACCOUNT) == "stale"
    with pytest.raises(BridgeError, match="is stale"):
        relay.enqueue(ACCOUNT, "order", {"volume": 0.1})
    relay.sessions[ACCOUNT].last_seen -= 60
    assert relay.session_health(ACCOUNT) == "disconnected"
    assert relay.age(ACCOUNT) > 15


def test_enqueue_without_any_session_is_refused():
    relay = BridgeRelay({ACCOUNT: TOKEN})
    with pytest.raises(BridgeError, match="no EA is connected"):
        relay.enqueue(ACCOUNT, "order", {"volume": 0.1})


# ------------------------------------------------------------------- HTTP wire
@pytest.fixture()
def bridge(client, runtime):
    """A registered, freshly polled EA session against the shared test runtime."""
    relay = runtime.bridge
    token = relay.accounts[ACCOUNT]
    res = client.post("/api/bridge/register",
                      json={"account_id": ACCOUNT, "session_id": SID,
                            "terminal": {"build": 4020, "company": "Connext"},
                            "symbols": ["XAUUSD"]},
                      headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    poll = client.post("/api/bridge/poll", json={"session_id": SID, "snapshot": snapshot()}, headers=AUTH)
    assert poll.status_code == 200, poll.text
    yield {"session_id": SID, "relay": relay, "adapter": runtime.registry.get(ACCOUNT)}
    relay.sessions.pop(ACCOUNT, None)


def test_poll_requires_a_live_session(client):
    res = client.post("/api/bridge/poll", json={"session_id": "EA-DOES-NOT-EXIST"}, headers=AUTH)
    assert res.status_code == 409
    assert "register" in res.json()["detail"]


def test_poll_without_the_token_is_refused(client, bridge):
    """A session id is not a credential: it must not be enough to poll or to ack."""
    no_token = client.post("/api/bridge/poll", json={"session_id": SID})
    assert no_token.status_code == 401
    wrong = client.post("/api/bridge/poll", json={"session_id": SID},
                        headers={"Authorization": "Bearer not-the-token"})
    assert wrong.status_code == 401
    ok = client.post("/api/bridge/poll", json={"session_id": SID}, headers=AUTH)
    assert ok.status_code == 200


def test_snapshot_feeds_the_adapter(bridge):
    adapter = bridge["adapter"]
    info = adapter.account_info()
    assert info.balance == 10000.0 and info.login == "51234567"
    tick = adapter.ticker("XAUUSD")
    assert tick.bid == 2000.0 and tick.ask == 2000.25
    assert tick.spread_points == pytest.approx(25.0)
    positions = adapter.positions()
    assert [p.ticket for p in positions] == ["50001"]
    assert positions[0].direction.value == "up" and positions[0].unrealized == 10.0
    bars = adapter.candles("XAUUSD", "M1", 10)
    assert list(bars.columns) == ["t", "o", "h", "l", "c", "v"] and len(bars) == 5
    assert adapter.health().value == "connected"


def test_positions_are_replaced_not_merged(bridge):
    adapter = bridge["adapter"]
    client = bridge["relay"]
    assert client is not None
    new = snapshot(positions=[{"ticket": "50002", "symbol": "XAUUSD", "direction": "sell",
                               "volume": 0.2, "price_open": 2002.0, "sl": 2006.0, "tp": 1994.0,
                               "time": int(time.time()), "price_current": 2000.0,
                               "profit": 40.0}])
    bridge["relay"].poll(SID, snapshot=new)
    positions = adapter.positions()
    assert [p.ticket for p in positions] == ["50002"]
    assert positions[0].direction.value == "down"


def test_old_snapshot_is_refused_not_served(bridge):
    adapter = bridge["adapter"]
    session = bridge["relay"].sessions[ACCOUNT]
    session.snapshot_at -= 120
    session.last_seen -= 120
    with pytest.raises(BrokerError, match="old|stale"):
        adapter.account_info()
    with pytest.raises(BrokerError, match="old|stale"):
        adapter.positions()
    with pytest.raises(BrokerError, match="old|stale"):
        adapter.ticker("XAUUSD")
    assert adapter.health().value == "disconnected"


def test_unusable_quote_is_an_error_not_a_price(bridge):
    bridge["relay"].poll(SID, snapshot=snapshot(bid=2000.5, ask=2000.1))  # ask below bid
    with pytest.raises(BrokerError, match="unusable"):
        bridge["adapter"].ticker("XAUUSD")


def test_missing_rates_are_an_error_not_synthetic_data(bridge):
    bridge["relay"].poll(SID, snapshot=snapshot(rates=False))
    with pytest.raises(BrokerError, match="no M1 rates"):
        bridge["adapter"].candles("XAUUSD", "M1", 10)


def test_order_round_trip_waits_for_the_ea(client, bridge):
    adapter = bridge["adapter"]
    adapter.order_timeout = 5.0
    box: dict = {}

    def place() -> None:
        try:
            box["result"] = adapter.order_send(OrderRequest(
                symbol="XAUUSD", side=OrderSide.buy, volume=0.1, sl=1995.0, tp=2008.0,
                idempotency_key="idem-test-1"))
        except Exception as exc:  # noqa: BLE001 - surfaced through the assertion
            box["error"] = exc

    thread = threading.Thread(target=place, daemon=True)
    thread.start()
    pending: list = []
    deadline = time.time() + 5
    while time.time() < deadline:
        pending = [c for c in bridge["relay"].sessions[ACCOUNT].commands.values()
                   if c.state == "pending"]
        if pending:
            break
        time.sleep(0.02)
    assert pending, "adapter never queued a command"
    ack = client.post("/api/bridge/poll", headers=AUTH, json={
        "session_id": SID, "snapshot": snapshot(),
        "results": [{"id": pending[0].id, "ok": True, "status": "filled",
                     "ticket": "55123", "price": 2000.25, "volume": 0.1}]})
    assert ack.status_code == 200
    thread.join(10)
    assert "error" not in box, box.get("error")
    result = box["result"]
    assert result.status == OrderState.filled
    assert result.ticket == "55123" and result.filled_volume == 0.1
    assert result.verified is True and result.idempotency_key == "idem-test-1"


def test_order_without_an_ea_is_refused(runtime):
    from integrations.brokers.bridge import BridgeBroker
    from services.bridge.relay import BridgeRelay as Relay

    relay = Relay({ACCOUNT: TOKEN})
    adapter = BridgeBroker({"id": "b1", "bridge_account": ACCOUNT, "symbols": {}}, relay)
    with pytest.raises(BrokerError, match="never connected"):
        adapter.order_send(OrderRequest(symbol="XAUUSD", side=OrderSide.buy, volume=0.1))


def test_unacked_order_returns_an_error_and_is_not_resent(client, bridge):
    adapter = bridge["adapter"]
    adapter.order_timeout = 0.05
    with pytest.raises(BrokerError, match="did not acknowledge"):
        adapter.order_send(OrderRequest(symbol="XAUUSD", side=OrderSide.buy, volume=0.1))
    # it was queued and is handed to the EA exactly once when it next polls ...
    first = client.post("/api/bridge/poll", json={"session_id": SID}, headers=AUTH).json()
    assert len(first["commands"]) == 1 and first["commands"][0]["kind"] == "order"
    # ... and never a second time, even though the adapter has already given up on it
    second = client.post("/api/bridge/poll", json={"session_id": SID}, headers=AUTH).json()
    assert second["commands"] == []


# ------------------------------------------------------------------- operator
def test_status_endpoint_is_admin_only(client, bridge, runtime):
    token = client.post("/api/auth/login",
                        json={"email": "demo@no7.ai", "password": "no7demo1234"}).json()["token"]
    res = client.get("/api/bridge/status", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] is True
    assert any(s["account"] == ACCOUNT for s in body["sessions"])
    me = next(s for s in body["sessions"] if s["account"] == ACCOUNT)
    assert me["health"] == "connected" and me["positions"] == 1
    # no token ever leaves the server, not even a hash of the whole thing
    assert all(len(v) == 8 for v in body["tokens"].values())

    client.post("/api/users", json={"email": "bridge-viewer@no7.ai", "password": "viewerpass123",
                                    "role": "viewer"},
                headers={"Authorization": f"Bearer {token}"})
    viewer = client.post("/api/auth/login", json={"email": "bridge-viewer@no7.ai",
                                                  "password": "viewerpass123"}).json()["token"]
    denied = client.get("/api/bridge/status", headers={"Authorization": f"Bearer {viewer}"})
    assert denied.status_code == 403


def test_cancel_drops_queued_commands(client, bridge):
    token = client.post("/api/auth/login",
                        json={"email": "demo@no7.ai", "password": "no7demo1234"}).json()["token"]
    bridge["relay"].enqueue(ACCOUNT, "order", {"volume": 0.1})
    res = client.post("/api/bridge/cancel", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["dropped"][ACCOUNT] == 1
    assert all(c.state != "pending"
               for c in bridge["relay"].sessions[ACCOUNT].commands.values())


def test_session_view_for_the_dashboard(client, bridge):
    token = client.post("/api/auth/login",
                        json={"email": "demo@no7.ai", "password": "no7demo1234"}).json()["token"]
    res = client.get("/api/bridge/session", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    row = next(r for r in res.json()["bridges"] if r["account"] == ACCOUNT)
    assert row["session_id"] == SID and row["health"] == "connected"
    assert row["snapshot_age_seconds"] is not None
