"""Alert fan-out: in-app (always), plus opt-in Telegram / LINE / generic webhook.

Design rules, learned the hard way:

* **In-app never fails.** Alerts are written to the database and pushed to the UI;
  an outbound channel is an extra, never a precondition.
* **A configured channel that cannot deliver must be visible.** The previous
  version called `httpx`, which is not a dependency of this project: every
  Telegram/LINE send raised `ModuleNotFoundError` inside a bare `except` and the
  operator was told nothing while messages silently never arrived. Every attempt
  now reports `{channel, ok, status, error}`, the result is stored with the alert
  and aggregated in `status()`, which `/api/system/health` and the System page read.
* **No network unless asked.** Channels come from `alerts:` config + env, off by
  default; tokens are read from env only and never echoed in status output.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable

from packages.persistence.db import Database
from packages.shared_schemas.models import Alert

STATUS_KEY = "notify_status"

# (url, payload, headers) -> {"ok": bool, "status": int, "error": str}
Transport = Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]


def _http_post_json(url: str, payload: dict[str, Any],
                    headers: dict[str, str]) -> dict[str, Any]:
    """POST JSON with the stdlib (no third-party dependency to forget)."""
    body = json.dumps(payload, default=str).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:  # noqa: S310 - https only
            text = resp.read(400).decode("utf-8", "replace")
            return {"ok": 200 <= getattr(resp, "status", 200) < 300,
                    "status": int(getattr(resp, "status", 200)), "error": "",
                    "body": text}
    except urllib.error.HTTPError as exc:  # non-2xx carries a useful body
        detail = ""
        try:
            detail = exc.read(400).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - diagnostics only
            pass
        return {"ok": False, "status": int(exc.code),
                "error": f"HTTP {exc.code}: {detail or exc.reason}"}
    except Exception as exc:  # noqa: BLE001 - network is allowed to break
        return {"ok": False, "status": 0, "error": f"{type(exc).__name__}: {exc}"}


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _text(value: Any) -> str:
    """Config values arrive typed: a Telegram chat id like -1001... is an int in
    YAML, not a string. Everything that leaves here must be a stripped string."""
    if value is None:
        return ""
    return str(value).strip()


class Notifier:
    def __init__(self, db: Database, min_score: float = 70.0,
                 cfg: dict[str, Any] | None = None,
                 transport: Transport | None = None,
                 env: dict[str, str] | None = None) -> None:
        self.db = db
        self.min_score = min_score
        self.cfg = cfg or {}
        self.env = os.environ if env is None else env
        self.transport: Transport = transport or _http_post_json
        self.timeout = float(self.cfg.get("timeout_seconds", 5) or 5)
        self.dedupe_seconds = int(self.cfg.get("dedupe_seconds", 60) or 0)
        self._last: dict[str, float] = {}
        self.channels = self._configured_channels()
        self.last_delivery: list[dict[str, Any]] = []

    # ------------------------------------------------------------ configuration
    def _configured_channels(self) -> list[str]:
        """Which channels will actually be attempted, and why.

        A channel needs both an explicit enable (config or env) *and* a token;
        having a token alone is not consent to send messages off this machine.
        """
        cfg = self.cfg
        channels = ["inapp"]
        telegram_token = self.env.get("TELEGRAM_BOT_TOKEN", "").strip()
        telegram_chat = _text(cfg.get("telegram_chat_id")
                              or self.env.get("TELEGRAM_CHAT_ID", ""))
        if telegram_token and telegram_chat and (
                _truthy(cfg.get("telegram_enabled")) or "telegram" in (cfg.get("channels") or [])
                or _truthy(self.env.get("NO7_TELEGRAM_ENABLED", ""))):
            channels.append("telegram")

        line_token = self.env.get("LINE_CHANNEL_TOKEN", "").strip()
        line_target = _text(cfg.get("line_target_id")
                            or self.env.get("LINE_TARGET_ID", ""))
        if line_token and line_target and (
                _truthy(cfg.get("line_enabled")) or "line" in (cfg.get("channels") or [])
                or _truthy(self.env.get("NO7_LINE_ENABLED", ""))):
            channels.append("line")

        webhook = _text(cfg.get("webhook_url") or self.env.get("NO7_WEBHOOK_URL", ""))
        if webhook and (_truthy(cfg.get("webhook_enabled")) or "webhook" in (cfg.get("channels") or [])
                        or _truthy(self.env.get("NO7_WEBHOOK_ENABLED", ""))):
            channels.append("webhook")
        return channels

    @property
    def external_channels(self) -> list[str]:
        return [c for c in self.channels if c != "inapp"]

    def status(self) -> dict[str, Any]:
        """Channel health for `/api/system/health` — no tokens, ever."""
        persisted = self.db.kv_get(STATUS_KEY, {}) or {}
        channels: dict[str, Any] = {
            "inapp": {"configured": True, "ok": True, "error": "", "last_attempt": None},
        }
        for name in ("telegram", "line", "webhook"):
            record = persisted.get(name, {}) if isinstance(persisted, dict) else {}
            channels[name] = {
                "configured": name in self.channels,
                "ok": record.get("ok"),
                "error": record.get("error", ""),
                "last_attempt": record.get("at"),
                "failures": int(record.get("failures", 0) or 0),
            }
        failing = [n for n, c in channels.items() if c["configured"] and c["ok"] is False]
        state = "failing" if failing else ("external" if self.external_channels else "inapp-only")
        return {
            "state": state,
            "channels": channels,
            "failing": failing,
            "min_score": self.min_score,
            "dedupe_seconds": self.dedupe_seconds,
            "disabled_reason": "" if self.external_channels else (
                "ไม่มีช่องทางภายนอกที่เปิดใช้ — in-app เท่านั้น "
                "(ต้องมี token + เปิดใช้ใน config หรือ env: TELEGRAM_BOT_TOKEN + chat id, "
                "LINE_CHANNEL_TOKEN + target id, หรือ NO7_WEBHOOK_URL)"),
        }

    # ------------------------------------------------------------------ sending
    def _payload(self, channel: str, title: str, message: str) -> tuple[str, dict, dict]:
        text = f"[No7 AI] {title}\n{message}"
        cfg = self.cfg
        if channel == "telegram":
            chat = _text(cfg.get("telegram_chat_id") or self.env.get("TELEGRAM_CHAT_ID", ""))
            token = self.env.get("TELEGRAM_BOT_TOKEN", "").strip()
            return (f"https://api.telegram.org/bot{token}/sendMessage",
                    {"chat_id": chat, "text": text, "disable_web_page_preview": True}, {})
        if channel == "line":
            target = _text(cfg.get("line_target_id") or self.env.get("LINE_TARGET_ID", ""))
            token = self.env.get("LINE_CHANNEL_TOKEN", "").strip()
            return ("https://api.line.me/v2/bot/message/push",
                    {"to": target, "messages": [{"type": "text", "text": text}]},
                    {"Authorization": f"Bearer {token}"})
        url = _text(cfg.get("webhook_url") or self.env.get("NO7_WEBHOOK_URL", ""))
        return (url, {"title": title, "message": message, "source": "no7-ai-trading-pro"}, {})

    def _send(self, channel: str, title: str, message: str) -> dict[str, Any]:
        try:
            url, payload, headers = self._payload(channel, title, message)
            if not url:
                return {"channel": channel, "ok": False, "status": 0,
                        "error": "no destination configured"}
            result = self.transport(url, payload, headers)
            return {"channel": channel, "ok": bool(result.get("ok")),
                    "status": int(result.get("status") or 0),
                    "error": str(result.get("error") or "")}
        except Exception as exc:  # noqa: BLE001 - a channel must never break an alert
            return {"channel": channel, "ok": False, "status": 0,
                    "error": f"{type(exc).__name__}: {exc}"}

    def _record_status(self, deliveries: list[dict[str, Any]]) -> None:
        if not deliveries:
            return
        persisted = self.db.kv_get(STATUS_KEY, {}) or {}
        if not isinstance(persisted, dict):
            persisted = {}
        now = time.time()
        for item in deliveries:
            channel = item["channel"]
            prev = persisted.get(channel, {})
            failures = int(prev.get("failures", 0) or 0)
            persisted[channel] = {
                "ok": item["ok"],
                "status": item["status"],
                "error": item["error"],
                "at": now,
                "failures": failures + (0 if item["ok"] else 1),
            }
        self.db.kv_set(STATUS_KEY, persisted)

    # -------------------------------------------------------------------- public
    def emit(self, level: str, title: str, message: str, symbol: str | None = None,
             meta: dict[str, Any] | None = None, dedupe_seconds: int | None = None) -> Alert:
        key = f"{level}:{title}:{symbol}"
        now = time.time()
        window = self.dedupe_seconds if dedupe_seconds is None else dedupe_seconds
        if window and now - self._last.get(key, 0) < window:
            return Alert(id=f"D{int(now)}", t=int(now), level=level, title=title,
                         message=message, channel="deduped", symbol=symbol,
                         meta={**(meta or {}), "deduped": True})  # type: ignore[arg-type]

        self._last[key] = now
        deliveries = [self._send(ch, title, message) for ch in self.external_channels]
        self.last_delivery = deliveries
        self._record_status(deliveries)

        payload = {**(meta or {})}
        if deliveries:
            payload["delivery"] = deliveries
        alert = Alert(
            id=f"A{uuid.uuid4().hex[:8]}",
            t=int(now),
            level=level,  # type: ignore[arg-type]
            title=title,
            message=message,
            channel=",".join(self.channels),
            symbol=symbol,
            meta=payload,
        )
        self.db.execute(
            "INSERT OR REPLACE INTO alerts(id, t, level, title, message, channel, payload) "
            "VALUES(?,?,?,?,?,?,?)",
            (alert.id, alert.t, alert.level.value if hasattr(alert.level, "value") else alert.level,
             title, message, alert.channel, json.dumps(payload, default=str)),
        )
        return alert

    def send_test(self) -> dict[str, Any]:
        """Prove the configured channels work, from the UI, with the real transport."""
        if not self.external_channels:
            return {"ok": False, "deliveries": [], "reason":
                    "ยังไม่มีช่องทางภายนอกที่เปิดใช้ — in-app ใช้ได้เสมอ แต่ต้องตั้ง token "
                    "และเปิดใช้ก่อนจึงจะทดสอบการส่งออกได้"}
        deliveries = [self._send(ch, "ทดสอบการแจ้งเตือน",
                                 "ถ้าคุณเห็นข้อความนี้ ช่องทางนี้ใช้งานได้")
                      for ch in self.external_channels]
        self._record_status(deliveries)
        return {"ok": all(d["ok"] for d in deliveries), "deliveries": deliveries}

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM alerts ORDER BY t DESC LIMIT ?", (limit,))
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            raw = item.get("payload")
            if isinstance(raw, str):
                try:
                    item["payload"] = json.loads(raw)
                except json.JSONDecodeError:
                    item["payload"] = {}
            out.append(item)
        return out
