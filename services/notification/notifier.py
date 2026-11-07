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
* **A blip is not a lost alert, a storm is not a flood.** Transient failures (network,
  429, 5xx) are retried a bounded number of times with backoff, honouring
  `Retry-After`; a channel that would exceed its minimum interval is *skipped on
  purpose* and counted, so an alert storm cannot get the bot banned by Telegram.
* **Tokens never leak through errors.** The Telegram token is part of the URL, so an
  exception message can contain it and `status()` is served to any logged-in user:
  every string that leaves this module is scrubbed of the configured secrets.
* **The API base is configurable.** `NO7_TELEGRAM_API_BASE` / `NO7_LINE_API_BASE`
  exist so the transport can be pointed at a local server that speaks the same
  protocol (which is how the delivery path is tested here); a non-HTTPS base is only
  accepted for loopback/private hosts, because plaintext would expose the token.
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

TELEGRAM_API = "https://api.telegram.org"
LINE_API = "https://api.line.me"

# Message limits from the providers; exceeding them is a hard 400, not a truncation.
MAX_LEN = {"telegram": 4096, "line": 5000, "webhook": 8000}

# Statuses worth another attempt: a dropped connection, a timeout, a busy or broken
# server. Everything else (bad token, bad chat id, blocked bot) will fail again.
RETRYABLE = {0, 408, 425, 429, 500, 502, 503, 504}

PRIVATE_HOST_HINTS = ("localhost", "127.0.0.1", "::1", "0.0.0.0")

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
                    "body": text, "retry_after": _retry_after(resp.headers)}
    except urllib.error.HTTPError as exc:  # non-2xx carries a useful body
        detail = ""
        try:
            detail = exc.read(400).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - diagnostics only
            pass
        return {"ok": False, "status": int(exc.code),
                "error": f"HTTP {exc.code}: {detail or exc.reason}",
                "retry_after": _retry_after(getattr(exc, "headers", None))}
    except Exception as exc:  # noqa: BLE001 - network is allowed to break
        return {"ok": False, "status": 0, "error": f"{type(exc).__name__}: {exc}"}


def _retry_after(headers: Any) -> float | None:
    """`Retry-After` in seconds, when the server bothered to say. Capped by the caller."""
    if not headers:
        return None
    try:
        raw = headers.get("Retry-After") or headers.get("retry-after")
        return float(str(raw).strip()) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _is_private_host(host: str) -> bool:
    """Loopback / RFC1918 / *.local — where plaintext HTTP cannot leave the box."""
    host = (host or "").strip().lower().strip("[]")
    if not host or host in PRIVATE_HOST_HINTS or host.endswith(".local"):
        return True
    if host.startswith(("10.", "192.168.", "169.254.")):
        return True
    if host.startswith("172."):
        try:
            return 16 <= int(host.split(".")[1]) <= 31
        except (IndexError, ValueError):
            return False
    return False


def safe_base(raw: str, fallback: str) -> tuple[str, str]:
    """Validate an API base URL. Returns (url, warning) — never raises.

    A test/local server speaking the provider protocol is a legitimate use of the
    override, but plain HTTP ships the bot token in clear text, so it is only allowed
    to a private host. Anything else suspicious falls back to the real endpoint and
    says why, rather than quietly sending credentials somewhere odd.
    """
    text = (raw or "").strip().rstrip("/")
    if not text:
        return fallback, ""
    if not text.startswith(("http://", "https://")):
        return fallback, f"ignored API base {text!r}: needs http(s)"
    scheme, _, rest = text.partition("://")
    host = rest.split("/")[0].split(":")[0]
    if scheme == "http" and not _is_private_host(host):
        return fallback, (f"ignored http API base for non-private host {host!r}: "
                          f"plaintext would expose the token")
    return text, ""


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
        self.attempts = max(1, int(self.cfg.get("retry_attempts", 3) or 1))
        self.backoff = max(0.0, float(self.cfg.get("retry_backoff_seconds", 0.5) or 0))
        self.min_interval = max(0.0, float(self.cfg.get("min_interval_seconds", 1.0) or 0))
        self._last: dict[str, float] = {}
        self._last_send: dict[str, float] = {}
        self.channels = self._configured_channels()
        self.last_delivery: list[dict[str, Any]] = []
        self.retries = 0          # extra attempts spent on transient failures
        self.dropped = 0          # messages deliberately skipped (pacing)
        # Every string that leaves this module gets scrubbed of these.
        self._secrets = [v for v in (
            self.env.get("TELEGRAM_BOT_TOKEN", "").strip(),
            self.env.get("LINE_CHANNEL_TOKEN", "").strip(),
            _text(self.cfg.get("webhook_secret") or self.env.get("NO7_WEBHOOK_SECRET", "")),
        ) if v]
        self.bases: dict[str, str] = {}
        self.base_warnings: list[str] = []
        for channel, raw, fallback in (
                ("telegram", self.cfg.get("telegram_api_base")
                 or self.env.get("NO7_TELEGRAM_API_BASE", ""), TELEGRAM_API),
                ("line", self.cfg.get("line_api_base")
                 or self.env.get("NO7_LINE_API_BASE", ""), LINE_API)):
            url, warning = safe_base(str(raw or ""), fallback)
            self.bases[channel] = url
            if warning:
                self.base_warnings.append(warning)

    # ------------------------------------------------------------ configuration
    def _redact(self, text: Any) -> str:
        """Remove configured secrets from anything we store, log or return."""
        out = str(text or "")
        for secret in self._secrets:
            if secret and secret in out:
                out = out.replace(secret, "***")
        return out
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
            "inapp": {"configured": True, "ok": True, "error": "", "last_attempt": None,
                      "skipped": 0, "base": ""},
        }
        for name in ("telegram", "line", "webhook"):
            record = persisted.get(name, {}) if isinstance(persisted, dict) else {}
            channels[name] = {
                "configured": name in self.channels,
                "ok": record.get("ok"),
                "error": self._redact(record.get("error", "")),
                "last_attempt": record.get("at"),
                "failures": int(record.get("failures", 0) or 0),
                "skipped": int(record.get("skipped", 0) or 0),
                "base": self.bases.get(name, ""),
            }
        failing = [n for n, c in channels.items() if c["configured"] and c["ok"] is False]
        state = "failing" if failing else ("external" if self.external_channels else "inapp-only")
        return {
            "state": state,
            "channels": channels,
            "failing": failing,
            "min_score": self.min_score,
            "dedupe_seconds": self.dedupe_seconds,
            "retry_attempts": self.attempts,
            "retries": self.retries,
            "dropped": self.dropped,
            "min_interval_seconds": self.min_interval,
            "base_warnings": list(self.base_warnings),
            "disabled_reason": "" if self.external_channels else (
                "ไม่มีช่องทางภายนอกที่เปิดใช้ — in-app เท่านั้น "
                "(ต้องมี token + เปิดใช้ใน config หรือ env: TELEGRAM_BOT_TOKEN + chat id, "
                "LINE_CHANNEL_TOKEN + target id, หรือ NO7_WEBHOOK_URL)"),
        }

    # ------------------------------------------------------------------ sending
    def _fit(self, channel: str, text: str) -> str:
        """Providers reject over-long messages with a 400; truncation at least delivers."""
        limit = MAX_LEN.get(channel, 4096)
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def _payload(self, channel: str, title: str, message: str) -> tuple[str, dict, dict]:
        text = self._fit(channel, f"[No7 AI] {title}\n{message}")
        cfg = self.cfg
        if channel == "telegram":
            chat = _text(cfg.get("telegram_chat_id") or self.env.get("TELEGRAM_CHAT_ID", ""))
            token = self.env.get("TELEGRAM_BOT_TOKEN", "").strip()
            base = self.bases.get("telegram", TELEGRAM_API)
            return (f"{base}/bot{token}/sendMessage",
                    {"chat_id": chat, "text": text, "disable_web_page_preview": True}, {})
        if channel == "line":
            target = _text(cfg.get("line_target_id") or self.env.get("LINE_TARGET_ID", ""))
            token = self.env.get("LINE_CHANNEL_TOKEN", "").strip()
            base = self.bases.get("line", LINE_API)
            return (f"{base}/v2/bot/message/push",
                    {"to": target, "messages": [{"type": "text", "text": text}]},
                    {"Authorization": f"Bearer {token}"})
        url = _text(cfg.get("webhook_url") or self.env.get("NO7_WEBHOOK_URL", ""))
        return (url, {"title": title, "message": self._fit(channel, message),
                      "source": "no7-ai-trading-pro"}, {})

    def _paced(self, channel: str) -> bool:
        """False when this channel was used too recently — dropped on purpose.

        Telegram answers a burst with 429 and can mute the bot; a skipped message that
        is counted beats a channel that stops working. The in-app alert still lands.
        """
        if self.min_interval <= 0:
            return True
        now = time.monotonic()
        last = self._last_send.get(channel)
        if last is not None and now - last < self.min_interval:
            return False
        self._last_send[channel] = now
        return True

    def _send(self, channel: str, title: str, message: str) -> dict[str, Any]:
        try:
            url, payload, headers = self._payload(channel, title, message)
            if not url:
                return {"channel": channel, "ok": False, "status": 0,
                        "error": "no destination configured"}
            if not self._paced(channel):
                self.dropped += 1
                return {"channel": channel, "ok": None, "status": 0, "skipped": "pacing",
                        "error": f"skipped: {channel} used less than "
                                 f"{self.min_interval:g}s ago"}
            result: dict[str, Any] = {}
            for attempt in range(1, self.attempts + 1):
                result = self.transport(url, payload, headers)
                status = int(result.get("status") or 0)
                if result.get("ok") or status not in RETRYABLE or attempt == self.attempts:
                    break
                self.retries += 1
                delay = result.get("retry_after")
                delay = min(float(delay), 30.0) if delay else self.backoff * attempt
                if delay > 0:
                    time.sleep(delay)
            return {"channel": channel, "ok": bool(result.get("ok")),
                    "status": int(result.get("status") or 0),
                    "error": self._redact(result.get("error") or ""),
                    "attempts": attempt}
        except Exception as exc:  # noqa: BLE001 - a channel must never break an alert
            return {"channel": channel, "ok": False, "status": 0,
                    "error": self._redact(f"{type(exc).__name__}: {exc}")}

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
            skipped = item.get("ok") is None
            persisted[channel] = {
                # A skip is not a failure and not a success: keep the last real answer.
                "ok": prev.get("ok") if skipped else item["ok"],
                "status": prev.get("status", 0) if skipped else item["status"],
                "error": prev.get("error", "") if skipped else item["error"],
                "at": prev.get("at") if skipped else now,
                "failures": failures + (1 if item.get("ok") is False else 0),
                "skipped": int(prev.get("skipped", 0) or 0) + (1 if skipped else 0),
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

        # Levels are a small set; a caller typo must degrade to a visible warning
        # rather than raise *after* the external channels already fired.
        known = {"info", "success", "warning", "critical"}
        level_out = level if level in known else "warning"
        payload = {**(meta or {})}
        if level_out != level:
            payload["level_coerced_from"] = level
        if deliveries:
            payload["delivery"] = deliveries
        alert = Alert(
            id=f"A{uuid.uuid4().hex[:8]}",
            t=int(now),
            level=level_out,  # type: ignore[arg-type]
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
        # A paced message was deliberately not sent; calling that a failure would teach
        # the operator to ignore the button. Only a real rejection counts.
        paced = [d["channel"] for d in deliveries if d.get("ok") is None]
        return {"ok": all(d["ok"] is not False for d in deliveries),
                "deliveries": deliveries,
                "paced": paced,
                "note": ("ถูกเลื่อนเพราะเพิ่งส่งไปไม่ถึง "
                         f"{self.min_interval:g} วินาที — ลองใหม่ภายหลัง" if paced else "")}

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
