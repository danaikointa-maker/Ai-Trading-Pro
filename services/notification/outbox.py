"""Durable outbound queue for alerts that could not be delivered in-process.

`Notifier._send` retries for about a second and then gives up. That covers a
dropped packet; it does not cover the normal case — the receiver being restarted,
redeployed or briefly unreachable for a minute or two. Every alert raised in that
window was lost, including the ones that exist precisely because nobody is looking
at the dashboard ("daily loss limit hit", "cooldown engaged"). The in-app copy
survived, which is not the same thing as somebody being told.

Design decisions, each of which is a trade-off worth stating:

* **SQLite, not an in-memory list.** A queue that dies with the process cannot
  survive the restart that created the backlog. This is the whole point.
* **Title and message are stored — never the rendered request.** The payload is
  rebuilt at send time, so (a) no bot token or webhook URL is written to the
  database, and (b) correcting a wrong URL in config flushes the backlog to the
  *new* destination instead of retrying a known-bad one.
* **Bounded on three axes.** `max_attempts` stops a permanently broken endpoint
  from being retried until the heat death of the universe; `max_age_seconds` drops
  alerts too stale to act on (a 40-minute-old entry signal is not information, it
  is a liability); `capacity` keeps a long outage from filling the disk. Every drop
  is counted and surfaced in `status()` — a silent drop would be worse than no
  queue at all, because the operator would believe delivery is guaranteed.
* **Newest wins on overflow.** When the queue is full the *oldest* row is removed.
  In trading the freshest alert is the valuable one; dropping the new arrival to
  preserve a stale backlog gets the priority exactly backwards.
* **Attempts are recorded before the send, not after.** A process killed mid-POST
  must not come back and retry immediately forever; the row already carries its
  next backoff.

Delivery is therefore *at least once*, not exactly once: a POST that succeeded but
whose response was lost will be retried. Receivers get `X-No7-Delivery-Id` to
deduplicate on — see `signing.py`.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from packages.persistence.db import Database

# Conservative defaults: ~8 attempts spread over roughly half an hour, which
# comfortably covers a deploy or a service restart without hammering a dead host.
# The cap matters more than it looks. Doubling without a tight ceiling means that
# after a few minutes of downtime the *next* attempt is several minutes away, so a
# receiver that comes back at 10:00 does not hear anything until 10:05 — measured,
# not guessed (see scripts/check_outbox.py). A 60s ceiling bounds the recovery lag;
# coverage of a long outage comes from the attempt count, not from longer sleeps.
DEFAULT_MAX_ATTEMPTS = 20
DEFAULT_MAX_AGE_SECONDS = 1800.0
DEFAULT_BACKOFF_SECONDS = 5.0
DEFAULT_BACKOFF_CAP_SECONDS = 60.0
DEFAULT_CAPACITY = 500


def _int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


class OutboxQueue:
    """Persistent retry queue for one Notifier."""

    def __init__(self, db: Database, cfg: dict[str, Any] | None = None) -> None:
        cfg = cfg or {}
        self.db = db
        self.enabled = str(cfg.get("enabled", True)).strip().lower() not in (
            "0", "false", "no", "off")
        self.max_attempts = max(1, _int(cfg.get("max_attempts"), DEFAULT_MAX_ATTEMPTS))
        self.max_age_seconds = max(0.0, _float(cfg.get("max_age_seconds"),
                                               DEFAULT_MAX_AGE_SECONDS))
        self.backoff_seconds = max(0.0, _float(cfg.get("backoff_seconds"),
                                               DEFAULT_BACKOFF_SECONDS))
        self.backoff_cap_seconds = max(self.backoff_seconds,
                                       _float(cfg.get("backoff_cap_seconds"),
                                              DEFAULT_BACKOFF_CAP_SECONDS))
        self.capacity = max(1, _int(cfg.get("capacity"), DEFAULT_CAPACITY))

        # Lifetime counters (process-local; the rows themselves are the state).
        self.queued = 0
        self.delivered = 0
        self.expired = 0
        self.exhausted = 0
        self.overflowed = 0

    # --------------------------------------------------------------- internals
    def _delay_for(self, attempts: int) -> float:
        """Exponential backoff, capped. `attempts` is the count *after* this try."""
        if self.backoff_seconds <= 0:
            return 0.0
        delay = self.backoff_seconds * (2 ** max(0, attempts - 1))
        return min(delay, self.backoff_cap_seconds)

    def _enforce_capacity(self) -> None:
        extra = self.pending() - self.capacity + 1
        if extra <= 0:
            return
        rows = self.db.query(
            "SELECT id FROM notify_outbox ORDER BY created_at ASC LIMIT ?", (extra,))
        for row in rows:
            self.db.execute("DELETE FROM notify_outbox WHERE id=?", (row["id"],))
            self.overflowed += 1

    # ------------------------------------------------------------------ writing
    def enqueue(self, channel: str, title: str, message: str, *, level: str = "info",
                symbol: str | None = None, status: int = 0, error: str = "",
                attempts: int = 0, delay: float | None = None,
                now: float | None = None) -> str | None:
        """Store one undelivered message. Returns its delivery id, or None when off.

        `attempts` is how many delivery attempts this message has *already* had.
        A message that failed its inline send arrives here with 1, so the attempt
        counter a receiver sees (and `max_attempts`) counts every try, not only the
        queued ones. A message held back by pacing was never attempted: 0.

        `delay` overrides the first backoff. A message held back by pacing is not
        failing — it becomes due the moment its channel's interval expires, and
        making it wait the generic retry backoff on top of that would be arbitrary.
        """
        if not self.enabled:
            return None
        moment = time.time() if now is None else now
        wait = self._delay_for(1) if delay is None else max(0.0, float(delay))
        self._enforce_capacity()
        row_id = f"OB{uuid.uuid4().hex[:12]}"
        self.db.execute(
            "INSERT INTO notify_outbox(id, channel, title, message, level, symbol, "
            "created_at, next_attempt_at, attempts, last_status, last_error) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (row_id, channel, title, message, level, symbol or "",
             moment, moment + wait, max(0, int(attempts)), int(status or 0),
             str(error or "")[:400]),
        )
        self.queued += 1
        return row_id

    def mark_delivered(self, row_id: str) -> None:
        self.db.execute("DELETE FROM notify_outbox WHERE id=?", (row_id,))
        self.delivered += 1

    def discard(self, row_id: str, *, reason: str = "") -> None:
        """Give up on a row for a reason that is not a failed attempt.

        Counted as `expired` rather than `delivered`: the message never arrived,
        and a counter that says otherwise would be a lie told to an operator.
        """
        self.db.execute("DELETE FROM notify_outbox WHERE id=?", (row_id,))
        self.expired += 1

    def mark_attempt(self, row_id: str, *, status: int, error: str,
                     now: float | None = None) -> bool:
        """Record a failed attempt. Returns False when the row was given up on."""
        moment = time.time() if now is None else now
        row = self.db.query_one("SELECT attempts FROM notify_outbox WHERE id=?", (row_id,))
        if row is None:
            return False
        attempts = int(row["attempts"] or 0) + 1
        if attempts >= self.max_attempts:
            self.db.execute("DELETE FROM notify_outbox WHERE id=?", (row_id,))
            self.exhausted += 1
            return False
        self.db.execute(
            "UPDATE notify_outbox SET attempts=?, next_attempt_at=?, last_status=?, "
            "last_error=? WHERE id=?",
            (attempts, moment + self._delay_for(attempts + 1), int(status or 0),
             str(error or "")[:400], row_id),
        )
        return True

    def reschedule_channel(self, channel: str, now: float | None = None) -> int:
        """Make every queued message for one channel due immediately.

        Backoff is a guess about a destination that is probably still broken. The
        moment *anything* reaches that destination the guess is obsolete: the host
        is back, and making the backlog serve out sleeps that were scheduled while
        it was down just delays alerts for no reason. Returns how many were moved.
        """
        moment = time.time() if now is None else now
        rows = self.db.query(
            "SELECT id FROM notify_outbox WHERE channel=? AND next_attempt_at > ?",
            (channel, moment))
        if rows:
            self.db.execute(
                "UPDATE notify_outbox SET next_attempt_at=? WHERE channel=? "
                "AND next_attempt_at > ?", (moment, channel, moment))
        return len(rows)

    def sweep(self, now: float | None = None) -> int:
        """Drop rows too old to be worth delivering. Returns how many went."""
        if self.max_age_seconds <= 0:
            return 0
        moment = time.time() if now is None else now
        cutoff = moment - self.max_age_seconds
        rows = self.db.query("SELECT id FROM notify_outbox WHERE created_at < ?", (cutoff,))
        for row in rows:
            self.db.execute("DELETE FROM notify_outbox WHERE id=?", (row["id"],))
        self.expired += len(rows)
        return len(rows)

    # ------------------------------------------------------------------ reading
    def due(self, now: float | None = None, limit: int = 10) -> list[dict[str, Any]]:
        moment = time.time() if now is None else now
        rows = self.db.query(
            "SELECT * FROM notify_outbox WHERE next_attempt_at <= ? "
            "ORDER BY created_at ASC LIMIT ?", (moment, int(limit)))
        return [dict(row) for row in rows]

    def pending(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS n FROM notify_outbox")
        return int(row["n"]) if row else 0

    def oldest_age(self, now: float | None = None) -> float:
        row = self.db.query_one("SELECT MIN(created_at) AS t FROM notify_outbox")
        if not row or row["t"] is None:
            return 0.0
        moment = time.time() if now is None else now
        return max(0.0, moment - float(row["t"]))

    def status(self, now: float | None = None) -> dict[str, Any]:
        pending = self.pending()
        out: dict[str, Any] = {
            "enabled": self.enabled,
            "pending": pending,
            "oldest_seconds": round(self.oldest_age(now), 1) if pending else 0.0,
            "queued": self.queued,
            "delivered": self.delivered,
            "expired": self.expired,
            "exhausted": self.exhausted,
            "overflowed": self.overflowed,
            "max_attempts": self.max_attempts,
            "max_age_seconds": self.max_age_seconds,
            "capacity": self.capacity,
        }
        notes: list[str] = []
        if self.exhausted:
            notes.append(f"{self.exhausted} ข้อความถูกยกเลิกหลังพยายามครบ "
                         f"{self.max_attempts} ครั้ง — ปลายทางน่าจะเสียจริง")
        if self.expired:
            notes.append(f"{self.expired} ข้อความเก่าเกิน {self.max_age_seconds:g} วินาที "
                         f"จึงถูกทิ้ง (แจ้งช้าเกินกว่าจะมีประโยชน์)")
        if self.overflowed:
            notes.append(f"คิวเต็ม {self.capacity} — ทิ้งของเก่าที่สุด "
                         f"{self.overflowed} ข้อความเพื่อรับของใหม่")
        if notes:
            out["warning"] = " · ".join(notes)
        return out

    def clear(self) -> int:
        removed = self.pending()
        self.db.execute("DELETE FROM notify_outbox", ())
        return removed
