"""The durable outbox and the webhook signature.

Two things are being proven here, and they are related:

1. An alert that could not be delivered is *kept*, survives a process restart, and
   is retried with backoff until it lands or the queue gives up loudly.
2. Every webhook POST carries an HMAC a receiver can actually verify — including a
   POST that spent ten minutes in the queue, which is the case a naive
   implementation breaks (sign at enqueue time, arrive outside the replay window,
   get rejected forever).

The signature tests verify with `signing.verify()` over the *raw bytes* that
crossed the socket, which is what a real receiver has to do.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from packages.persistence.db import Database
from services.notification import signing
from services.notification.notifier import Notifier
from services.notification.outbox import OutboxQueue

SECRET = "whsec_test_8f2b1c"


# --------------------------------------------------------------------- harness
class Receiver:
    """A webhook endpoint that records raw bodies and can be scripted to fail."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.responses: list[tuple[int, dict]] = []
        self.down = False
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.port = self._server.server_address[1]
        self.thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/hook"

    def start(self) -> "Receiver":
        self.thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _handler(self):
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):  # noqa: N802 - http.server API
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)          # raw bytes: what gets verified
                receiver.requests.append({"raw": raw, "headers": dict(self.headers)})
                status, body = (receiver.responses.pop(0) if receiver.responses
                                else (200, {"ok": True}))
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                return

        return Handler


class FlakyTransport:
    """Records calls; returns scripted results so no socket is needed."""

    def __init__(self, *results: dict) -> None:
        self.results = list(results)
        self.calls: list[dict] = []

    def __call__(self, url, payload, headers):
        self.calls.append({"url": url, "payload": payload, "headers": headers})
        if self.results:
            return self.results.pop(0)
        return {"ok": True, "status": 200, "error": ""}


@pytest.fixture()
def receiver():
    server = Receiver().start()
    yield server
    server.stop()


@pytest.fixture()
def db(tmp_path):
    database = Database(str(tmp_path / "outbox.sqlite3"))
    yield database
    database.close()


def webhook_notifier(db, url: str, *, secret: str = SECRET, transport=None, **cfg) -> Notifier:
    base = {"channels": ["inapp", "webhook"], "webhook_enabled": True,
            "webhook_url": url, "webhook_secret": secret, "dedupe_seconds": 0,
            "min_interval_seconds": 0, "retry_backoff_seconds": 0, "retry_attempts": 1}
    base.update(cfg)
    return Notifier(db, min_score=70, cfg=base, env={}, transport=transport)


# ------------------------------------------------------------------- the queue
def test_an_undelivered_alert_is_kept_instead_of_lost(db):
    transport = FlakyTransport({"ok": False, "status": 503, "error": "HTTP 503"})
    n = webhook_notifier(db, "https://example.invalid/hook", transport=transport)
    alert = n.emit("critical", "Daily loss limit", "-3.1% วันนี้")
    assert alert.meta["delivery"][0]["ok"] is False
    assert alert.meta["delivery"][0]["queued"] is True
    assert n.outbox.pending() == 1


def test_a_permanent_rejection_is_not_queued(db):
    """A 401 will be a 401 tomorrow. Queueing it only builds a useless backlog."""
    transport = FlakyTransport({"ok": False, "status": 401, "error": "HTTP 401: bad token"})
    n = webhook_notifier(db, "https://example.invalid/hook", transport=transport)
    alert = n.emit("warning", "t", "m")
    assert "queued" not in alert.meta["delivery"][0]
    assert n.outbox.pending() == 0


def test_the_queue_survives_losing_the_process(db, tmp_path):
    """The whole point: the restart that caused the backlog must not erase it."""
    path = str(tmp_path / "restart.sqlite3")
    first = Database(path)
    transport = FlakyTransport({"ok": False, "status": 0, "error": "connection refused"})
    n = webhook_notifier(first, "https://example.invalid/hook", transport=transport)
    n.emit("critical", "Cooldown engaged", "3 ไม้ติดลบติดกัน")
    assert n.outbox.pending() == 1
    first.close()                                   # simulate the process dying

    second = Database(path)                         # same file, new process
    survived = OutboxQueue(second, {})
    assert survived.pending() == 1
    row = survived.due(now=time.time() + 3600)[0]
    assert row["title"] == "Cooldown engaged"
    assert row["channel"] == "webhook"
    second.close()


def test_the_queue_never_stores_the_destination_or_the_token(db):
    """Tokens and URLs must not end up at rest in the database."""
    transport = FlakyTransport({"ok": False, "status": 503, "error": "HTTP 503"})
    n = webhook_notifier(db, "https://hooks.example.invalid/s3cr3t-path",
                         secret="whsec_do_not_persist", transport=transport)
    n.emit("warning", "t", "m")
    dump = json.dumps([dict(r) for r in db.query("SELECT * FROM notify_outbox")])
    assert "s3cr3t-path" not in dump
    assert "whsec_do_not_persist" not in dump


def test_backoff_grows_and_the_row_is_not_retried_immediately(db):
    queue = OutboxQueue(db, {"backoff_seconds": 5, "backoff_cap_seconds": 60})
    now = 1_000_000.0
    row_id = queue.enqueue("webhook", "t", "m", now=now)
    assert queue.due(now=now) == [], "a fresh row is not due instantly"
    assert len(queue.due(now=now + 5)) == 1

    queue.mark_attempt(row_id, status=503, error="x", now=now + 5)
    assert queue.due(now=now + 6) == [], "the second attempt waits longer"
    assert len(queue.due(now=now + 5 + 10)) == 1


def test_the_queue_gives_up_loudly_after_max_attempts(db):
    queue = OutboxQueue(db, {"max_attempts": 3, "backoff_seconds": 0})
    row_id = queue.enqueue("webhook", "t", "m", now=0.0)
    assert queue.mark_attempt(row_id, status=503, error="x", now=0.0) is True
    assert queue.mark_attempt(row_id, status=503, error="x", now=0.0) is True
    assert queue.mark_attempt(row_id, status=503, error="x", now=0.0) is False
    assert queue.pending() == 0
    assert queue.exhausted == 1
    assert "ยกเลิก" in queue.status()["warning"]


def test_stale_alerts_are_dropped_and_counted(db):
    """A 40-minute-old entry signal is not information. Dropping it is correct —
    dropping it silently is not."""
    queue = OutboxQueue(db, {"max_age_seconds": 600})
    queue.enqueue("webhook", "old", "m", now=1_000_000.0)
    queue.enqueue("webhook", "new", "m", now=1_000_900.0)
    assert queue.sweep(now=1_000_901.0) == 1
    assert queue.pending() == 1
    assert queue.expired == 1
    assert "เก่าเกิน" in queue.status()["warning"]


def test_a_full_queue_drops_the_oldest_not_the_newest(db):
    queue = OutboxQueue(db, {"capacity": 3, "max_age_seconds": 0})
    for i in range(5):
        queue.enqueue("webhook", f"t{i}", "m", now=1_000_000.0 + i)
    assert queue.pending() == 3
    titles = [r["title"] for r in queue.due(now=1_000_999.0)]
    assert titles == ["t2", "t3", "t4"], "the freshest alerts are the ones kept"
    assert queue.overflowed == 2
    assert "คิวเต็ม" in queue.status()["warning"]


def test_a_disabled_outbox_changes_nothing(db):
    transport = FlakyTransport({"ok": False, "status": 503, "error": "HTTP 503"})
    n = webhook_notifier(db, "https://example.invalid/hook", transport=transport,
                         outbox={"enabled": False})
    alert = n.emit("warning", "t", "m")
    assert "queued" not in alert.meta["delivery"][0]
    assert n.outbox.pending() == 0
    assert n.status()["outbox"]["enabled"] is False


def test_a_message_for_a_switched_off_channel_is_discarded_not_delivered(db):
    queue_owner = webhook_notifier(db, "https://example.invalid/hook",
                                   transport=FlakyTransport({"ok": False, "status": 503,
                                                             "error": "HTTP 503"}))
    queue_owner.emit("warning", "t", "m")
    assert queue_owner.outbox.pending() == 1

    # operator turns the webhook off; the backlog must not be counted as delivered
    offline = webhook_notifier(db, "", secret="", transport=FlakyTransport())
    result = offline.drain(now=time.time() + 600)
    assert result["sent"] == 0
    assert offline.outbox.pending() == 0
    assert offline.outbox.delivered == 0
    assert offline.outbox.expired == 1


def test_drain_is_bounded_per_pass(db):
    n = webhook_notifier(db, "https://example.invalid/hook", transport=FlakyTransport())
    for i in range(7):
        n.outbox.enqueue("webhook", f"t{i}", "m", now=1_000_000.0)
    result = n.drain(now=1_000_100.0, limit=3)
    assert result["sent"] == 3
    assert result["pending"] == 4


# --------------------------------------------------------------- the signature
def test_a_webhook_without_a_secret_is_flagged_in_health(db):
    n = webhook_notifier(db, "https://example.invalid/hook", secret="",
                         transport=FlakyTransport())
    status = n.status()
    assert status["webhook_signed"] is False
    assert "NO7_WEBHOOK_SECRET" in status["webhook_warning"]


def test_a_signed_webhook_verifies_over_the_bytes_that_were_sent(db, receiver):
    n = webhook_notifier(db, receiver.url)
    n.emit("critical", "Daily loss limit", "ขาดทุนวันนี้ -3.1%", symbol="XAUUSD")
    assert len(receiver.requests) == 1
    sent = receiver.requests[0]

    ok, reason = signing.verify(SECRET, sent["headers"], sent["raw"])
    assert ok, reason
    # the body is real JSON and carries enough to route on without parsing prose
    body = json.loads(sent["raw"])
    assert body["title"] == "Daily loss limit"
    assert body["level"] == "critical"
    assert body["symbol"] == "XAUUSD"
    assert "ขาดทุน" in body["message"], "Thai text survives as UTF-8"


def test_a_tampered_body_fails_verification(db, receiver):
    n = webhook_notifier(db, receiver.url)
    n.emit("warning", "Spread สูง", "38 points", symbol="EURUSD")
    sent = receiver.requests[0]
    forged = sent["raw"].replace(b"38 points", b"99 points")
    assert len(forged) == len(sent["raw"])              # same length, different bytes
    ok, reason = signing.verify(SECRET, sent["headers"], forged)
    assert ok is False and reason == "signature mismatch"


def test_the_wrong_secret_fails_verification(db, receiver):
    n = webhook_notifier(db, receiver.url)
    n.emit("info", "t", "m")
    sent = receiver.requests[0]
    assert signing.verify("whsec_other", sent["headers"], sent["raw"])[0] is False


def test_an_old_capture_is_rejected_as_a_replay(db, receiver):
    n = webhook_notifier(db, receiver.url)
    n.emit("info", "t", "m")
    sent = receiver.requests[0]
    ok, reason = signing.verify(SECRET, sent["headers"], sent["raw"],
                                now=time.time() + 3600)
    assert ok is False and "replay" in reason


def test_verification_requires_both_headers(db, receiver):
    n = webhook_notifier(db, receiver.url)
    n.emit("info", "t", "m")
    sent = receiver.requests[0]
    without_sig = {k: v for k, v in sent["headers"].items()
                   if k.lower() != signing.SIGNATURE_HEADER.lower()}
    assert signing.verify(SECRET, without_sig, sent["raw"])[1].endswith("Signature")
    without_ts = {k: v for k, v in sent["headers"].items()
                  if k.lower() != signing.TIMESTAMP_HEADER.lower()}
    assert signing.verify(SECRET, without_ts, sent["raw"])[1].endswith("Timestamp")


def test_an_unconfigured_secret_means_no_headers_and_no_false_sense_of_safety(db, receiver):
    n = webhook_notifier(db, receiver.url, secret="")
    n.emit("info", "t", "m")
    headers = receiver.requests[0]["headers"]
    assert signing.SIGNATURE_HEADER not in headers
    assert signing.verify("", headers, b"{}") == (False, "no secret configured")


# ------------------------------------------- the two features, working together
def test_a_delayed_delivery_is_signed_fresh_and_still_verifies(db, receiver):
    """The bug this design avoids: signing at enqueue time.

    A message that waited in the queue would arrive with a stale timestamp and be
    refused as a replay by any receiver that checks — forever, on every retry.
    """
    receiver.responses.append((503, {"error": "deploying"}))
    n = webhook_notifier(db, receiver.url)
    n.emit("critical", "Cooldown engaged", "3 ไม้ติดลบติดกัน")
    assert n.outbox.pending() == 1, "the 503 must have been queued"
    assert len(receiver.requests) == 1

    # ten minutes later the receiver is back
    later = time.time() + 600
    result = n.drain(now=later)
    assert result["sent"] == 1 and n.outbox.pending() == 0
    assert len(receiver.requests) == 2

    delayed = receiver.requests[1]
    ok, reason = signing.verify(SECRET, delayed["headers"], delayed["raw"],
                                now=time.time())
    assert ok, f"a delayed delivery must verify against the current clock: {reason}"
    # and the receiver can still see that it was delayed, and dedupe on the id
    assert int(delayed["headers"][signing.QUEUED_HEADER]) <= int(time.time())
    assert delayed["headers"][signing.DELIVERY_HEADER].startswith("OB")
    assert delayed["headers"][signing.ATTEMPT_HEADER] == "2"
    # the body still reports when the alert happened, not when it was delivered
    assert json.loads(delayed["raw"])["ts"] <= int(time.time())


def test_a_retry_keeps_the_same_delivery_id_so_a_receiver_can_deduplicate(db, receiver):
    """Delivery is at-least-once; the id is what makes that safe for the receiver."""
    receiver.responses.extend([(503, {}), (503, {})])
    n = webhook_notifier(db, receiver.url, outbox={"backoff_seconds": 1})
    n.emit("warning", "t", "m")
    base = time.time()
    n.drain(now=base + 10)
    n.drain(now=base + 100)
    ids = [r["headers"].get(signing.DELIVERY_HEADER) for r in receiver.requests[1:]]
    assert len(ids) == 2
    assert ids[0] == ids[1] and ids[0].startswith("OB")


def test_health_reports_the_backlog(db):
    transport = FlakyTransport({"ok": False, "status": 503, "error": "HTTP 503"})
    n = webhook_notifier(db, "https://example.invalid/hook", transport=transport)
    n.emit("warning", "t", "m")
    outbox = n.status()["outbox"]
    assert outbox["enabled"] is True
    assert outbox["pending"] == 1
    assert outbox["queued"] == 1
    assert outbox["delivered"] == 0
    assert n.status()["webhook_signed"] is True


def test_drain_async_does_not_start_two_drains_at_once(db):
    n = webhook_notifier(db, "https://example.invalid/hook", transport=FlakyTransport())
    n.outbox.enqueue("webhook", "t", "m", now=0.0)
    started = n.drain_async()
    assert started is True
    for _ in range(100):                              # let the worker finish
        if not n._draining:
            break
        time.sleep(0.02)
    assert n.outbox.pending() == 0


def test_reschedule_makes_a_backlog_due_immediately(db):
    """The mechanism, with no threads involved."""
    queue = OutboxQueue(db, {"backoff_seconds": 300})
    at = 1_000_000.0
    queue.enqueue("webhook", "a", "m", now=at)
    queue.enqueue("webhook", "b", "m", now=at)
    queue.enqueue("telegram", "c", "m", now=at)
    assert queue.due(now=at + 1) == [], "everything is serving a 300s backoff"

    moved = queue.reschedule_channel("webhook", now=at + 1)
    assert moved == 2, "only the recovered channel is moved"
    assert [r["title"] for r in queue.due(now=at + 1)] == ["a", "b"]


def test_a_recovered_destination_flushes_the_whole_backlog_at_once(db):
    """Backoff is a guess about a dead host. One success proves the guess wrong.

    Without this, a receiver that comes back finds its backlog trickling out over
    the next several minutes, because every queued message is still serving a sleep
    that was scheduled while the host was down. Measured on the real thing first:
    see scripts/check_outbox.py.
    """
    transport = FlakyTransport(*[{"ok": False, "status": 503, "error": "HTTP 503"}] * 3)
    n = webhook_notifier(db, "https://example.invalid/hook", transport=transport)
    for i in range(3):
        n.emit("warning", f"t{i}", "m")
    assert n.outbox.pending() == 3
    assert n.outbox.due(now=time.time() + 1) == [], "all three are waiting out a backoff"

    # the fourth alert gets through: the destination is demonstrably back, so the
    # backlog must go now rather than when its stale backoff happens to expire
    n.emit("info", "recovered", "m")
    for _ in range(250):
        if n.outbox.pending() == 0:
            break
        time.sleep(0.02)
    assert n.outbox.pending() == 0, "the backlog flushed as soon as the host answered"
    assert n.outbox.delivered == 3


def test_one_queued_success_also_flushes_the_rest(db):
    queue_owner = webhook_notifier(
        db, "https://example.invalid/hook",
        transport=FlakyTransport(*[{"ok": False, "status": 503, "error": "x"}] * 3))
    for i in range(3):
        queue_owner.emit("warning", f"t{i}", "m")
    assert queue_owner.outbox.pending() == 3

    live = webhook_notifier(db, "https://example.invalid/hook", transport=FlakyTransport())
    base = time.time() + 10
    # only the first row is due; delivering it must pull the other two forward
    result = live.drain(now=base, limit=1)
    assert result["sent"] == 1
    assert len(live.outbox.due(now=base)) == 2


def test_a_real_time_drain_spaces_messages_instead_of_giving_up_on_them(db):
    """Pacing inside a drain must delay a message, not postpone it a whole cycle.

    With `paced -> skip`, a backlog left the queue at one message per loop tick
    (15 seconds). The drain runs on its own thread, so it can simply wait out the
    channel's interval and clear the backlog at provider-safe speed.
    """
    n = webhook_notifier(db, "https://example.invalid/hook", transport=FlakyTransport(),
                         min_interval_seconds=0.05)
    for i in range(3):
        n.outbox.enqueue("webhook", f"t{i}", "m", delay=0, now=time.time())
    started = time.monotonic()
    result = n.drain()                      # real clock: sleeping is allowed
    elapsed = time.monotonic() - started
    assert result["sent"] == 3, "all three left in one pass"
    assert result["paced"] == 0
    assert elapsed >= 0.05, "they were spaced, not fired as a burst"


def test_a_simulated_drain_never_sleeps(db):
    n = webhook_notifier(db, "https://example.invalid/hook", transport=FlakyTransport(),
                         min_interval_seconds=30)
    for i in range(2):
        n.outbox.enqueue("webhook", f"t{i}", "m", delay=0, now=999.0)
    started = time.monotonic()
    result = n.drain(now=1_000.0)
    assert time.monotonic() - started < 1.0, "a clock-overriding caller must not block"
    assert result["sent"] + result["paced"] == 2
