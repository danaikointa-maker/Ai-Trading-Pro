"""Economic-calendar / news lockout service.

The bundled schedule is a deterministic placeholder so the lockout logic can be
demonstrated offline. In production swap ``_seed_schedule`` for a real calendar
API — the rest of the risk engine consumes the same interface.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from packages.persistence.db import Database


@dataclass
class NewsEvent:
    id: str
    t: int
    currency: str
    impact: str          # high | medium | low
    title: str
    # True for the bundled demo schedule: it must never be mistaken for a real
    # economic calendar, but it still demonstrates the lockout logic.
    provisional: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _row_flag(row: Any, column: str) -> bool:
    """sqlite3.Row has no .get(); a missing column means the row predates it."""
    return bool(row[column]) if column in row.keys() else False


class NewsService:
    def __init__(self, db: Database, high_impact_currencies: list[str] | None = None,
                 horizon_hours: int = 72, now: float | None = None, seed: int = 7,
                 calendar_path: Path | None = None) -> None:
        self.db = db
        self.currencies = high_impact_currencies or ["USD"]
        self.events: list[NewsEvent] = []
        self._now_ref = now or time.time()
        self._horizon = horizon_hours
        self._seed = seed
        self.calendar_path = calendar_path
        self.source = "demo"
        self.skipped_events = 0
        self._load_or_seed()

    # ------------------------------------------------------------------ seed
    def _load_or_seed(self) -> None:
        self._ensure_columns()
        if self.calendar_path and self.calendar_path.exists():
            if self._load_calendar_file(self.calendar_path):
                return
        rows = self.db.query(
            "SELECT id, t, currency, impact, title, provisional FROM news WHERE t > ? ORDER BY t",
            (int(self._now_ref) - 86400,))
        if rows:
            self.events = [
                NewsEvent(r["id"], int(r["t"]), r["currency"], r["impact"], r["title"],
                          # older rows have no flag: the title still tells the truth
                          _row_flag(r, "provisional") or "(placeholder)" in str(r["title"]))
                for r in rows
            ]
            return
        self._seed_schedule()
        self._persist()

    def _ensure_columns(self) -> None:
        """Additive migration: older sqlite files predate `provisional`."""
        try:
            self.db.execute("ALTER TABLE news ADD COLUMN provisional INTEGER DEFAULT 0")
        except Exception:  # noqa: BLE001 - the column already exists
            pass

    def _persist(self) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO news(id, t, currency, impact, title, provisional) "
            "VALUES(?,?,?,?,?,?)",
            [(e.id, e.t, e.currency, e.impact, e.title, int(e.provisional)) for e in self.events],
        )

    def _load_calendar_file(self, path: Path) -> bool:
        """Load a real calendar (own export or scraper output) from JSON.

        Format: a list (or ``{"events": [...]}``) of
        ``{"t": <epoch seconds>, "currency": "USD", "impact": "high|medium|low", "title": "..."}``.
        Returns False when the file is unusable so the demo schedule is kept.
        """
        try:
            import json

            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - a broken file must not stop the app
            return False
        rows = raw.get("events") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            return False
        events: list[NewsEvent] = []
        skipped = 0
        for index, row in enumerate(rows):
            try:
                title = str(row["title"]).strip()
                event_t = int(row["t"])
                currency = str(row.get("currency", "USD")).upper()
                impact = str(row.get("impact", "high")).lower()
                if impact not in ("high", "medium", "low") or not title:
                    raise ValueError
            except Exception:  # noqa: BLE001
                skipped += 1
                continue
            events.append(NewsEvent(str(row.get("id") or f"f{index:04d}"), event_t, currency,
                                    impact, title, provisional=False))
        if not events:
            return False
        self.events = events
        self.source = str(path)
        self.skipped_events = skipped
        self.db.execute("DELETE FROM news")
        self._persist()
        return True

    def _seed_schedule(self) -> None:
        now = int(self._now_ref)
        # Anchor on the next 15-minute boundary so events look like a real calendar.
        base = now - (now % 900) + 900
        template = [
            (45, "USD", "high", "US CPI m/m (placeholder)"),
            (3 * 60, "USD", "medium", "Fed speaker — Waller (placeholder)"),
            (7 * 60, "USD", "high", "US Initial Jobless Claims (placeholder)"),
            (13 * 60, "EUR", "medium", "ECB Economic Bulletin (placeholder)"),
            (21 * 60, "USD", "high", "FOMC Rate Decision (placeholder)"),
            (30 * 60, "USD", "medium", "US PPI m/m (placeholder)"),
            (44 * 60, "USD", "high", "US NFP (placeholder)"),
            (60 * 60, "USD", "low", "Treasury auction (placeholder)"),
        ]
        self.events = [
            NewsEvent(f"n{i:02d}", base + minutes * 60, ccy, impact, title, provisional=True)
            for i, (minutes, ccy, impact, title) in enumerate(template)
        ]

    def refresh(self, now: float | None = None) -> None:
        now = now or time.time()
        if self.events and self.events[-1].t < now + 6 * 3600:
            extra = []
            last = max(e.t for e in self.events)
            for i, (offset_h, ccy, impact, title) in enumerate([
                (8, "USD", "high", "US ISM Manufacturing (placeholder)"),
                (20, "USD", "medium", "Fed Beige Book (placeholder)"),
                (32, "USD", "high", "US Core PCE (placeholder)"),
            ]):
                extra.append(NewsEvent(f"n{uuid.uuid4().hex[:6]}", last + offset_h * 3600, ccy, impact,
                                       title, provisional=True))
            self.events.extend(extra)
            self._persist()

    # ----------------------------------------------------------------- query
    def upcoming(self, now: float, hours: int = 24) -> list[dict[str, Any]]:
        end = now + hours * 3600
        rows = [e.to_dict() for e in self.events if now - 900 <= e.t <= end]
        rows.sort(key=lambda r: r["t"])
        for row in rows:
            row["minutes_until"] = round((row["t"] - now) / 60.0, 1)
        return rows

    def lockout(self, now: float, before_minutes: int = 30, after_minutes: int = 15,
                currencies: list[str] | None = None) -> dict[str, Any]:
        ccy = currencies or self.currencies
        for event in self.events:
            if event.impact != "high" or event.currency not in ccy:
                continue
            window_start = event.t - before_minutes * 60
            window_end = event.t + after_minutes * 60
            if window_start <= now <= window_end:
                suffix = (" — provisional demo calendar, NOT a real economic release"
                          if event.provisional else "")
                info = event.to_dict()
                return {
                    "active": True,
                    "provisional": event.provisional,
                    "reason": f"{event.currency} high-impact event within window: {event.title}{suffix}",
                    "event": info,
                    "next_event": info,
                    "minutes_to_event": round((event.t - now) / 60.0, 1),
                    "window": [window_start, window_end],
                }
        nxt = next((e for e in self.events if e.t > now and e.impact == "high" and e.currency in ccy), None)
        return {
            "active": False,
            "provisional": bool(nxt.provisional) if nxt else False,
            "reason": "",
            "next_event": nxt.to_dict() if nxt else None,
            "minutes_to_event": round((nxt.t - now) / 60.0, 1) if nxt else None,
        }
