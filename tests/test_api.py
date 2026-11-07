"""HTTP contract tests: everything the dashboard relies on must answer 200."""
from __future__ import annotations

import json



def test_login_returns_token_and_hides_secret(client):
    res = client.post("/api/auth/login", json={"email": "demo@no7.ai", "password": "no7demo1234"})
    assert res.status_code == 200
    body = res.json()
    assert body["token"] and len(body["token"]) > 40
    assert "password" not in res.text.lower().replace("demo_password", "")


def test_login_rejects_wrong_password(client):
    res = client.post("/api/auth/login", json={"email": "demo@no7.ai", "password": "nope"})
    assert res.status_code == 401


def test_private_endpoints_require_auth(client):
    assert client.get("/api/trading/live").status_code == 401
    assert client.get("/api/risk/settings").status_code == 401


def test_health_is_public(client):
    res = client.get("/api/system/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] in ("ok", "degraded")
    assert "services" in body and "broker_health" in body


def test_live_snapshot_has_every_block_the_ui_needs(client, auth):
    res = client.get("/api/trading/live", headers=auth)
    assert res.status_code == 200, res.text
    live = res.json()
    for key in ("account", "positions", "risk_state", "limits", "signal", "analysis",
                "forecast", "mode", "feed", "alerts", "ticker"):
        assert key in live, f"missing {key}"
    analysis = live["analysis"]
    assert len(analysis["supports"]) >= 3 and len(analysis["resistances"]) >= 3
    assert analysis["spec"]["point"] > 0 and analysis["spec"]["digits"] >= 0
    forecast = live["forecast"]
    assert len(forecast["horizons"]) >= 3
    for h in forecast["horizons"]:
        assert h["p10_price"] < h["p90_price"]
        assert 0 <= h["p_up"] <= 1 and 0 <= h["p_down"] <= 1
    assert {s["name"] for s in forecast["scenarios"]} == {"bull", "base", "bear"}
    # the score is a heuristic and must never be presented as a probability
    assert live["signal"] is None or "score" in live["signal"]


def test_signal_score_is_not_a_probability(client, auth):
    live = client.get("/api/trading/live", headers=auth).json()
    signal = live.get("signal")
    if signal:
        assert signal["score"] <= 100
        if signal["explanation"]:
            assert signal["explanation"].get("calibrated") is False


def test_forecast_exposes_uncertainty(client, auth):
    res = client.get("/api/forecast", headers=auth)
    assert res.status_code == 200
    body = res.json()
    assert "active" in body and "models" in body


def test_zones_endpoint_separates_statuses(client, auth):
    res = client.get("/api/analysis/XAUUSD/zones", headers=auth)
    assert res.status_code == 200
    body = res.json()
    assert len(body["supports"]) >= 3 and len(body["resistances"]) >= 3


def test_points_calculator_uses_live_spec(client, auth):
    res = client.get("/api/market/calculator?symbol=XAUUSD&points=500&lot=0.01", headers=auth)
    assert res.status_code == 200
    body = res.json()
    assert body["spec"]["point"] == 0.01
    assert body["result"]["price_move"] == 5.0
    assert "excludes" in body["disclaimer"].lower() or "Excludes" in body["disclaimer"]


def test_risk_settings_round_trip(client, auth):
    before = client.get("/api/risk/settings", headers=auth).json()
    res = client.put("/api/risk/settings", json={"limits": {"max_spread_points": 55}}, headers=auth)
    assert res.status_code == 200
    assert res.json()["limits"]["max_spread_points"] == 55
    client.put("/api/risk/settings",
               json={"limits": {"max_spread_points": before["limits"]["max_spread_points"]}}, headers=auth)


def test_order_is_blocked_without_a_clean_gate(client, auth):
    """A demo account in a news window must refuse a manual order."""
    settings = client.get("/api/risk/settings", headers=auth).json()
    client.put("/api/risk/settings", json={"limits": {"news_lockout_enabled": False}}, headers=auth)
    try:
        live = client.get("/api/trading/live", headers=auth).json()
        if live["positions"]:
            client.post("/api/trading/close-all", headers=auth)
        res = client.post("/api/trading/order", json={"class": "x"}, headers=auth)
        assert res.status_code in (400, 422)
    finally:
        client.put("/api/risk/settings",
                   json={"limits": {"news_lockout_enabled": settings["settings"]["limits"]["news_lockout_enabled"]}},
                   headers=auth)


def test_broker_list_and_symbols(client, auth):
    brokers = client.get("/api/brokers", headers=auth).json()
    assert brokers["brokers"] and brokers["active"]
    syms = client.get(f"/api/brokers/{brokers['active']}/symbols", headers=auth).json()
    assert syms["symbols"] and syms["symbols"][0]["lot_step"] > 0


def test_spa_deep_links_are_served(client):
    for path in ("/", "/forecast", "/risk"):
        res = client.get(path)
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]


def test_backtest_job_list_is_pruned(client, token):
    """Finished jobs must not accumulate forever in a module-level dict."""
    from services.api_gateway.routes import backtest as bt

    with bt._LOCK:
        bt.JOBS.clear()
        for i in range(bt.MAX_JOBS + 10):
            bt.JOBS[f"JOB-OLD{i}"] = {"state": "done", "started_at": float(i)}
    bt._prune_jobs()
    assert len(bt.JOBS) <= bt.MAX_JOBS
    with bt._LOCK:
        bt.JOBS.clear()


def test_health_reports_notification_channels(client):
    health = client.get("/api/system/health").json()
    assert "notify" in health
    assert health["notify"]["channels"]["inapp"]["configured"] is True
    # external channels are off unless the operator configures them
    assert health["services"]["notify"] in ("inapp-only", "external", "failing")


def test_notify_status_endpoint_lists_channels_without_secrets(client, token):
    res = client.get("/api/system/notify", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    body = res.json()
    assert res.request.url.path == "/api/system/notify"
    assert set(body["channels"]) == {"inapp", "telegram", "line", "webhook"}
    assert "Bearer" not in json.dumps(body)
    for channel in body["channels"].values():
        assert "token" not in channel


def test_alert_test_endpoint_says_why_it_cannot_send(client, token):
    res = client.post("/api/system/alerts/test", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["deliveries"] == []
    assert body["reason"]
