"""A stalled provider must not hold the trading thread."""
import threading

from packages.persistence.db import Database
from services.notification.notifier import Notifier


def test_background_delivery_persists_first_and_does_not_block(tmp_path):
    db = Database(str(tmp_path / "notify.sqlite3"))
    entered, release = threading.Event(), threading.Event()

    def slow(*_):
        entered.set()
        assert release.wait(5)
        return {"ok": True, "status": 200}

    notifier = Notifier(db, cfg={"telegram_enabled": True, "dedupe_seconds": 0},
                        env={"TELEGRAM_BOT_TOKEN": "secret", "TELEGRAM_CHAT_ID": "1"},
                        transport=slow, background=True, queue_size=1)
    try:
        first = notifier.emit("info", "one", "message")
        assert entered.wait(2)
        assert first.meta["delivery_state"] == "queued"
        assert db.query_one("SELECT id FROM alerts WHERE id=?", (first.id,))
        notifier.emit("info", "two", "message")
        third = notifier.emit("info", "three", "message")
        assert third.meta["delivery_state"] == "queue_full"
        assert notifier.status()["queue"]["dropped"] == 1
    finally:
        release.set()
        assert notifier.close(timeout=5)
    assert notifier.emit("info", "after close", "message").meta["delivery_state"] == "stopped"
    assert notifier.status()["queue"]["running"] is False
    db.close()


def test_background_success_updates_persisted_alert(tmp_path):
    db = Database(str(tmp_path / "notify.sqlite3"))
    notifier = Notifier(db, cfg={"telegram_enabled": True},
                        env={"TELEGRAM_BOT_TOKEN": "secret", "TELEGRAM_CHAT_ID": "1"},
                        transport=lambda *_: {"ok": True, "status": 200}, background=True)
    try:
        alert = notifier.emit("info", "title", "message")
        notifier._queue.join()
        row = next(r for r in notifier.recent() if r["id"] == alert.id)
        assert row["payload"]["delivery"][0]["ok"] is True
        assert row["payload"]["delivery_state"] == "completed"
    finally:
        assert notifier.close(timeout=5)
        db.close()


def test_shutdown_timeout_is_reported_and_test_send_is_refused(tmp_path):
    db = Database(str(tmp_path / "notify.sqlite3"))
    entered, release = threading.Event(), threading.Event()

    def slow(*_):
        entered.set()
        release.wait(5)
        return {"ok": True, "status": 200}

    notifier = Notifier(db, cfg={"telegram_enabled": True},
                        env={"TELEGRAM_BOT_TOKEN": "secret", "TELEGRAM_CHAT_ID": "1"},
                        transport=slow, background=True)
    try:
        notifier.emit("info", "title", "message")
        assert entered.wait(2)
        assert notifier.close(timeout=0) is False
        assert notifier.send_test()["ok"] is False
    finally:
        release.set()
        assert notifier.close(timeout=5)
        db.close()


def test_runtime_always_uses_background_delivery(runtime):
    assert runtime.notifier.background is True


def test_background_failure_keeps_metadata_for_durable_retry(tmp_path):
    db = Database(str(tmp_path / "notify.sqlite3"))
    notifier = Notifier(db, cfg={"webhook_url": "http://127.0.0.1/hook", "webhook_enabled": True,
                                "retry_attempts": 1, "min_interval_seconds": 0},
                        env={}, transport=lambda *_: {"ok": False, "status": 503},
                        background=True)
    try:
        notifier.emit("critical", "risk", "blocked", symbol="XAUUSD")
        notifier._queue.join()
        rows = db.query("SELECT * FROM notify_outbox")
        assert len(rows) == 1
        assert rows[0]["level"] == "critical"
        assert rows[0]["symbol"] == "XAUUSD"
    finally:
        assert notifier.close(5)
        db.close()


def test_close_waits_for_outbox_worker_and_refuses_new_drains(tmp_path):
    db = Database(str(tmp_path / "notify.sqlite3"))
    entered, release = threading.Event(), threading.Event()

    def slow(*_):
        entered.set()
        assert release.wait(5)
        return {"ok": True, "status": 200}

    notifier = Notifier(db, cfg={"telegram_enabled": True, "min_interval_seconds": 0},
                        env={"TELEGRAM_BOT_TOKEN": "secret", "TELEGRAM_CHAT_ID": "1"},
                        transport=slow, background=True)
    notifier.outbox.enqueue("telegram", "title", "message", delay=0)
    try:
        assert notifier.drain_async()
        assert entered.wait(2)
        assert notifier.close(0) is False
        assert notifier.drain_async() is False
    finally:
        release.set()
        assert notifier.close(5)
        assert notifier.outbox.pending() == 0
        db.close()