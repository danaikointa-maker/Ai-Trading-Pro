"""Alert fan-out: in-app, Telegram, LINE, Web Push (pluggable)."""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from packages.persistence.db import Database
from packages.shared_schemas.models import Alert


class Notifier:
    def __init__(self, db: Database, min_score: float = 70.0) -> None:
        self.db = db
        self.min_score = min_score
        self._last: dict[str, float] = {}
        self.channels = ["inapp"]
        self.telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
        self.line_token = os.environ.get("LINE_CHANNEL_TOKEN", "")
        if self.telegram_token and self.telegram_chat:
            self.channels.append("telegram")
        if self.line_token:
            self.channels.append("line")

    def emit(self, level: str, title: str, message: str, symbol: str | None = None,
             meta: dict[str, Any] | None = None, dedupe_seconds: int = 60) -> Alert:
        key = f"{level}:{title}:{symbol}"
        now = time.time()
        if dedupe_seconds and now - self._last.get(key, 0) < dedupe_seconds:
            return Alert(id="deduped", t=int(now), level=level, title=title, message=message, symbol=symbol)  # type: ignore[arg-type]
        self._last[key] = now
        alert = Alert(
            id=f"A{uuid.uuid4().hex[:8]}",
            t=int(now),
            level=level,  # type: ignore[arg-type]
            title=title,
            message=message,
            channel="inapp",
            symbol=symbol,
            meta=meta or {},
        )
        self.db.execute(
            "INSERT OR REPLACE INTO alerts(id, t, level, title, message, channel, payload) VALUES(?,?,?,?,?,?,?)",
            (alert.id, alert.t, alert.level.value if hasattr(alert.level, "value") else alert.level,
             title, message, "inapp", json.dumps(meta or {}, default=str)),
        )
        for channel in self.channels:
            if channel == "inapp":
                continue
            try:
                self._send_external(channel, title, message)
            except Exception:  # noqa: BLE001 - alerts must never break trading
                continue
        return alert

    def _send_external(self, channel: str, title: str, message: str) -> None:
        import httpx

        text = f"[No7 AI] {title}\n{message}"
        if channel == "telegram":
            httpx.post(
                f"https://api.telegram.org/bot{self.telegram_token}/sendMessage",
                json={"chat_id": self.telegram_chat, "text": text}, timeout=5.0)
        elif channel == "line":
            httpx.post(
                "https://api.line.me/v2/bot/message/push",
                headers={"Authorization": f"Bearer {self.line_token}"},
                json={"to": os.environ.get("LINE_TARGET_ID", ""),
                      "messages": [{"type": "text", "text": text}]}, timeout=5.0)

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM alerts ORDER BY t DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]
