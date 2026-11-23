"""Outbound alert channels: configured, delivered, and — crucially — diagnosable.

The regression these tests exist for: the notifier used to call `httpx`, which is
not installed here, so every Telegram/LINE send raised inside a bare `except` and
nothing reached the operator while nothing complained either. A channel that is
configured must therefore either deliver, or say that it did not.
"""
from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

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


def test_event_dedupe_key_isolated_per_account_and_action(db):
    transport = FakeTransport()
    notifier = build(db, env={"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42"},
                     transport=transport, telegram_enabled=True, dedupe_seconds=0,
                     min_interval_seconds=0)
    first = notifier.emit("warning", "Management modify: unknown", "ticket T-1",
                          symbol="XAUUSD", dedupe_key="account-a:T-1:sl-1995", dedupe_seconds=300)
    repeated = notifier.emit("warning", "Management modify: unknown", "ticket T-1",
                             symbol="XAUUSD", dedupe_key="account-a:T-1:sl-1995", dedupe_seconds=300)
    other_account = notifier.emit("warning", "Management modify: unknown", "ticket T-1",
                                  symbol="XAUUSD", dedupe_key="account-b:T-1:sl-1995", dedupe_seconds=300)

    assert first.id.startswith("A")
    assert repeated.id.startswith("D")
    assert other_account.id.startswith("A")
    assert len(transport.calls) == 2


def test_keyed_alert_dedupe_survives_notifier_restart(tmp_path):
    path = tmp_path / "persistent-notify.sqlite3"
    first_db = Database(path)
    first_transport = FakeTransport()
    first = build(first_db, env={"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42"},
                  transport=first_transport, telegram_enabled=True, min_interval_seconds=0)
    original = first.emit("warning", "Management modify: unknown", "ticket T-9",
                          symbol="XAUUSD", dedupe_key="account-hash:T-9:sl-1995",
                          dedupe_seconds=300)
    first_db.close()

    restarted_db = Database(path)
    restarted_transport = FakeTransport()
    try:
        restarted = build(restarted_db,
                          env={"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42"},
                          transport=restarted_transport, telegram_enabled=True,
                          min_interval_seconds=0)
        duplicate = restarted.emit(
            "warning", "Management modify: unknown", "ticket T-9", symbol="XAUUSD",
            dedupe_key="account-hash:T-9:sl-1995", dedupe_seconds=300)

        assert original.id.startswith("A")
        assert duplicate.id.startswith("D")
        assert duplicate.meta["deduped"] is True
        assert restarted_transport.calls == []
        row = restarted_db.query_one("SELECT dedupe_fingerprint FROM alerts WHERE id=?",
                                     (original.id,))
        assert row["dedupe_fingerprint"]
        assert "account-hash" not in row["dedupe_fingerprint"]
    finally:
        restarted_db.close()


def test_keyed_alert_claim_is_atomic_across_notifier_instances(tmp_path):
    path = tmp_path / "concurrent-notify.sqlite3"
    first_db, second_db = Database(path), Database(path)
    first_transport, second_transport = FakeTransport(), FakeTransport()
    first = build(first_db, env={"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42"},
                  transport=first_transport, telegram_enabled=True, min_interval_seconds=0)
    second = build(second_db, env={"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42"},
                   transport=second_transport, telegram_enabled=True, min_interval_seconds=0)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda notifier: notifier.emit(
                "warning", "Management modify: unknown", "ticket T-10", symbol="XAUUSD",
                dedupe_key="account-hash:T-10:sl-1995", dedupe_seconds=300),
                                    (first, second)))

        assert sum(result.id.startswith("A") for result in results) == 1
        assert sum(result.id.startswith("D") for result in results) == 1
        assert len(first_transport.calls) + len(second_transport.calls) == 1
        assert first_db.query_one("SELECT COUNT(*) AS n FROM alerts")["n"] == 1
    finally:
        first_db.close()
        second_db.close()


def test_keyed_alert_outbox_survives_restart_before_first_send(tmp_path):
    path = tmp_path / "queued-notify.sqlite3"
    first_db = Database(path)
    first_transport = FakeTransport()
    first = Notifier(first_db, cfg={"channels": ["inapp"], "telegram_enabled": True,
                                    "min_interval_seconds": 0},
                     env={"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42"},
                     transport=first_transport, background=True)
    # Simulate a process stopping after the atomic database commit and before the
    # background outbox worker can be started.
    first.drain_async = lambda: False
    alert = first.emit("warning", "Management modify: unknown", "ticket T-11",
                       symbol="XAUUSD", dedupe_key="account-hash:T-11:sl-1995",
                       dedupe_seconds=300)
    assert first_transport.calls == []
    assert first_db.query_one("SELECT alert_id FROM notify_outbox WHERE alert_id=?",
                              (alert.id,)) is not None
    first_db.close()

    restarted_db = Database(path)
    restarted_transport = FakeTransport()
    try:
        restarted = build(restarted_db,
                          env={"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42"},
                          transport=restarted_transport, telegram_enabled=True,
                          min_interval_seconds=0)
        result = restarted.drain()
        assert result["sent"] == 1
        assert len(restarted_transport.calls) == 1
        persisted = restarted_db.query_one("SELECT payload FROM alerts WHERE id=?",
                                           (alert.id,))
        assert json.loads(persisted["payload"])["delivery_state"] == "completed"
        duplicate = restarted.emit(
            "warning", "Management modify: unknown", "ticket T-11", symbol="XAUUSD",
            dedupe_key="account-hash:T-11:sl-1995", dedupe_seconds=300)
        assert duplicate.meta["deduped"] is True
        assert len(restarted_transport.calls) == 1
    finally:
        restarted_db.close()


def test_keyed_alert_does_not_reserve_delivery_when_outbox_is_disabled(tmp_path):
    path = tmp_path / "disabled-outbox.sqlite3"
    first_db = Database(path)
    first_transport = FakeTransport()
    first = build(first_db, env={"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42"},
                  transport=first_transport, telegram_enabled=True,
                  outbox={"enabled": False}, min_interval_seconds=0)
    first.emit("warning", "Management modify: unknown", "ticket T-12",
               dedupe_key="account-hash:T-12:sl-1995", dedupe_seconds=300)
    assert len(first_transport.calls) == 1
    first_db.close()

    restarted_db = Database(path)
    restarted_transport = FakeTransport()
    try:
        restarted = build(restarted_db,
                          env={"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42"},
                          transport=restarted_transport, telegram_enabled=True,
                          outbox={"enabled": False}, min_interval_seconds=0)
        result = restarted.emit(
            "warning", "Management modify: unknown", "ticket T-12",
            dedupe_key="account-hash:T-12:sl-1995", dedupe_seconds=300)
        assert result.id.startswith("A")
        assert len(restarted_transport.calls) == 1
    finally:
        restarted_db.close()


def test_alert_dedupe_column_migrates_existing_rows_without_replacing_them(tmp_path):
    path = tmp_path / "legacy-alerts.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE workspace_identity(singleton INTEGER PRIMARY KEY, workspace_id TEXT)")
    connection.execute("INSERT INTO workspace_identity VALUES(1, 'local')")
    connection.execute("""CREATE TABLE alerts(
        id TEXT PRIMARY KEY, t INTEGER, level TEXT, title TEXT, message TEXT,
        channel TEXT, payload TEXT)""")
    connection.execute("INSERT INTO alerts VALUES('old',1,'info','old title','old message','inapp','{}')")
    connection.execute("""CREATE TABLE notify_outbox(
        id TEXT PRIMARY KEY, channel TEXT NOT NULL, title TEXT, message TEXT,
        level TEXT, symbol TEXT, created_at REAL NOT NULL, next_attempt_at REAL NOT NULL,
        attempts INTEGER DEFAULT 0, last_status INTEGER DEFAULT 0, last_error TEXT DEFAULT '')""")
    connection.execute("INSERT INTO notify_outbox(id,channel,title,message,created_at,next_attempt_at) "
                       "VALUES('legacy','telegram','old','message',1,1)")
    connection.commit()
    connection.close()

    migrated = Database(path)
    try:
        columns = {row["name"] for row in migrated.query("PRAGMA table_info(alerts)")}
        old_alert = migrated.query_one("SELECT * FROM alerts WHERE id='old'")
        index = migrated.query_one(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_alerts_dedupe'")
        outbox_columns = {row["name"] for row in migrated.query("PRAGMA table_info(notify_outbox)")}
        old_outbox = migrated.query_one("SELECT * FROM notify_outbox WHERE id='legacy'")
        outbox_index = migrated.query_one(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_notify_outbox_alert'")
        assert "dedupe_fingerprint" in columns
        assert old_alert["title"] == "old title"
        assert old_alert["dedupe_fingerprint"] is None
        assert index is not None
        assert "alert_id" in outbox_columns
        assert old_outbox["title"] == "old"
        assert old_outbox["alert_id"] is None
        assert outbox_index is not None
    finally:
        migrated.close()


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
