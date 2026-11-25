from __future__ import annotations

import json
import uuid
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
    audit_before = runtime.db.query_one("SELECT COALESCE(MAX(id), 0) AS n FROM audit")["n"]
    first = client.post("/api/integrations/tradingview/ai-agent-lens", json=body)
    second = client.post("/api/integrations/tradingview/ai-agent-lens", json=body)
    assert first.status_code == second.status_code == 202
    assert first.json()["quality"] == "shadow_only"
    assert second.json()["duplicate"] is True
    rows = runtime.db.query("SELECT payload FROM tradingview_evidence WHERE mapped_symbol=?", ("XAUUSD",))
    assert len(rows) == 1
    assert "test-tradingview-token" not in rows[0]["payload"]
    assert "stop" not in rows[0]["payload"]
    audit_rows = runtime.db.query(
        "SELECT detail FROM audit WHERE action='tradingview.evidence' AND id>?", (audit_before,))
    assert len(audit_rows) == 2
    assert all("test-tradingview-token" not in row["detail"] for row in audit_rows)
    assert all('"hash"' in row["detail"] for row in audit_rows)
    assert "test-tradingview-token" not in first.text + second.text
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


def test_latest_shadow_view_rejects_non_default_tenant(client, runtime, settings):
    """A tenant without an isolated trading runtime cannot read shared shadow data."""
    from integrations.tradingview.normalizer import normalize_lens_packet
    from services.api_gateway.auth import create_token
    from services.api_gateway.tenants import create_tenant

    email = f"lens-tenant-{uuid.uuid4().hex[:12]}@no7.ai"
    created = create_tenant(runtime.db, "Lens isolation test", email,
                            "longenough1", "test")
    payload_sha256 = None
    try:
        evidence = normalize_lens_packet(_packet(), mapped_symbol="XAUUSD")
        payload_sha256 = evidence.payload_sha256
        runtime.db.store_tradingview_evidence(evidence.model_dump(mode="json"))
        token, _ = create_token(settings, email, "admin")
        response = client.get(
            "/api/integrations/tradingview/ai-agent-lens/latest",
            params={"symbol": "XAUUSD", "timeframe": "M5"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403
        assert "evidence" not in response.json()
    finally:
        if payload_sha256:
            runtime.db.execute("DELETE FROM tradingview_evidence WHERE payload_sha256=?",
                               (payload_sha256,))
        runtime.db.execute("DELETE FROM users WHERE email=?", (email,))
        runtime.db.execute("DELETE FROM tenants WHERE id=?", (created["tenant"]["id"],))


def test_latest_shadow_view_batches_no7_signal_lookup(client, runtime, auth, monkeypatch):
    """A full 100-row shadow view uses a bounded number of signal queries."""
    from integrations.tradingview.normalizer import normalize_lens_packet

    now = datetime.now(timezone.utc)
    for offset in range(5):
        packet = _packet()
        packet["timeframe"] = "5"
        packet["time"] = (now - timedelta(minutes=5 * offset)).isoformat()
        evidence = normalize_lens_packet(packet, mapped_symbol="XAUUSD")
        runtime.db.store_tradingview_evidence(evidence.model_dump(mode="json"))

    original_query = runtime.db.query
    signal_reads = 0

    def count_signal_reads(sql, params=()):
        nonlocal signal_reads
        if "FROM signals WHERE symbol=? AND t IN (" in sql:
            signal_reads += 1
        return original_query(sql, params)

    monkeypatch.setattr(runtime.db, "query", count_signal_reads)
    response = client.get(
        "/api/integrations/tradingview/ai-agent-lens/latest",
        params={"symbol": "XAUUSD", "timeframe": "M5", "limit": 100},
        headers=auth,
    )

    assert response.status_code == 200, response.text
    assert len(response.json()["evidence"]) >= 5
    assert signal_reads == 1


@pytest.mark.parametrize("role", ["admin", "viewer", "trader"])
def test_latest_shadow_view_is_readable_for_authenticated_tenant_roles_without_side_effects(
        client, runtime, auth, role):
    """Authenticated tenant roles can read advisory evidence without trading side effects."""
    from integrations.tradingview.normalizer import normalize_lens_packet

    packet = _packet()
    evidence = normalize_lens_packet(packet, mapped_symbol="XAUUSD")
    assert runtime.db.store_tradingview_evidence(evidence.model_dump(mode="json")) is True
    before = {
        table: runtime.db.query_one(f"SELECT COUNT(*) AS n FROM {table}")["n"]
        for table in ("orders", "signals")
    }

    email = f"lens-{role}-{uuid.uuid4().hex[:12]}@no7.ai"
    password = "longenough1"
    created = client.post("/api/users", json={"email": email, "password": password,
                                              "role": role}, headers=auth)
    assert created.status_code == 200, created.text
    try:
        login = client.post("/api/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200, login.text
        response = client.get(
            "/api/integrations/tradingview/ai-agent-lens/latest",
            params={"symbol": "XAUUSD", "timeframe": "M5"},
            headers={"Authorization": f"Bearer {login.json()['token']}"},
        )
        assert response.status_code == 200, response.text
        rows = response.json()["evidence"]
        own_row = next((row for row in rows
                        if row["payload_sha256"] == evidence.payload_sha256), None)
        assert own_row is not None
        assert own_row["comparison"]["scores_are_separate"] is True
        after = {
            table: runtime.db.query_one(f"SELECT COUNT(*) AS n FROM {table}")["n"]
            for table in ("orders", "signals")
        }
        assert after == before
    finally:
        client.delete(f"/api/users/{email}", headers=auth)


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
    from integrations.tradingview.normalizer import normalize_lens_packet
    expected_hashes = {
        normalize_lens_packet(packet, mapped_symbol="XAUUSD").payload_sha256
        for packet in (newer, older)
    }

    for packet in (newer, older):
        response = client.post(url, json={"token": "test-tradingview-token-0123456789",
                                          "packet": packet})
        assert response.status_code == 202

    result = client.get(url + "/latest", params={"symbol": "XAUUSD", "timeframe": "M5",
                                                  "limit": 100}, headers=auth)
    assert result.status_code == 200
    own_rows = [row for row in result.json()["evidence"]
                if row["payload_sha256"] in expected_hashes]
    assert len(own_rows) == 2
    closes = [row["bar_close_utc"] for row in own_rows]
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
