"""Delivery over a real socket, not a mock.

The unit suite (`test_notify_channels.py`) checks the decisions; this one checks the
wire: a local HTTP server that speaks the Telegram and LINE shapes receives the POST,
so URL building, headers, JSON bodies, retries, `Retry-After`, pacing and redaction
are all exercised end to end.

Why a local server: this sandbox cannot reach api.telegram.org, and a test that
"would work with real tokens" is exactly the kind of claim this project does not make.
The base-URL override that makes this possible is production code, guarded so a
plaintext base is only accepted for a private host.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from packages.persistence.db import Database
from services.notification.notifier import Notifier, safe_base


class FakeProvider:
    """Telegram/LINE-shaped server: records requests, replays scripted responses."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.responses: list[tuple[int, dict, dict]] = []   # (status, body, headers)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.port = self._server.server_address[1]
        self.thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> "FakeProvider":
        self.thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _handler(self):
        provider = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):  # noqa: N802 - http.server API
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8", "replace")
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    payload = {"_raw": raw}
                provider.requests.append({"path": self.path, "payload": payload,
                                          "headers": dict(self.headers)})
                status, body, headers = (provider.responses.pop(0) if provider.responses
                                         else (200, {"ok": True}, {}))
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for key, value in headers.items():
                    self.send_header(key, str(value))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):  # keep pytest output clean
                return

        return Handler


@pytest.fixture()
def provider():
    server = FakeProvider().start()
    yield server
    server.stop()


@pytest.fixture()
def db(tmp_path):
    database = Database(str(tmp_path / "delivery.sqlite3"))
    yield database
    database.close()


def notifier(db, provider, **cfg) -> Notifier:
    env = {"TELEGRAM_BOT_TOKEN": "123456:TEST-TOKEN", "TELEGRAM_CHAT_ID": "-100123",
           "LINE_CHANNEL_TOKEN": "line-secret-token", "LINE_TARGET_ID": "Udeadbeef"}
    base = {"channels": ["inapp", "telegram"], "telegram_enabled": True,
            "dedupe_seconds": 0, "min_interval_seconds": 0, "retry_backoff_seconds": 0,
            "telegram_api_base": provider.base, "line_api_base": provider.base}
    base.update(cfg)
    return Notifier(db, min_score=70, cfg=base, env={**env, **cfg.pop("env", {})})


def test_telegram_message_reaches_the_wire(db, provider):
    n = notifier(db, provider)
    alert = n.emit("warning", "spread สูง", "EURUSD spread 38 points", symbol="EURUSD")
    assert len(provider.requests) == 1
    sent = provider.requests[0]
    assert sent["path"] == "/bot123456:TEST-TOKEN/sendMessage"
    assert sent["payload"]["chat_id"] == "-100123"          # string, not int
    assert sent["payload"]["text"].startswith("[No7 AI] spread สูง")
    assert "38 points" in sent["payload"]["text"]
    delivery = alert.meta["delivery"][0]
    assert delivery == {"channel": "telegram", "ok": True, "status": 200,
                        "error": "", "attempts": 1}
    assert n.status()["state"] == "external"
    assert n.status()["channels"]["telegram"]["ok"] is True


def test_line_uses_the_bearer_token_and_push_shape(db, provider):
    n = Notifier(db, min_score=70,
                 cfg={"channels": ["line"], "line_enabled": True, "dedupe_seconds": 0,
                      "min_interval_seconds": 0, "line_api_base": provider.base},
                 env={"LINE_CHANNEL_TOKEN": "line-secret-token", "LINE_TARGET_ID": "U1"})
    n.emit("info", "hello", "world")
    sent = provider.requests[0]
    assert sent["path"] == "/v2/bot/message/push"
    assert sent["headers"]["Authorization"] == "Bearer line-secret-token"
    assert sent["payload"]["to"] == "U1"
    assert sent["payload"]["messages"][0]["type"] == "text"


def test_a_429_is_retried_after_the_retry_after_delay(db, provider):
    provider.responses = [(429, {"ok": False, "description": "Too Many Requests"},
                           {"Retry-After": "0"})]
    n = notifier(db, provider)
    alert = n.emit("warning", "x", "y")
    assert len(provider.requests) == 2, "the second attempt must happen"
    assert alert.meta["delivery"][0]["ok"] is True
    assert alert.meta["delivery"][0]["attempts"] == 2
    assert n.status()["retries"] == 1


def test_a_5xx_is_retried_then_reported_as_a_failure(db, provider):
    provider.responses = [(503, {"ok": False}, {}), (502, {"ok": False}, {})]
    n = notifier(db, provider, retry_attempts=2)
    alert = n.emit("critical", "down", "broker unreachable")
    assert len(provider.requests) == 2
    delivery = alert.meta["delivery"][0]
    assert delivery["ok"] is False and delivery["status"] == 502
    assert alert.id.startswith("A"), "the in-app alert still exists"
    status = n.status()
    assert status["state"] == "failing" and status["failing"] == ["telegram"]
    assert status["channels"]["telegram"]["failures"] == 1


def test_a_400_is_not_retried(db, provider):
    provider.responses = [(400, {"ok": False, "description": "chat not found"}, {})]
    n = notifier(db, provider)
    alert = n.emit("warning", "x", "y")
    assert len(provider.requests) == 1, "a bad chat id will never fix itself"
    assert alert.meta["delivery"][0]["status"] == 400
    assert "chat not found" in n.status()["channels"]["telegram"]["error"]


def test_unreachable_provider_does_not_raise_and_is_reported(db):
    n = Notifier(db, min_score=70,
                 cfg={"channels": ["telegram"], "telegram_enabled": True,
                      "dedupe_seconds": 0, "min_interval_seconds": 0,
                      "retry_attempts": 2, "retry_backoff_seconds": 0,
                      "telegram_api_base": "http://127.0.0.1:9"},   # nothing listens there
                 env={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"})
    alert = n.emit("critical", "x", "y")
    delivery = alert.meta["delivery"][0]
    assert delivery["ok"] is False and delivery["status"] == 0
    assert delivery["error"], "the reason must be kept"
    assert n.status()["state"] == "failing"


def test_the_bot_token_never_appears_in_status_or_errors(db, provider):
    provider.responses = [(500, {"ok": False, "description": "boom 123456:TEST-TOKEN"}, {})]
    n = notifier(db, provider, retry_attempts=1)
    n.emit("critical", "x", "y")
    status_text = json.dumps(n.status(), ensure_ascii=False)
    assert "TEST-TOKEN" not in status_text, status_text
    assert "***" in n.status()["channels"]["telegram"]["error"]
    rows = db.query("SELECT payload FROM alerts")
    assert "TEST-TOKEN" not in str([dict(r)["payload"] for r in rows])


def test_a_storm_is_paced_and_counted_instead_of_flooding(db, provider):
    n = notifier(db, provider, min_interval_seconds=60)
    first = n.emit("info", "t1", "m1")
    second = n.emit("info", "t2", "m2")
    assert len(provider.requests) == 1, "the second message must be held back"
    assert second.meta["delivery"][0]["ok"] is None
    assert second.meta["delivery"][0]["skipped"] == "pacing"
    assert n.dropped == 1 and n.status()["dropped"] == 1
    assert first.meta["delivery"][0]["ok"] is True
    # a skip is not a failure: health must not flip to "failing"
    assert n.status()["state"] == "external"
    assert n.status()["channels"]["telegram"]["ok"] is True
    assert n.status()["channels"]["telegram"]["skipped"] == 1


def test_long_messages_are_truncated_to_the_provider_limit(db, provider):
    n = notifier(db, provider)
    n.emit("info", "long", "x" * 6000)
    text = provider.requests[0]["payload"]["text"]
    assert len(text) == 4096 and text.endswith("…")


def test_an_unknown_level_becomes_a_visible_warning(db, provider):
    """A typo must not raise after the message already went out."""
    n = notifier(db, provider)
    alert = n.emit("warn", "t", "m")          # not a valid level
    assert alert.level == "warning"
    assert alert.meta["level_coerced_from"] == "warn"
    assert len(provider.requests) == 1


def test_send_test_reports_every_channel(db, provider):
    n = notifier(db, provider)
    result = n.send_test()
    assert result["ok"] is True
    assert result["deliveries"][0]["channel"] == "telegram"
    assert result["deliveries"][0]["ok"] is True


def test_a_paced_test_is_not_reported_as_a_failure(db, provider):
    n = notifier(db, provider, min_interval_seconds=60)
    assert n.send_test()["ok"] is True
    second = n.send_test()
    assert second["ok"] is True, "pacing is not a delivery failure"
    assert second["paced"] == ["telegram"]
    assert "ลองใหม่" in second["note"]
    assert n.dropped == 1


# ------------------------------------------------------------------ base safety
def test_public_https_base_is_accepted():
    url, warning = safe_base("https://api.telegram.org/", "https://fallback")
    assert url == "https://api.telegram.org" and warning == ""


def test_plaintext_base_is_only_allowed_for_private_hosts():
    for allowed in ("http://127.0.0.1:8080", "http://localhost:9", "http://10.1.2.3:80",
                    "http://192.168.1.5", "http://172.20.0.9"):
        url, warning = safe_base(allowed, "https://fallback")
        assert url == allowed.rstrip("/") and warning == "", allowed
    for refused in ("http://api.telegram.org", "http://8.8.8.8", "http://172.32.0.1"):
        url, warning = safe_base(refused, "https://fallback")
        assert url == "https://fallback" and "plaintext" in warning
    url, warning = safe_base("ftp://example.com", "https://fallback")
    assert url == "https://fallback" and "http(s)" in warning


def test_a_refused_base_is_visible_in_status(db):
    n = Notifier(db, min_score=70,
                 cfg={"channels": ["telegram"], "telegram_enabled": True,
                      "telegram_api_base": "http://api.telegram.org"},
                 env={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"})
    assert n.bases["telegram"] == "https://api.telegram.org"
    assert n.status()["base_warnings"], "silently ignoring the config would hide a typo"
