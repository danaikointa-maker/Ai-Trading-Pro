"""The perimeter: headers, CORS, and who the client is.

Everything here protects the token in `localStorage` and the orders it can place:
injected script (CSP), framing (clickjacking), and forged forwarding headers that
would otherwise hand out a fresh rate-limit budget per request.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from services.api_gateway.netutil import client_ip, is_secure, parse_networks
from services.api_gateway.security import CSP, SecurityHeadersMiddleware, parse_origins

BASE = ("x-content-type-options", "x-frame-options", "referrer-policy",
        "permissions-policy", "cross-origin-opener-policy")


def _app_client(runtime, **kwargs) -> TestClient:
    from services.api_gateway.app import create_app
    return TestClient(create_app(runtime), **kwargs)


# --------------------------------------------------------------------- headers
def test_headers_land_on_html_json_and_error_responses(client):
    for path in ("/", "/api/system/health", "/api/does-not-exist"):
        headers = client.get(path).headers
        for name in BASE:
            assert name in headers, f"{path} is missing {name}"
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"
        assert "content-security-policy" in headers, f"{path} has no CSP"


def test_csp_actually_blocks_the_dangerous_things(client):
    policy = client.get("/").headers["content-security-policy"]
    directives = {part.split()[0]: part.strip() for part in policy.split(";")}
    assert "default-src 'self'" in policy
    assert directives["frame-ancestors"] == "frame-ancestors 'none'"
    assert directives["object-src"] == "object-src 'none'"
    assert "script-src 'self'" in policy
    # the SPA needs its own websocket and inline style attributes for Vue bindings
    assert "connect-src 'self' ws: wss:" in policy
    assert "style-src 'self' 'unsafe-inline'" in policy
    assert "'unsafe-eval'" not in policy


def test_swagger_docs_get_their_own_relaxed_policy(client):
    """The CDN-backed API docs must still work; only that path may reach out."""
    res = client.get("/api/docs")
    assert res.status_code == 200
    policy = res.headers["content-security-policy"]
    assert "https://cdn.jsdelivr.net" in policy
    dashboard = client.get("/").headers["content-security-policy"]
    assert "cdn.jsdelivr.net" not in dashboard, "the app itself must not need a CDN"


def test_hsts_is_never_sent_over_plain_http(client):
    # Over HTTP the browser would cache the upgrade and brick the dev install.
    assert "strict-transport-security" not in client.get("/").headers


def test_a_trusted_proxy_may_report_https_and_gets_hsts(runtime):
    proxy = TestClient(_app_is(runtime), client=("127.0.0.1", 51000))
    res = proxy.get("/", headers={"X-Forwarded-Proto": "https"})
    assert res.headers["strict-transport-security"].startswith("max-age=15552000")


def test_an_untrusted_peer_cannot_claim_https(runtime):
    stranger = TestClient(_app_is(runtime), client=("203.0.113.9", 51000))
    res = stranger.get("/", headers={"X-Forwarded-Proto": "https"})
    assert "strict-transport-security" not in res.headers, "spoofed scheme must be ignored"


def _app_is(runtime):
    from services.api_gateway.app import create_app
    return create_app(runtime)


def test_csp_mode_can_be_relaxed_for_debugging(runtime, monkeypatch):
    monkeypatch.setenv("NO7_CSP_MODE", "report")
    res = TestClient(_app_is(runtime)).get("/")
    assert "content-security-policy-report-only" in res.headers
    assert "content-security-policy" not in res.headers

    monkeypatch.setenv("NO7_CSP_MODE", "off")
    res = TestClient(_app_is(runtime)).get("/")
    assert "content-security-policy" not in res.headers
    assert "content-security-policy-report-only" not in res.headers
    assert res.headers["x-frame-options"] == "DENY"   # the rest still applies


def test_hsts_can_be_disabled(runtime, monkeypatch):
    monkeypatch.setenv("NO7_HSTS", "false")
    proxy = TestClient(_app_is(runtime), client=("127.0.0.1", 51000))
    res = proxy.get("/", headers={"X-Forwarded-Proto": "https"})
    assert "strict-transport-security" not in res.headers


# ------------------------------------------------------------------------ cors
def test_no_cross_origin_caller_is_allowed_by_default(client):
    res = client.get("/api/system/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in res.headers
    res = client.get("/api/system/health", headers={"Origin": "http://localhost:5173"})
    assert "access-control-allow-origin" not in res.headers


def test_an_explicit_allowlist_is_honoured(runtime, monkeypatch):
    monkeypatch.setenv("NO7_CORS_ORIGINS", "http://localhost:5173, https://dash.example.com/")
    test_client = TestClient(_app_is(runtime))
    allowed = test_client.get("/api/system/health", headers={"Origin": "http://localhost:5173"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    trailing = test_client.get("/api/system/health",
                               headers={"Origin": "https://dash.example.com"})
    assert trailing.headers["access-control-allow-origin"] == "https://dash.example.com"
    blocked = test_client.get("/api/system/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in blocked.headers


def test_health_says_what_the_perimeter_is_doing(client):
    security = client.get("/api/system/health").json()["security"]
    assert security["require_auth"] is True
    assert security["jwt_secret_from_env"] is True     # conftest sets NO7_JWT_SECRET
    assert security["csp_mode"] in ("enforce", "report", "off")
    assert security["hsts_when_https"] is True
    assert isinstance(security["trusted_proxies"], list)
    assert security["cors"]["wildcard"] is False


# --------------------------------------------------------------- client identity
def _scope(peer: str, headers: dict[str, str] | None = None, scheme: str = "http") -> dict:
    return {"type": "http", "client": (peer, 40000), "scheme": scheme,
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]}


def test_forwarded_headers_from_a_stranger_are_ignored():
    trusted = parse_networks(["127.0.0.1/32"])
    scope = _scope("203.0.113.9", {"x-forwarded-for": "10.9.9.9"})
    assert client_ip(scope, trusted) == "203.0.113.9"


def test_a_trusted_proxy_supplies_the_first_untrusted_hop():
    trusted = parse_networks(["127.0.0.1/32", "10.0.0.0/8"])
    scope = _scope("127.0.0.1", {"x-forwarded-for": "198.51.100.7, 10.1.2.3"})
    assert client_ip(scope, trusted) == "198.51.100.7"
    # a chain of only proxies falls back to the socket peer, not to a proxy address
    all_proxies = _scope("127.0.0.1", {"x-forwarded-for": "10.0.0.5, 10.0.0.6"})
    assert client_ip(all_proxies, trusted) == "127.0.0.1"


def test_garbage_forwarded_values_do_not_crash_or_win():
    trusted = parse_networks(["127.0.0.1/32"])
    scope = _scope("127.0.0.1", {"x-forwarded-for": "not-an-ip, "})
    assert client_ip(scope, trusted) == "127.0.0.1"


def test_network_parsing_tolerates_what_people_type():
    assert [str(n) for n in parse_networks("10.0.0.1, 192.168.0.0/16 ,junk")] == [
        "10.0.0.1/32", "192.168.0.0/16"]
    assert parse_networks(None) == [] and parse_networks("") == []


def test_secure_detection_needs_a_trusted_peer():
    trusted = parse_networks(["127.0.0.1/32"])
    assert is_secure(_scope("127.0.0.1", {"x-forwarded-proto": "https"}), trusted) is True
    assert is_secure(_scope("203.0.113.9", {"x-forwarded-proto": "https"}), trusted) is False
    assert is_secure(_scope("127.0.0.1", {}, scheme="https"), trusted) is True


def test_rate_limit_identity_cannot_be_rotated_by_a_stranger(settings):
    from services.api_gateway.ratelimit import RateLimiter, RateLimitMiddleware

    middleware = RateLimitMiddleware(app=None, limiter=RateLimiter({}), settings=settings,
                                     trusted_proxies=["127.0.0.1/32"])
    first = middleware._identity(_scope("203.0.113.9", {"x-forwarded-for": "10.0.0.1"}))
    second = middleware._identity(_scope("203.0.113.9", {"x-forwarded-for": "10.0.0.2"}))
    assert first == second == "ip:203.0.113.9"

    from_proxy = middleware._identity(_scope("127.0.0.1", {"x-forwarded-for": "198.51.100.1"}))
    assert from_proxy == "ip:198.51.100.1"


def test_login_throttle_keys_on_the_real_client_not_a_forged_header(client):
    """Rotating X-Forwarded-For used to reset the password-guessing budget."""
    import time
    import uuid

    email = f"throttle-{uuid.uuid4().hex[:8]}@no7.ai"
    for i in range(3):
        res = client.post("/api/auth/login", json={"email": email, "password": "wrong-password"},
                          headers={"X-Forwarded-For": f"198.51.100.{i + 1}"})
        assert res.status_code in (401, 429)
    rows = client.app.state.runtime.db.query(
        "SELECT key, failures FROM login_throttle WHERE key LIKE ?", (f"{email}|%",))
    assert len(rows) == 1, "one bucket per real client, not one per forged header"
    assert rows[0]["key"] == f"{email}|testclient"
    assert int(rows[0]["failures"]) >= 1
    assert time.time() > 0


def test_cors_parse_keeps_wildcard_deliberate():
    assert parse_origins("*, https://a.example") == ["*", "https://a.example"]
    assert parse_origins(None) == [] and parse_origins("") == []


def test_csp_constant_has_no_wildcard_sources():
    assert "'unsafe-eval'" not in CSP and "*" not in CSP.replace("wss:", "").replace("ws:", "")


def test_middleware_preserves_existing_headers(runtime):
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def handler(request):
        return JSONResponse({"ok": True}, headers={"X-Frame-Options": "SAMEORIGIN",
                                                  "Cache-Control": "no-store"})

    inner = Starlette(routes=[Route("/", handler)])
    app = SecurityHeadersMiddleware(inner, trusted_proxies=["127.0.0.1/32"])
    res = TestClient(app).get("/")
    assert res.headers["x-frame-options"] == "SAMEORIGIN", "an explicit header wins"
    assert res.headers["cache-control"] == "no-store"
    assert res.headers["x-content-type-options"] == "nosniff"
    assert json.loads(res.content) == {"ok": True}
