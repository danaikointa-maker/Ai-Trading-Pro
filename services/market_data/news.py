"""Economic-calendar / news lockout service.

The bundled schedule is a deterministic placeholder so the lockout logic can be
demonstrated offline. In production swap ``_seed_schedule`` for a real calendar
API — the rest of the risk engine consumes the same interface.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, asdict
from typing import Any

from packages.persistence.db import Database


@dataclass
class NewsEvent:
    id: str
    t: int
    currency: str
    impact: str          # high | medium | low
    title: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NewsService:
    def __init__(self, db: Database, high_impact_currencies: list[str] | None = None,
                 horizon_hours: int = 72, now: float | None = None, seed: int = 7) -> None:
        self.db = db
        self.currencies = high_impact_currencies or ["USD"]
        self.events: list[NewsEvent] = []
        self._now_ref = now or time.time()
        self._horizon = horizon_hours
        self._seed = seed
        self._load_or_seed()

    # ------------------------------------------------------------------ seed
    def _load_or_seed(self) -> None:
        rows = self.db.query("SELECT id, t, currency, impact, title FROM news WHERE t > ? ORDER BY t",
                             (int(self._now_ref) - 86400,))
        if rows:
            self.events = [NewsEvent(r["id"], int(r["t"]), r["currency"], r["impact"], r["title"]) for r in rows]
            return
        self._seed_schedule()
        self.db.executemany(
            "INSERT OR REPLACE INTO news(id, t, currency, impact, title) VALUES(?,?,?,?,?)",
            [(e.id, e.t, e.currency, e.impact, e.title) for e in self.events],
        )

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
            NewsEvent(f"n{i:02d}", base + minutes * 60, ccy, impact, title)
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
                extra.append(NewsEvent(f"n{uuid.uuid4().hex[:6]}", last + offset_h * 3600, ccy, impact, title))
            self.events.extend(extra)
            self.db.executemany(
                "INSERT OR REPLACE INTO news(id, t, currency, impact, title) VALUES(?,?,?,?,?)",
                [(e.id, e.t, e.currency, e.impact, e.title) for e in extra],
            )

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
                return {
                    "active": True,
                    "reason": f"{event.currency} high-impact event within window: {event.title}",
                    "event": event.to_dict(),
                    "minutes_to_event": round((event.t - now) / 60.0, 1),
                    "window": [window_start, window_end],
                }
        nxt = next((e for e in self.events if e.t > now and e.impact == "high" and e.currency in ccy), None)
        return {
            "active": False,
            "reason": "",
            "next_event": nxt.to_dict() if nxt else None,
            "minutes_to_event": round((nxt.t - now) / 60.0, 1) if nxt else None,
        }
