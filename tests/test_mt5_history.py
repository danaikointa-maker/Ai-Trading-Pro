from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from integrations.brokers.base import BrokerError
from integrations.brokers.mt5_live import MT5Broker


@pytest.fixture
def terminal(monkeypatch):
    from integrations.brokers import mt5_live

    info = SimpleNamespace(login=123, server="Demo-Server", currency="USD", balance=10000,
                           equity=10000, margin=0, margin_free=10000, leverage=100,
                           trade_mode=0)
    trade = SimpleNamespace(ticket=1, order=10, position_id=100, type=0, entry=0,
                            symbol="XAUUSD", volume=0.1, price=2000, time_msc=1000,
                            profit=0, commission=-1, swap=0, fee=0)
    api = SimpleNamespace(account_info=Mock(return_value=info), history_deals_get=Mock(return_value=(trade,)),
                          last_error=lambda: (-1, "unavailable"),
                          terminal_info=lambda: SimpleNamespace(connected=True))
    monkeypatch.setattr(mt5_live, "mt5", api)
    # The fixture stands in for a connected terminal, so the availability flag has
    # to say so too — the package is Windows-only and absent on CI, which left
    # `account_info()` on its disconnected branch returning login "—". The identity
    # guard in ExecutionGateway then refused the account, failing a test about
    # history. Same patch the other MT5 suites use.
    monkeypatch.setattr(mt5_live, "MT5_AVAILABLE", True)
    broker = MT5Broker({"id": "demo", "symbols": {}}, login=123, server="Demo-Server")
    broker._connected = True
    return broker, api


def test_history_maps_exact_deal_identity(terminal):
    broker, api = terminal
    history = broker.deal_history(0, 10)
    assert history["account_key"] == "Demo-Server:123"
    assert history["deals"][0]["order_id"] == "10"
    assert history["deals"][0]["entry"] == "in"
    assert api.history_deals_get.call_count == 1
    assert history["account_identity"] == {"broker_id": "demo", "login": "123",
                                            "server": "Demo-Server", "currency": "USD"}


def test_history_transport_failure_is_not_empty_history(terminal):
    broker, api = terminal
    api.history_deals_get.return_value = None
    with pytest.raises(BrokerError, match="history"):
        broker.deal_history(0, 10)


def test_empty_history_keeps_explicit_account_evidence(terminal):
    broker, api = terminal
    api.history_deals_get.return_value = ()
    history = broker.deal_history(0, 10)
    assert history["deals"] == []
    assert history["account_identity"] == {"broker_id": "demo", "login": "123",
                                            "server": "Demo-Server", "currency": "USD"}


def test_history_account_switch_discards_entire_response(terminal):
    broker, api = terminal
    api.account_info.side_effect = [SimpleNamespace(login=123, server="Demo-Server", currency="USD"),
                                    SimpleNamespace(login=456, server="Demo-Server", currency="USD")]
    with pytest.raises(BrokerError, match="identity"):
        broker.deal_history(0, 10)


def test_history_without_explicit_identity_is_refused(terminal):
    broker, api = terminal
    broker.login = None
    with pytest.raises(BrokerError, match="identity"):
        broker.deal_history(0, 10)
    api.history_deals_get.assert_not_called()


def test_gateway_refresh_history_never_resends_or_resolves(tmp_path, terminal):
    from packages.persistence.db import Database
    from services.execution_gateway.gateway import ExecutionGateway

    broker, _ = terminal
    db = Database(str(tmp_path / "history.sqlite3"))
    try:
        gateway = ExecutionGateway(SimpleNamespace(execution={}), db)
        status = gateway.refresh_history(broker, 0, 10)
        assert status["ok"] is True
        assert status["inserted"] == 1
        assert gateway.refresh_history(broker, 0, 10)["inserted"] == 0
        assert status["auto_resolved"] is False
        assert db.query("SELECT * FROM orders") == []
    finally:
        db.close()