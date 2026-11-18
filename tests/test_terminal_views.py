import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from packages.persistence.db import Database
from services.api_gateway.terminal_views import (
    claim_terminal,
    issue_link_code,
    list_terminal_views,
    private_positions,
)
from services.bridge.relay import BridgeRelay, BridgeTokenError


@pytest.fixture
def terminal(tmp_path):
    db = Database(tmp_path / "terminal-view.sqlite3")
    identity = {"login": "12345678", "server": "Broker-Demo", "trade_mode": "demo", "connected": True}
    relay = BridgeRelay({"bridge": "fixture-readonly-bridge-token"}, db=db,
                        demo_identities={"bridge": {"login": identity["login"], "server": identity["server"]}})
    relay.register("bridge", "fixture-readonly-bridge-token", "fixture-session", terminal=identity, symbols=["XAUUSD.s"])
    snapshot = {"account": dict(identity), "positions_scope": "private", "positions": [{"symbol": "XAUUSD.s", "ticket": "99",
                 "direction": "up", "entry": 2000, "sl": 1990, "tp": 2020, "volume": 0.01}],
                "positions_status": {"available": True, "captured_at": time.time()}}
    relay.poll("fixture-session", snapshot=snapshot)
    adapter = SimpleNamespace(id="adapter", account_id="bridge")
    runtime = SimpleNamespace(db=db, bridge=relay, registry=SimpleNamespace(all=lambda: [adapter], get=lambda _: adapter))
    yield runtime, snapshot
    db.close()


OWNER = {"tenant_id": "tenant-one", "email": "owner@example.test"}


def test_terminal_link_requires_private_token_and_is_one_use(terminal):
    rt, _ = terminal
    with pytest.raises(BridgeTokenError):
        issue_link_code(rt, "bridge", "fixture-session", "not-the-token")
    issued = issue_link_code(rt, "bridge", "fixture-session", "fixture-readonly-bridge-token")
    row = rt.db.query_one("SELECT code_hash FROM terminal_link_codes")
    assert issued["code"] not in row["code_hash"]
    link = claim_terminal(rt, OWNER, issued["code"])
    assert link["execution_enabled"] is False
    with pytest.raises(HTTPException):
        claim_terminal(rt, OWNER, issued["code"])
    assert len(list_terminal_views(rt, OWNER)) == 1


def test_private_positions_do_not_leak_to_another_user_or_tenant(terminal):
    rt, _ = terminal
    code = issue_link_code(rt, "bridge", "fixture-session", "fixture-readonly-bridge-token")["code"]
    link = claim_terminal(rt, OWNER, code)
    result = private_positions(rt, OWNER, link["id"], "adapter", "XAUUSD.s")
    assert result["available"] is True and result["positions"][0]["sl"] == 1990
    for other in [{**OWNER, "email": "other@example.test"}, {**OWNER, "tenant_id": "tenant-two"}]:
        assert list_terminal_views(rt, other) == []
        assert private_positions(rt, other, link["id"], "adapter", "XAUUSD.s")["available"] is False
    assert rt.bridge.read_only is True
    assert rt.bridge.commands("bridge") == []


def test_private_positions_invalidate_account_switch_and_stale_snapshots(terminal):
    rt, snapshot = terminal
    code = issue_link_code(rt, "bridge", "fixture-session", "fixture-readonly-bridge-token")["code"]
    link = claim_terminal(rt, OWNER, code)
    snapshot["positions_status"]["captured_at"] = time.time() - 20
    rt.bridge.poll("fixture-session", snapshot=snapshot)
    assert private_positions(rt, OWNER, link["id"], "adapter", "XAUUSD.s")["available"] is False
    snapshot["account"]["login"] = "different-account"
    rt.bridge.store.save_snapshot("bridge", "fixture-session", snapshot, time.time())
    assert private_positions(rt, OWNER, link["id"], "adapter", "XAUUSD.s")["available"] is False


def test_claim_code_expires_and_rejects_terminal_identity_change(terminal):
    rt, snapshot = terminal
    code = issue_link_code(rt, "bridge", "fixture-session", "fixture-readonly-bridge-token")["code"]
    rt.db.execute("UPDATE terminal_link_codes SET expires_at=0")
    with pytest.raises(HTTPException):
        claim_terminal(rt, OWNER, code)
    code = issue_link_code(rt, "bridge", "fixture-session", "fixture-readonly-bridge-token")["code"]
    snapshot["account"]["server"] = "different-server"
    rt.bridge.store.save_snapshot("bridge", "fixture-session", snapshot, time.time())
    with pytest.raises(HTTPException):
        claim_terminal(rt, OWNER, code)


def test_private_empty_positions_are_distinct_from_failed_reads(terminal):
    rt, snapshot = terminal
    code = issue_link_code(rt, "bridge", "fixture-session", "fixture-readonly-bridge-token")["code"]
    link = claim_terminal(rt, OWNER, code)
    snapshot["positions"] = []
    rt.bridge.poll("fixture-session", snapshot=snapshot)
    assert private_positions(rt, OWNER, link["id"], "adapter", "XAUUSD.s")["available"] is True
    snapshot["positions_status"]["available"] = False
    rt.bridge.poll("fixture-session", snapshot=snapshot)
    assert private_positions(rt, OWNER, link["id"], "adapter", "XAUUSD.s")["available"] is False


def test_publisher_reads_only_requested_positions_and_preserves_unknown(monkeypatch):
    from scripts import mt5_readonly_market_publisher as publisher

    account = SimpleNamespace(login=123, server="Broker-Demo", trade_mode=0)
    status = SimpleNamespace(connected=True)
    position = SimpleNamespace(symbol="XAUUSD.s", type=0, ticket=99, price_open=2000, sl=1990, tp=2020, volume=0.01)
    other = SimpleNamespace(symbol="EURUSD", type=0)
    mt5 = SimpleNamespace(ACCOUNT_TRADE_MODE_DEMO=0, POSITION_TYPE_BUY=0, POSITION_TYPE_SELL=1,
                          positions_get=lambda: [position, other], account_info=lambda: account,
                          terminal_info=lambda: status)
    monkeypatch.setattr(publisher, "symbol_snapshot", lambda *_: ({"bid": 2000, "ask": 2001}, {}))
    build = lambda: publisher.build_snapshot(mt5, account, status, ["XAUUSD.s"],
                                             include_rates=False, rates_bars=20, include_positions=True)
    result = build()
    assert result["positions_status"]["available"] is True
    assert len(result["positions"]) == 1 and result["positions"][0]["sl"] == 1990
    mt5.positions_get = lambda: None
    assert build()["positions_status"]["available"] is False
    mt5.account_info = lambda: SimpleNamespace(login=999, server="Broker-Demo", trade_mode=0)
    with pytest.raises(publisher.PublisherError, match="expected"):
        build()


def test_shared_broker_adapter_cannot_expose_private_positions(terminal):
    from integrations.brokers.base import BrokerError
    from integrations.brokers.bridge import BridgeBroker

    rt, _ = terminal
    adapter = BridgeBroker({"id": "bridge"}, rt.bridge)
    with pytest.raises(BrokerError, match="owner-scoped"):
        adapter.positions()
