"""Read-only bridge refuses mutations even with a valid token and fresh session."""
from pathlib import Path

import pytest

from packages.persistence.db import Database
from services.bridge.relay import BridgeError, BridgeRelay


@pytest.fixture(params=["memory", "sqlite"])
def relay(request, tmp_path):
    db = Database(str(tmp_path / "bridge.sqlite3")) if request.param == "sqlite" else None
    relay = BridgeRelay({"demo": "token"}, db=db,
                        demo_identities={"demo": {"login": "123", "server": "Broker-Demo"}})
    yield relay
    if db:
        db.close()


def identity():
    return {"login": "123", "server": "Broker-Demo", "trade_mode": "demo", "connected": True}


def test_readonly_is_default_and_mutations_never_queue(relay):
    relay.register("demo", "token", "sid", terminal=identity())
    relay.poll("sid", token="token", snapshot={"account": identity()})
    for kind in ("order", "close", "modify", "unknown"):
        with pytest.raises(BridgeError, match="read.only"):
            relay.enqueue("demo", kind, {})
    assert relay.commands("demo") == []


@pytest.mark.parametrize("field,value", [("login", "999"), ("server", "Live"),
                                          ("trade_mode", "real"), ("connected", False)])
def test_wrong_identity_cannot_register_or_refresh(relay, field, value):
    bad = {**identity(), field: value}
    with pytest.raises(BridgeError, match="identity"):
        relay.register("demo", "token", "bad", terminal=bad)
    relay.register("demo", "token", "sid", terminal=identity())
    relay.poll("sid", token="token", snapshot={"account": identity()})
    with pytest.raises(BridgeError, match="identity"):
        relay.poll("sid", token="token", snapshot={"account": bad})
    assert relay.snapshot("demo") == {}, "old account data must be invalidated"


def test_missing_identity_configuration_fails_closed():
    relay = BridgeRelay({"demo": "token"})
    with pytest.raises(BridgeError, match="identity"):
        relay.register("demo", "token", terminal=identity())


def test_readonly_never_delivers_preexisting_mutation(relay):
    relay.register("demo", "token", "sid", terminal=identity())
    relay.read_only = False  # simulate an old executable queue before a policy change
    relay.enqueue("demo", "order", {"volume": 1})
    relay.read_only = True
    assert relay.poll("sid", token="token", snapshot={"account": identity()})["commands"] == []


def test_ea_source_has_readonly_and_account_guards():
    source = (Path(__file__).resolve().parents[1] / "bridge/No7BridgeEA.mq5").read_text(encoding="utf-8")
    assert "InpReadOnly     = true" in source
    assert "ACCOUNT_TRADE_MODE_DEMO" in source
    assert "InpExpectedLogin" in source and "InpExpectedServer" in source
    body = source.split("string ExecuteCommand(", 1)[1].split("string DoOrder(", 1)[0]
    assert body.index("InpReadOnly") < body.index('kind == "order"')
    for name in ("DoOrder", "DoClose", "DoModify"):
        body = source.split(f"string {name}(", 1)[1].split("OrderSend(", 1)[0]
        assert "InpReadOnly" in body and "DemoIdentityValid()" in body


def test_runtime_bridge_api_requires_identity_and_exposes_readonly(client, runtime, monkeypatch, auth):
    relay = runtime.bridge
    monkeypatch.setattr(relay, "enabled", True)
    monkeypatch.setattr(relay, "read_only", True)
    monkeypatch.setattr(relay, "accounts", {"readonly-test": "test-token"})
    monkeypatch.setattr(relay, "demo_identities", {"readonly-test": {"login": "123", "server": "Broker-Demo"}})
    headers = {"Authorization": "Bearer test-token"}
    body = {"account_id": "readonly-test", "session_id": "readonly-sid"}
    try:
        assert client.post("/api/bridge/register", json=body, headers=headers).status_code == 403
        body["terminal"] = identity()
        response = client.post("/api/bridge/register", json=body, headers=headers)
        assert response.status_code == 200 and response.json()["read_only"] is True
        response = client.post("/api/bridge/poll", headers=headers,
                               json={"session_id": "readonly-sid", "snapshot": {"account": identity()}})
        assert response.status_code == 200 and response.json()["commands"] == []
        assert client.get("/api/bridge/session", headers=auth).json()["read_only"] is True
    finally:
        relay.forget("readonly-test")