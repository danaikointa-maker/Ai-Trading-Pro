from __future__ import annotations

import time


def _configure(runtime, monkeypatch):
    monkeypatch.setattr(runtime.market, "publisher", {
        "enabled": True, "token": "separate-market-data-token",
        "expected_login": "123456", "expected_server": "Connext-Demo",
        "symbols": ["XAUUSD"], "max_snapshot_age_seconds": 15,
    })
    monkeypatch.setattr(runtime.market, "db", None)


def _payload(*, captured_at=None, login="123456", time_basis="broker_server"):
    now = time.time()
    utc = now if captured_at is None else captured_at
    server = utc + 7200 if time_basis == "broker_server" else utc
    return {
        "identity": {"login": login, "server": "Connext-Demo",
                     "trade_mode": "demo", "connected": True},
        "captured_at": utc, "time_basis": time_basis,
        "server_time": server, "utc_time": utc,
        "quotes": {"XAUUSD": {"bid": 2300.0, "ask": 2300.2,
                                "last": 2300.1, "t": server}},
        "rates": {"XAUUSD": {"M1": [
            {"t": server - 60, "o": 2299, "h": 2301, "l": 2298, "c": 2300, "v": 10},
            {"t": server, "o": 2300, "h": 2302, "l": 2299, "c": 2301, "v": 11},
        ]}},
        "specs": {"XAUUSD": {"symbol": "XAUUSD", "digits": 2,
                               "point": 0.01, "tick_size": 0.01,
                               "contract_size": 100, "min_lot": 0.01,
                               "max_lot": 50, "lot_step": 0.01}},
    }


def test_mt5_market_publisher_requires_its_separate_token(client, runtime, monkeypatch):
    _configure(runtime, monkeypatch)
    response = client.post("/api/market/publish/mt5", json=_payload())
    assert response.status_code == 401
    response = client.post("/api/market/publish/mt5", json=_payload(),
                           headers={"Authorization": "Bearer separate-market-data-token"})
    assert response.status_code == 200, response.text
    assert response.json()["accepted"] is True
    assert runtime.market._publisher_snapshot["identity"] == {"verified_demo": True}


def test_mt5_market_publisher_is_disabled_by_default(client, runtime):
    assert runtime.market.publisher.get("enabled") is not True
    response = client.post("/api/market/publish/mt5", json=_payload(),
                           headers={"Authorization": "Bearer arbitrary"})
    assert response.status_code == 503


def test_mt5_market_publisher_fails_closed_without_demo_identity(client, runtime, monkeypatch):
    _configure(runtime, monkeypatch)
    runtime.market.publisher["expected_server"] = ""
    response = client.post("/api/market/publish/mt5", json=_payload(),
                           headers={"Authorization": "Bearer separate-market-data-token"})
    assert response.status_code == 503


def test_market_publisher_cache_is_scoped_to_account_and_demo_identity(tmp_path):
    from types import SimpleNamespace

    from packages.persistence.db import Database
    from services.market_data.service import MarketDataService

    db = Database(str(tmp_path / "publisher-scope.sqlite3"), workspace_id="publisher-test")
    try:
        base = {"enabled": True, "token": "not-used-here", "expected_server": "Connext-Demo",
                "symbols": ["XAUUSD"], "max_snapshot_age_seconds": 15}
        first_config = {**base, "account_id": "demo-a", "expected_login": "123456"}
        second_config = {**base, "account_id": "demo-b", "expected_login": "654321"}
        first = MarketDataService(SimpleNamespace(market_data={"mt5_publisher": first_config}),
                                  None, None, db=db)
        first.publish_mt5_snapshot(_payload(), now=time.time())
        restarted_same_identity = MarketDataService(
            SimpleNamespace(market_data={"mt5_publisher": first_config}), None, None, db=db)
        assert restarted_same_identity._publisher_snapshot is not None
        second = MarketDataService(SimpleNamespace(market_data={"mt5_publisher": second_config}),
                                   None, None, db=db)
        assert first._publisher_key != second._publisher_key
        assert second._publisher_snapshot is None
        assert "login" not in first._publisher_snapshot["identity"]
    finally:
        db.close()


def test_mt5_market_publisher_rejects_wrong_demo_identity_and_stale_data(
        client, runtime, monkeypatch):
    _configure(runtime, monkeypatch)
    headers = {"Authorization": "Bearer separate-market-data-token"}
    wrong_identity = client.post("/api/market/publish/mt5", json=_payload(login="other"),
                                 headers=headers)
    stale = client.post("/api/market/publish/mt5",
                        json=_payload(captured_at=time.time() - 60), headers=headers)
    assert wrong_identity.status_code == 422
    assert stale.status_code == 422


def test_mt5_market_publisher_has_no_positions_or_command_payload(client, runtime, monkeypatch):
    _configure(runtime, monkeypatch)
    payload = _payload()
    payload["positions"] = []
    response = client.post("/api/market/publish/mt5", json=payload,
                           headers={"Authorization": "Bearer separate-market-data-token"})
    assert response.status_code == 422


def test_mt5_market_publisher_drives_chart_and_refuses_stale_fallback(
        client, auth, runtime, monkeypatch):
    _configure(runtime, monkeypatch)
    headers = {"Authorization": "Bearer separate-market-data-token"}
    pushed = client.post("/api/market/publish/mt5", json=_payload(), headers=headers)
    assert pushed.status_code == 200, pushed.text
    ticker = client.get("/api/market/ticker?symbol=XAUUSD", headers=auth)
    assert ticker.status_code == 200
    assert ticker.json()["source"] == "mt5_demo_publisher"
    assert ticker.json()["stale"] is False
    assert runtime.health()["feed_mode"] == "mt5_demo_publisher"
    bars = client.get("/api/market/candles?symbol=XAUUSD&timeframe=M1&limit=20", headers=auth)
    assert bars.status_code == 200, bars.text
    assert bars.json()["candles"][-1]["c"] == 2301
    assert abs(bars.json()["candles"][-1]["t"] - time.time()) < 10
    monkeypatch.setattr(runtime.market, "_publisher_received_at", time.time() - 60)
    stale = client.get("/api/market/candles?symbol=XAUUSD&timeframe=M1&limit=20", headers=auth)
    assert stale.status_code == 503


def test_utc_publisher_does_not_claim_broker_server_clock(client, auth, runtime, monkeypatch):
    _configure(runtime, monkeypatch)
    pushed = client.post("/api/market/publish/mt5", json=_payload(time_basis="utc"),
                         headers={"Authorization": "Bearer separate-market-data-token"})
    assert pushed.status_code == 200, pushed.text
    response = client.get("/api/market/candles?symbol=XAUUSD&timeframe=M1&limit=20", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json()["time"] == {
        "basis": "utc", "display_basis": "utc", "server_utc_offset_seconds": 0,
    }
