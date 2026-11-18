from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from services.api_gateway import market_access


def test_shared_chart_does_not_require_a_broker_account():
    runtime = Mock()
    runtime.market.chart_source.return_value = ("shared", "mt5-live")
    assert market_access.chart_source(runtime, {}, "XAUUSD") == ("shared", "mt5-live")
    runtime.db.query_one.assert_not_called()


def test_selected_account_requires_access_and_a_connected_session(monkeypatch):
    runtime = Mock()
    monkeypatch.setattr(market_access, "market_accounts", lambda *_: [
        {"id": "mine", "market_connected": False}])
    for account_id, status in [("someone-elses", 404), ("mine", 503)]:
        with pytest.raises(HTTPException) as error:
            market_access.chart_source(runtime, {}, "XAUUSD", account_id)
        assert error.value.status_code == status
    runtime.registry.get.assert_not_called()


@pytest.mark.parametrize("mode,login,connected", [
    ("demo", "1234", True), ("live", "1234", False), ("demo", "5678", False)])
def test_account_session_must_match_type_and_full_identity(monkeypatch, mode, login, connected):
    account = {"id": "mine", "provider": "mt5", "server": "Broker-Demo", "account_type": "demo"}
    monkeypatch.setattr(market_access, "list_broker_accounts", lambda *_: [dict(account)])
    vault = Mock()
    vault.fingerprint.side_effect = lambda tenant, provider, server, login: f"{tenant}/{login}"
    monkeypatch.setattr(market_access, "CredentialVault", lambda: vault)
    runtime = Mock()
    runtime.db.query.return_value = []
    runtime.db.query_one.return_value = {"login_fingerprint": "tenant-a/1234"}
    adapter = SimpleNamespace(adapter_type="bridge", account_id="bridge", id="adapter",
                              health=lambda: SimpleNamespace(value="connected"))
    runtime.registry.all.return_value = [adapter]
    runtime.bridge.get.return_value = SimpleNamespace(snapshot={"account": {
        "connected": True, "trade_mode": mode, "server": "Broker-Demo", "login": login}})
    result = market_access.market_accounts(runtime, {"tenant_id": "tenant-a"})[0]
    assert result["market_connected"] is connected
    assert result["market_broker_id"] == ("adapter" if connected else None)
