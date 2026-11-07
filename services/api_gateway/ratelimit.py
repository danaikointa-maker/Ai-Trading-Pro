"""Rate limiting for the REST surface.

The login throttle protects credentials; this protects capacity. Without it a
retry loop in the dashboard, a stray `while true` in a script, or two windows
left open can hammer the expensive paths (order sends, backtests, LLM explain,
model training) until the box stops answering.

Identity is the authenticated user when a valid bearer token is present, else the
client IP, so one noisy user cannot spend another user's budget. Limits are token
buckets: a burst is allowed, sustained abuse is not.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from services.api_gateway.netutil import client_ip, parse_networks

# rule -> {limit, window_seconds}; `default` covers everything not listed below.
DEFAULT_RULES: dict[str, dict[str, float]] = {
    "order": {"limit": 10, "window_seconds": 60},
    "explain": {"limit": 20, "window_seconds": 60},
    "backtest": {"limit": 6, "window_seconds": 60},
    "train": {"limit": 2, "window_seconds": 3600},
    # The EA polls once a second; 240/min leaves room for a retry without letting a
    # runaway loop hammer the box.
    "bridge": {"limit": 240, "window_seconds": 60},
    "default": {"limit": 300, "window_seconds": 60},
}

# Longest prefix wins, so `/api/trading/close-all` lands in `order` too.
RULE_PATHS: tuple[tuple[str, str], ...] = (
    ("/api/trading/order", "order"),
    ("/api/trading/close", "order"),
    ("/api/explain", "explain"),
    ("/api/backtests", "backtest"),
    ("/api/forecast/train", "train"),
    ("/api/bridge", "bridge"),
)

# Nothing here costs anything, and blocking the health probe or static assets
# would break the dashboard for no reason.
SKIP_PREFIXES = ("/ws", "/assets", "/api/docs", "/api/openapi.json", "/api/system/health")


@dataclass
class _Bucket:
    tokens: float
    updated: float


class MemoryBucketStore:
    """Token buckets in this process only (the default).

    Correct for a single uvicorn worker; with several workers each one would hand
    out its own full budget, so the effective limit multiplies by the worker count.
    """

    wall_clock = False

    def __init__(self, max_keys: int = 4096) -> None:
        self.max_keys = max_keys
        self._buckets: dict[tuple[str, str], _Bucket] = {}

    def spend(self, key: tuple[str, str], limit: float, rate: float,
              now: float) -> tuple[bool, float]:
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= self.max_keys:
                self._evict()
            bucket = _Bucket(tokens=limit, updated=now)
            self._buckets[key] = bucket
        else:
            bucket.tokens = min(limit, bucket.tokens + max(0.0, now - bucket.updated) * rate)
            bucket.updated = now
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True, bucket.tokens
        return False, bucket.tokens

    def _evict(self) -> None:
        ordered = sorted(self._buckets.items(), key=lambda item: item[1].updated)
        for key, _ in ordered[: max(1, len(ordered) // 2)]:
            self._buckets.pop(key, None)

    def reset(self) -> None:
        self._buckets.clear()

    @property
    def tracked(self) -> int:
        return len(self._buckets)


class SqliteBucketStore:
    """Token buckets in a small SQLite file, shared by every worker on this host.

    Each spend is one `BEGIN IMMEDIATE` transaction so two workers cannot both read
    the same token and both spend it. That costs a write per limited request — fine
    for a dashboard, and the reason this is opt-in rather than the default. Use a
    separate file from the application database to keep the hot path off it.
    """

    wall_clock = True
    PRUNE_EVERY = 512
    PRUNE_AGE = 6 * 3600

    def __init__(self, path: str | Path, busy_timeout: float = 2.0) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._spends = 0
        self._conn = sqlite3.connect(self.path, timeout=busy_timeout, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS buckets("
            " key TEXT PRIMARY KEY, tokens REAL NOT NULL, updated REAL NOT NULL)")

    def spend(self, key: tuple[str, str], limit: float, rate: float,
              now: float) -> tuple[bool, float]:
        k = "\x1f".join(key)
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT tokens, updated FROM buckets WHERE key = ?", (k,)).fetchone()
                if row is None:
                    tokens = limit
                    self._conn.execute(
                        "INSERT INTO buckets(key, tokens, updated) VALUES(?,?,?)", (k, tokens, now))
                else:
                    tokens = min(limit, float(row[0]) + max(0.0, now - float(row[1])) * rate)
                allowed = tokens >= 1.0
                if allowed:
                    tokens -= 1.0
                self._conn.execute(
                    "UPDATE buckets SET tokens = ?, updated = ? WHERE key = ?", (tokens, now, k))
                self._spends += 1
                if self._spends % self.PRUNE_EVERY == 0:
                    self._conn.execute("DELETE FROM buckets WHERE updated < ?",
                                       (now - self.PRUNE_AGE,))
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return allowed, tokens

    def reset(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM buckets")
            self._conn.commit()

    @property
    def tracked(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM buckets").fetchone()
        return int(row[0])

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def make_store(kind: str | None, path: str | Path | None = None,
               max_keys: int = 4096) -> MemoryBucketStore | SqliteBucketStore:
    """Build the store named in config. Unknown kinds fail loudly, not silently."""
    name = (kind or "memory").strip().lower()
    if name in ("memory", "in-process", "inprocess", "local"):
        return MemoryBucketStore(max_keys=max_keys)
    if name == "sqlite":
        if not path:
            raise ValueError("ratelimit store 'sqlite' needs a path")
        return SqliteBucketStore(path)
    raise ValueError(f"unknown ratelimit store {kind!r} — use 'memory' or 'sqlite'")


class RateLimiter:
    """Token buckets keyed by (rule, identity), backed by a pluggable store."""

    def __init__(self, rules: dict[str, dict[str, Any]] | None = None,
                 clock: Callable[[], float] | None = None, max_keys: int = 4096,
                 store: MemoryBucketStore | SqliteBucketStore | None = None) -> None:
        self.rules: dict[str, dict[str, Any]] = {**DEFAULT_RULES, **(rules or {})}
        self.store = store if store is not None else MemoryBucketStore(max_keys=max_keys)
        # A shared store is read by other processes, so it must key on a clock they
        # all agree about; only the in-process store can use the cheap monotonic one.
        self.clock = clock or (time.time if getattr(self.store, "wall_clock", False)
                               else time.monotonic)

    # ------------------------------------------------------------------ rules
    @staticmethod
    def rule_for(path: str, method: str) -> str:
        if method.upper() in ("GET", "HEAD", "OPTIONS"):
            return "default"
        for prefix, rule in RULE_PATHS:
            if path.startswith(prefix):
                return rule
        return "default"

    def limit_of(self, rule: str) -> tuple[float, float]:
        cfg = self.rules.get(rule) or self.rules["default"]
        limit = float(cfg.get("limit", 300) or 300)
        window = float(cfg.get("window_seconds", 60) or 60)
        return max(1.0, limit), max(1.0, window)

    # ------------------------------------------------------------------ check
    def check(self, identity: str, rule: str) -> tuple[bool, int, float]:
        """Spend one token. Returns (allowed, remaining, retry_after_seconds)."""
        limit, window = self.limit_of(rule)
        rate = limit / window
        allowed, tokens = self.store.spend((rule, identity), limit, rate, self.clock())
        if allowed:
            return True, int(tokens), 0.0
        # Never report 0 seconds: the caller would retry tighter than the refill.
        retry_after = min(window, max((1.0 - tokens) / rate, 1.0))
        return False, 0, retry_after

    # ------------------------------------------------------------------ upkeep
    def reset(self) -> None:
        self.store.reset()

    @property
    def tracked(self) -> int:
        return self.store.tracked


class RateLimitMiddleware:
    """ASGI middleware that answers 429 once an identity spends its budget.

    Implemented as a plain ASGI middleware (not BaseHTTPMiddleware) so it stays
    cheap on the hot path and works for every response type.
    """

    def __init__(self, app: Any, limiter: RateLimiter, settings: Any | None = None,
                 trusted_proxies: list[str] | None = None) -> None:
        self.app = app
        self.limiter = limiter
        self.settings = settings
        # Only a trusted reverse proxy may tell us who the client is; otherwise one
        # forged header would hand out a fresh budget per request.
        self.trusted = parse_networks(trusted_proxies or [])
        cfg = (getattr(settings, "app", {}) or {}).get("ratelimit", {}) if settings else {}
        self.enabled = bool(cfg.get("enabled", True))

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        method = scope.get("method", "GET")
        if not self.enabled or method == "OPTIONS" or not path.startswith("/api") \
                or any(path.startswith(p) for p in SKIP_PREFIXES):
            return await self.app(scope, receive, send)

        identity = self._identity(scope)
        rule = self.limiter.rule_for(path, method)
        allowed, remaining, retry_after = self.limiter.check(identity, rule)
        if not allowed:
            seconds = max(1, int(retry_after + 0.999))
            body = (f'{{"detail":"rate limit exceeded for {rule}; retry in {seconds}s",'
                    f'"rule":"{rule}","retry_after":{round(retry_after, 2)}}}').encode()
            await send({
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"retry-after", str(seconds).encode()),
                    (b"x-ratelimit-remaining", b"0"),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return

        async def _send_with_header(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((b"x-ratelimit-remaining", str(remaining).encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, _send_with_header)

    # ------------------------------------------------------------------ identity
    def _identity(self, scope) -> str:
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        raw = headers.get("authorization", "")
        token = raw[7:] if raw.lower().startswith("bearer ") else ""
        if token and self.settings is not None:
            try:
                from services.api_gateway.auth import decode_token

                payload = decode_token(self.settings, token)
            except Exception:  # noqa: BLE001 - never fail a request over identity parsing
                payload = None
            if payload and payload.get("sub"):
                return f"user:{payload['sub']}"
        return f"ip:{client_ip(scope, self.trusted)}"
