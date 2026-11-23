from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest


def _packet():
    return {
        "schema": "ai-agent-lens/v1", "event": "BAR_CLOSE",
        "symbol": "OANDA:XAUUSD", "timeframe": "5",
        "time": datetime.now(timezone.utc).isoformat(), "state_code": "LENS|XAUUSD|5",
        "candle": {"open": 2600, "high": 2603, "low": 2599, "close": 2602,
                   "volume": 100, "direction": "bull", "body_pct": 50,
                   "upper_wick_pct": 25, "lower_wick_pct": 25, "range_atr": 1,
                   "close_position_pct": 75, "gap_pct": None,
                   "closed_above_prev_high": False, "closed_below_prev_low": False,
                   "pattern": "NONE"},
        "regime": "TREND_UP",
        "trend": {"ema_fast": 2601, "ema_mid": 2600, "ema_slow": 2590,
                  "stack": "BULLISH", "slow_slope": "RISING", "htf": "60", "htf_bias": "UP"},
        "momentum": {"rsi": 60, "macd_hist": 0.1, "macd_hist_rising": True},
        "strength": {"adx": 25, "di_plus": 30, "di_minus": 15},
        "volatility": {"atr": 3, "atr_percentile": 60}, "volume": {"relative": 1.2},
        "structure": {"bias": "BULLISH", "event": "BREAK_UP",
                      "last_swing_high": 2601, "last_swing_low": 2598},
        "levels": {"prev_day_high": 2610, "prev_day_low": 2580, "vwap": 2600},
        "scores": {"long": 60, "short": 20, "threshold": 70},
    }


def test_ingress_is_off_by_default(client, monkeypatch):
    monkeypatch.delenv("NO7_TRADINGVIEW_ENABLED", raising=False)
    response = client.post("/api/integrations/tradingview/ai-agent-lens",
                           json={"token": "x" * 40, "packet": _packet()})
    assert response.status_code == 503


def test_ingress_stores_only_deduped_shadow_evidence(client, runtime, monkeypatch, auth):
    monkeypatch.setenv("NO7_TRADINGVIEW_ENABLED", "true")
    monkeypatch.setenv("NO7_TRADINGVIEW_WEBHOOK_TOKEN", "test-tradingview-token-0123456789")
    monkeypatch.setenv("NO7_TRADINGVIEW_SYMBOL_MAP", '{"OANDA:XAUUSD":"XAUUSD"}')
    packet = _packet()
    body = {"token": "test-tradingview-token-0123456789", "packet": packet}
    orders_before = runtime.db.query_one("SELECT COUNT(*) AS n FROM orders")["n"]
    first = client.post("/api/integrations/tradingview/ai-agent-lens", json=body)
    second = client.post("/api/integrations/tradingview/ai-agent-lens", json=body)
    assert first.status_code == second.status_code == 202
    assert first.json()["quality"] == "shadow_only"
    assert second.json()["duplicate"] is True
    rows = runtime.db.query("SELECT payload FROM tradingview_evidence WHERE mapped_symbol=?", ("XAUUSD",))
    assert len(rows) == 1
    assert "test-tradingview-token" not in rows[0]["payload"]
    assert "stop" not in rows[0]["payload"]
    assert runtime.db.query_one("SELECT COUNT(*) AS n FROM orders")["n"] == orders_before

    view = client.get("/api/integrations/tradingview/ai-agent-lens/latest",
                      params={"symbol": "XAUUSD", "timeframe": "5"}, headers=auth)
    assert view.status_code == 200
    assert view.json()["quality"] == "shadow_only"
    assert len(view.json()["evidence"]) == 1
    evidence = view.json()["evidence"][0]
    assert evidence["freshness"]["status"] == "fresh"
    assert evidence["comparison"]["status"] == "no_exact_no7_bar_match"
    runtime.db.execute(
        "INSERT INTO signals(id,t,symbol,action,score,payload) VALUES(?,?,?,?,?,?)",
        ("tv-shadow-match", evidence["bar_close_utc"], "XAUUSD", "WAIT", 55,
         json.dumps({"symbol": "XAUUSD", "timeframe": "M5", "action": "WAIT",
                     "score": 55, "status": "weak"})),
    )
    aligned = client.get("/api/integrations/tradingview/ai-agent-lens/latest",
                         params={"symbol": "XAUUSD", "timeframe": "M5"}, headers=auth)
    comparison = aligned.json()["evidence"][0]["comparison"]
    assert comparison["status"] == "exact_bar_match"
    assert comparison["no7_score"] == 55
    assert comparison["scores_are_separate"] is True

    stale_payload = dict(evidence)
    stale_payload["bar_close_utc"] = int(datetime.now(timezone.utc).timestamp()) - 3600
    runtime.db.execute(
        "UPDATE tradingview_evidence SET bar_close_utc=?, payload=? WHERE payload_sha256=?",
        (stale_payload["bar_close_utc"], json.dumps(stale_payload), evidence["payload_sha256"]),
    )
    stale_view = client.get("/api/integrations/tradingview/ai-agent-lens/latest",
                            params={"symbol": "XAUUSD", "timeframe": "M5"}, headers=auth)
    assert stale_view.json()["evidence"][0]["freshness"]["status"] == "stale"


def test_ingress_rejects_bad_credential_and_unmapped_symbol(client, monkeypatch):
    monkeypatch.setenv("NO7_TRADINGVIEW_ENABLED", "true")
    monkeypatch.setenv("NO7_TRADINGVIEW_WEBHOOK_TOKEN", "test-tradingview-token-0123456789")
    monkeypatch.setenv("NO7_TRADINGVIEW_SYMBOL_MAP", "{}")
    bad_auth = client.post("/api/integrations/tradingview/ai-agent-lens",
                           json={"token": "wrong", "packet": _packet()})
    assert bad_auth.status_code == 401
    mapped = client.post("/api/integrations/tradingview/ai-agent-lens",
                         json={"token": "test-tradingview-token-0123456789", "packet": _packet()})
    assert mapped.status_code == 422


def test_ingress_rejects_stale_and_oversized_packets(client, monkeypatch):
    monkeypatch.setenv("NO7_TRADINGVIEW_ENABLED", "true")
    monkeypatch.setenv("NO7_TRADINGVIEW_WEBHOOK_TOKEN", "test-tradingview-token-0123456789")
    monkeypatch.setenv("NO7_TRADINGVIEW_SYMBOL_MAP", '{"OANDA:XAUUSD":"XAUUSD"}')
    stale = _packet()
    stale["time"] = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    response = client.post("/api/integrations/tradingview/ai-agent-lens",
                           json={"token": "test-tradingview-token-0123456789", "packet": stale})
    assert response.status_code == 422
    oversized = client.post("/api/integrations/tradingview/ai-agent-lens",
                            content=b" " * 65537, headers={"Content-Type": "application/json"})
    assert oversized.status_code == 413


def test_ingress_rejects_malformed_envelopes_bad_media_and_future_bars(client, monkeypatch):
    monkeypatch.setenv("NO7_TRADINGVIEW_ENABLED", "true")
    monkeypatch.setenv("NO7_TRADINGVIEW_WEBHOOK_TOKEN", "test-tradingview-token-0123456789")
    monkeypatch.setenv("NO7_TRADINGVIEW_SYMBOL_MAP", '{"OANDA:XAUUSD":"XAUUSD"}')
    url = "/api/integrations/tradingview/ai-agent-lens"
    wrong_media = client.post(url, content="{}", headers={"Content-Type": "text/plain"})
    malformed = client.post(url, content="{", headers={"Content-Type": "application/json"})
    missing_packet = client.post(url, json={"token": "test-tradingview-token-0123456789"})
    assert wrong_media.status_code == 415
    assert malformed.status_code == 400
    assert missing_packet.status_code == 422

    future = _packet()
    future["time"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    future_response = client.post(
        url, json={"token": "test-tradingview-token-0123456789", "packet": future})
    assert future_response.status_code == 422

    tainted = _packet()
    tainted["debug_secret"] = "must-not-echo-this-value"
    invalid_schema = client.post(
        url, json={"token": "test-tradingview-token-0123456789", "packet": tainted})
    assert invalid_schema.status_code == 422
    assert "must-not-echo-this-value" not in invalid_schema.text

    monkeypatch.setenv("NO7_TRADINGVIEW_WEBHOOK_TOKEN", "short")
    short_secret = client.post(url, json={"token": "short", "packet": _packet()})
    assert short_secret.status_code == 503


def test_ingress_allows_recent_weekly_closed_bar(client, monkeypatch):
    monkeypatch.setenv("NO7_TRADINGVIEW_ENABLED", "true")
    monkeypatch.setenv("NO7_TRADINGVIEW_WEBHOOK_TOKEN", "test-tradingview-token-0123456789")
    monkeypatch.setenv("NO7_TRADINGVIEW_SYMBOL_MAP", '{"OANDA:XAUUSD":"XAUUSD"}')
    weekly = _packet()
    weekly["timeframe"] = "W"
    weekly["time"] = (datetime.now(timezone.utc) - timedelta(days=6)).isoformat()
    response = client.post("/api/integrations/tradingview/ai-agent-lens",
                           json={"token": "test-tradingview-token-0123456789", "packet": weekly})
    assert response.status_code == 202


def test_latest_shadow_view_requires_authenticated_user(client):
    response = client.get("/api/integrations/tradingview/ai-agent-lens/latest",
                          params={"symbol": "XAUUSD", "timeframe": "M5"})
    assert response.status_code == 401


@pytest.mark.parametrize("limit", [0, 101])
def test_latest_shadow_view_rejects_out_of_range_limit(client, auth, limit):
    response = client.get("/api/integrations/tradingview/ai-agent-lens/latest",
                          params={"symbol": "XAUUSD", "timeframe": "M5", "limit": limit},
                          headers=auth)
    assert response.status_code == 422


def test_latest_shadow_view_accepts_timeframe_aliases_and_keeps_mismatch_unmatched(
        client, runtime, monkeypatch, auth):
    monkeypatch.setenv("NO7_TRADINGVIEW_ENABLED", "true")
    monkeypatch.setenv("NO7_TRADINGVIEW_WEBHOOK_TOKEN", "test-tradingview-token-0123456789")
    monkeypatch.setenv("NO7_TRADINGVIEW_SYMBOL_MAP", '{"OANDA:XAGUSD":"XAGUSD"}')
    url = "/api/integrations/tradingview/ai-agent-lens"
    packet = _packet()
    packet["symbol"] = "OANDA:XAGUSD"
    response = client.post(url, json={"token": "test-tradingview-token-0123456789",
                                      "packet": packet})
    assert response.status_code == 202
    stored = runtime.db.query_one(
        "SELECT bar_close_utc FROM tradingview_evidence WHERE mapped_symbol=? LIMIT 1", ("XAGUSD",))
    runtime.db.execute(
        "INSERT INTO signals(id,t,symbol,action,score,payload) VALUES(?,?,?,?,?,?)",
        ("tv-malformed-payload", stored["bar_close_utc"], "XAGUSD", "WAIT", 0, "not-json"),
    )
    runtime.db.execute(
        "INSERT INTO signals(id,t,symbol,action,score,payload) VALUES(?,?,?,?,?,?)",
        ("tv-wrong-timeframe", stored["bar_close_utc"], "XAGUSD", "WAIT", 55,
         json.dumps({"symbol": "XAGUSD", "timeframe": "M15", "action": "WAIT",
                     "score": 55, "status": "weak"})),
    )

    for timeframe in ("M5", "5"):
        view = client.get(url + "/latest", params={"symbol": "XAGUSD",
                                                   "timeframe": timeframe}, headers=auth)
        assert view.status_code == 200
        assert len(view.json()["evidence"]) == 1
        assert view.json()["evidence"][0]["comparison"]["status"] == "no_exact_no7_bar_match"

    # A different timeframe stored first for the same symbol/bar must not mask
    # the later exact match; the table does not have a unique symbol/time key.
    runtime.db.execute(
        "INSERT INTO signals(id,t,symbol,action,score,payload) VALUES(?,?,?,?,?,?)",
        ("tv-exact-timeframe", stored["bar_close_utc"], "XAGUSD", "BUY", 67,
         json.dumps({"symbol": "XAGUSD", "timeframe": "5", "action": "BUY",
                     "score": 67, "status": "candidate"})),
    )
    exact = client.get(url + "/latest", params={"symbol": "XAGUSD", "timeframe": "M5"},
                       headers=auth)
    comparison = exact.json()["evidence"][0]["comparison"]
    assert comparison["status"] == "exact_bar_match"
    assert comparison["no7_score"] == 67


def test_latest_shadow_view_has_no_order_or_signal_write_side_effects(
        client, runtime, monkeypatch, auth):
    monkeypatch.setenv("NO7_TRADINGVIEW_ENABLED", "true")
    monkeypatch.setenv("NO7_TRADINGVIEW_WEBHOOK_TOKEN", "test-tradingview-token-0123456789")
    monkeypatch.setenv("NO7_TRADINGVIEW_SYMBOL_MAP", '{"OANDA:XAUUSD":"XAUUSD"}')
    before = {
        table: runtime.db.query_one(f"SELECT COUNT(*) AS n FROM {table}")["n"]
        for table in ("orders", "signals")
    }
    response = client.post(
        "/api/integrations/tradingview/ai-agent-lens",
        json={"token": "test-tradingview-token-0123456789", "packet": _packet()})
    assert response.status_code == 202
    view = client.get("/api/integrations/tradingview/ai-agent-lens/latest",
                      params={"symbol": "XAUUSD", "timeframe": "M5"}, headers=auth)
    assert view.status_code == 200
    after = {
        table: runtime.db.query_one(f"SELECT COUNT(*) AS n FROM {table}")["n"]
        for table in ("orders", "signals")
    }
    assert after == before


def test_latest_shadow_view_orders_out_of_order_arrivals_by_bar_close(client, monkeypatch, auth):
    monkeypatch.setenv("NO7_TRADINGVIEW_ENABLED", "true")
    monkeypatch.setenv("NO7_TRADINGVIEW_WEBHOOK_TOKEN", "test-tradingview-token-0123456789")
    monkeypatch.setenv("NO7_TRADINGVIEW_SYMBOL_MAP", '{"OANDA:XAUUSD":"XAUUSD"}')
    url = "/api/integrations/tradingview/ai-agent-lens"
    now = datetime.now(timezone.utc)
    newer = _packet()
    newer["time"] = (now - timedelta(seconds=60)).isoformat()
    older = _packet()
    older["time"] = (now - timedelta(seconds=120)).isoformat()

    for packet in (newer, older):
        response = client.post(url, json={"token": "test-tradingview-token-0123456789",
                                          "packet": packet})
        assert response.status_code == 202

    result = client.get(url + "/latest", params={"symbol": "XAUUSD", "timeframe": "M5",
                                                  "limit": 2}, headers=auth)
    assert result.status_code == 200
    closes = [row["bar_close_utc"] for row in result.json()["evidence"]]
    assert closes == sorted(closes, reverse=True)
    assert len(set(closes)) == 2


def test_ingress_future_time_tolerance_is_bounded(client, monkeypatch):
    import services.api_gateway.routes.tradingview as tradingview_route

    fixed_now = 1_800_000_000
    monkeypatch.setattr(tradingview_route.time, "time", lambda: fixed_now)
    monkeypatch.setenv("NO7_TRADINGVIEW_ENABLED", "true")
    monkeypatch.setenv("NO7_TRADINGVIEW_WEBHOOK_TOKEN", "test-tradingview-token-0123456789")
    monkeypatch.setenv("NO7_TRADINGVIEW_SYMBOL_MAP", '{"OANDA:XAUUSD":"XAUUSD"}')
    url = "/api/integrations/tradingview/ai-agent-lens"
    tolerated = _packet()
    tolerated["time"] = datetime.fromtimestamp(fixed_now + 10, timezone.utc).isoformat()
    accepted = client.post(url, json={"token": "test-tradingview-token-0123456789",
                                      "packet": tolerated})
    rejected_packet = _packet()
    rejected_packet["time"] = datetime.fromtimestamp(fixed_now + 11, timezone.utc).isoformat()
    rejected = client.post(url, json={"token": "test-tradingview-token-0123456789",
                                      "packet": rejected_packet})
    assert accepted.status_code == 202
    assert rejected.status_code == 422


def test_ingress_rejects_malformed_symbol_map_without_echoing_config(client, monkeypatch):
    monkeypatch.setenv("NO7_TRADINGVIEW_ENABLED", "true")
    monkeypatch.setenv("NO7_TRADINGVIEW_WEBHOOK_TOKEN", "test-tradingview-token-0123456789")
    monkeypatch.setenv("NO7_TRADINGVIEW_SYMBOL_MAP", '{"OANDA:XAUUSD":')
    response = client.post(
        "/api/integrations/tradingview/ai-agent-lens",
        json={"token": "test-tradingview-token-0123456789", "packet": _packet()})
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid TradingView symbol map"
    assert "OANDA:XAUUSD" not in response.text


def test_ingress_credential_rotation_rejects_old_token(client, monkeypatch):
    monkeypatch.setenv("NO7_TRADINGVIEW_ENABLED", "true")
    monkeypatch.setenv("NO7_TRADINGVIEW_WEBHOOK_TOKEN", "old-tradingview-token-0123456789")
    monkeypatch.setenv("NO7_TRADINGVIEW_SYMBOL_MAP", '{"OANDA:XAUUSD":"XAUUSD"}')
    url = "/api/integrations/tradingview/ai-agent-lens"
    packet = _packet()
    accepted = client.post(url, json={"token": "old-tradingview-token-0123456789",
                                      "packet": packet})
    assert accepted.status_code == 202

    monkeypatch.setenv("NO7_TRADINGVIEW_WEBHOOK_TOKEN", "new-tradingview-token-0123456789")
    old_credential = client.post(url, json={"token": "old-tradingview-token-0123456789",
                                            "packet": packet})
    new_credential = client.post(url, json={"token": "new-tradingview-token-0123456789",
                                            "packet": packet})
    assert old_credential.status_code == 401
    assert "old-tradingview-token" not in old_credential.text
    assert new_credential.status_code == 202
    assert new_credential.json()["duplicate"] is True
