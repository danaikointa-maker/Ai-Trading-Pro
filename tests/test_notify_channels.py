"""Outbound alert channels: configured, delivered, and — crucially — diagnosable.

The regression these tests exist for: the notifier used to call `httpx`, which is
not installed here, so every Telegram/LINE send raised inside a bare `except` and
nothing reached the operator while nothing complained either. A channel that is
configured must therefore either deliver, or say that it did not.
"""
from __future__ import annotations

import json

import pytest

from packages.persistence.db import Database
from services.notification.notifier import Notifier


@pytest.fixture()
def db(tmp_path):
    database = Database(str(tmp_path / "notify.sqlite3"))
    yield database
    database.close()


class FakeTransport:
    """Records what would have been sent; can be told to fail."""

    def __init__(self, ok: bool = True, status: int = 200, error: str = "") -> None:
        self.calls: list[dict] = []
        self.ok, self.status, self.error = ok, status, error

    def __call__(self, url, payload, headers):
        self.calls.append({"url": url, "payload": payload, "headers": headers})
        return {"ok": self.ok, "status": self.status, "error": self.error}


def build(db, env=None, transport=None, **cfg):
    base = {"channels": ["inapp"], "dedupe_seconds": 0}
    base.update(cfg)
    return Notifier(db, min_score=70, cfg=base, transport=transport or FakeTransport(),
                    env=env or {})


def test_nothing_external_is_sent_without_a_token(db):
    transport = FakeTransport()
    notifier = build(db, env={}, transport=transport, telegram_enabled=True)
    alert = notifier.emit("info", "hello", "world")
    assert transport.calls == []
    assert alert.channel == "inapp"
    assert notifier.status()["state"] == "inapp-only"
    assert "ไม่มีช่องทางภายนอก" in notifier.status()["disabled_reason"]


def test_a_token_alone_is_not_consent_to_send(db):
    """Having a token in the environment must not start outbound traffic by itself."""
    transport = FakeTransport()
    notifier = build(db, env={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"},
                     transport=transport)
    notifier.emit("info", "hello", "world")
    assert transport.calls == []
    assert notifier.external_channels == []


def test_telegram_delivers_when_enabled_and_reports_success(db):
    transport = FakeTransport()
    notifier = build(db, env={"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42"},
                     transport=transport, telegram_enabled=True)
    alert = notifier.emit("critical", "Kill switch", "reason: manual")
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["url"].endswith("/bottok/sendMessage")
    assert call["payload"]["chat_id"] == "42"
    assert "Kill switch" in call["payload"]["text"]
    assert alert.channel == "inapp,telegram"
    assert notifier.status()["state"] == "external"
    assert notifier.status()["channels"]["telegram"]["ok"] is True

    row = notifier.recent(1)[0]
    assert row["payload"]["delivery"][0]["channel"] == "telegram"
    assert row["payload"]["delivery"][0]["ok"] is True


def test_a_failing_channel_is_visible_and_never_loses_the_in_app_alert(db):
    transport = FakeTransport(ok=False, status=401, error="HTTP 401: unauthorized")
    notifier = build(db, env={"LINE_CHANNEL_TOKEN": "bad", "LINE_TARGET_ID": "U1"},
                     transport=transport, line_enabled=True)
    alert = notifier.emit("warning", "Stop moved", "breakeven")

    # the operator still sees the alert in the dashboard
    assert alert.id.startswith("A")
    assert notifier.recent(1)[0]["title"] == "Stop moved"
    # ...and the broken channel is reported, not swallowed
    status = notifier.status()
    assert status["state"] == "failing"
    assert status["failing"] == ["line"]
    assert status["channels"]["line"]["failures"] == 1
    assert "401" in status["channels"]["line"]["error"]


def test_a_transport_that_raises_is_recorded_not_hidden(db):
    def boom(url, payload, headers):
        raise RuntimeError("no route to host")

    notifier = build(db, env={"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42"},
                     transport=boom, telegram_enabled=True)
    notifier.emit("critical", "Emergency close", "flatten all")
    record = notifier.status()["channels"]["telegram"]
    assert record["ok"] is False
    assert "no route to host" in record["error"]


def test_delivery_status_survives_a_restart(db):
    transport = FakeTransport(ok=False, status=500, error="HTTP 500")
    build(db, env={"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42"},
          transport=transport, telegram_enabled=True).emit("info", "x", "y")
    fresh = build(db, env={"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42"},
                  transport=FakeTransport(), telegram_enabled=True)
    assert fresh.status()["channels"]["telegram"]["failures"] == 1


def test_duplicate_alerts_are_deduped_without_extra_network_calls(db):
    transport = FakeTransport()
    notifier = build(db, env={"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42"},
                     transport=transport, telegram_enabled=True, dedupe_seconds=60)
    notifier.emit("info", "same", "message", symbol="XAUUSD")
    second = notifier.emit("info", "same", "message", symbol="XAUUSD")
    assert len(transport.calls) == 1
    assert second.id.startswith("D")
    assert second.meta["deduped"] is True


def test_webhook_payload_is_generic_json(db):
    transport = FakeTransport()
    notifier = build(db, env={}, transport=transport, webhook_enabled=True,
                     webhook_url="https://example.invalid/hook")
    notifier.emit("success", "Trade closed", "+12.40 USD")
    call = transport.calls[0]
    assert call["url"] == "https://example.invalid/hook"
    assert call["payload"]["title"] == "Trade closed"
    assert json.dumps(call["payload"])  # serialisable


def test_send_test_explains_itself_when_nothing_is_configured(db):
    result = build(db, env={}).send_test()
    assert result["ok"] is False
    assert result["deliveries"] == []
    assert "token" in result["reason"]


def test_send_test_reports_each_channel(db):
    transport = FakeTransport()
    notifier = build(db, env={"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42"},
                     transport=transport, telegram_enabled=True)
    result = notifier.send_test()
    assert result["ok"] is True
    assert [d["channel"] for d in result["deliveries"]] == ["telegram"]
    assert transport.calls[0]["payload"]["text"].startswith("[No7 AI]")


def test_status_never_echoes_a_token(db):
    secret = "123456:AAH-super-secret-token-value"
    notifier = build(db, env={"TELEGRAM_BOT_TOKEN": secret, "TELEGRAM_CHAT_ID": "42"},
                     transport=FakeTransport(), telegram_enabled=True)
    notifier.emit("info", "x", "y")
    dumped = json.dumps(notifier.status())
    assert secret not in dumped
    assert "Bearer" not in dumped


def test_typed_config_values_do_not_crash_the_notifier(db):
    """`telegram_chat_id: -1001234567890` is an int after YAML parsing."""
    transport = FakeTransport()
    notifier = build(db, env={"TELEGRAM_BOT_TOKEN": "tok"}, transport=transport,
                     telegram_enabled=True, telegram_chat_id=-1001234567890)
    notifier.emit("info", "hello", "world")
    assert transport.calls[0]["payload"]["chat_id"] == "-1001234567890"
