"""Rate limiting for the REST surface.

The login throttle protects credentials; this protects capacity. Without it a
retry loop in the dashboard, a stray `while true` in a script, or two windows
left open can hammer the expensive paths (order sends, backtests, LLM explain,
model training) until the box stops answering.

Identity is the authenticated user when a valid bearer token is present, else the
client IP, so one noisy user cannot spend another user's budget. Limits are token
buckets: a burst is allowed, sustained abuse is not.

Where the buckets live decides who shares a budget (``build_store``):

* ``memory`` — this process. One worker only; N workers means N times the limit.
* ``sqlite`` — a small file, so every worker *on this host* shares one budget.
* ``redis`` — every worker and every host shares one budget.

A backend that cannot be used is never silently swapped: the store we ended up with,
what was requested, and why they differ are all reported in
``/api/system/health → ratelimit``. If Redis dies *while running*, each affected
request still gets limited against the in-process bucket, the counter ``degraded``
goes up, and the response carries ``x-ratelimit-degraded`` — the request is served,
but not as if nothing happened.
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
    name = "memory"

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
    name = "sqlite"
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


class RedisBucketStore:
    """Token buckets in Redis, shared by every worker and every host.

    The refill-and-spend is one Lua script so two workers cannot both read the same
    token: Redis runs it atomically, which is the only reason this can replace a
    transaction. The key expires after one window, so idle identities disappear
    without a sweeper.

    The timestamp comes from the caller (the app's clock), not from Redis: every node
    then agrees with the same authority, at the price of needing NTP. Clock skew shows
    up as an inaccurate refill, never as a lost or duplicated token.
    """

    wall_clock = True
    name = "redis"

    # KEYS[1] bucket key; ARGV = limit, rate (tokens/sec), now (epoch seconds), ttl ms.
    # Returns {allowed(0|1), tokens-as-string}: Redis replies cannot carry a float, so
    # the balance travels as a string.
    #
    # Every number is serialised with %.17g, not Lua's tostring(). tostring() is
    # "%.14g", which silently rounds the balance on every single spend — enough that
    # a bucket sitting exactly on 1.000000 token allowed one more request in memory
    # than it did in Redis. %.17g round-trips a float64 exactly, so every backend
    # applies the same policy down to the last bit (proved in tests/test_redis_real.py).
    SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local data = redis.call('HMGET', key, 'tokens', 'updated')
local tokens = tonumber(data[1])
local updated = tonumber(data[2])
if tokens == nil then
  tokens = limit
  updated = now
end
local elapsed = now - updated
if elapsed > 0 then
  tokens = math.min(limit, tokens + elapsed * rate)
end
local allowed = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
end
redis.call('HSET', key, 'tokens', string.format('%.17g', tokens),
           'updated', string.format('%.17g', now))
redis.call('PEXPIRE', key, ttl)
return {allowed, string.format('%.17g', tokens)}
"""

    def __init__(self, client: Any, prefix: str = "no7:ratelimit") -> None:
        self.client = client
        self.prefix = prefix.rstrip(":")
        self._script = getattr(client, "register_script", None)
        self.script = self._script(self.SCRIPT) if callable(self._script) else None

    def _key(self, key: tuple[str, str]) -> str:
        return f"{self.prefix}:{key[0]}:{key[1]}"

    def _run(self, script_args: list) -> list:
        if self.script is not None:
            return self.script(keys=[script_args[0]], args=script_args[1:])
        return self.client.eval(self.SCRIPT, 1, *script_args)

    def spend(self, key: tuple[str, str], limit: float, rate: float,
              now: float) -> tuple[bool, float]:
        ttl_ms = max(1000, int((limit / rate if rate > 0 else 60) * 1000))
        out = self._run([self._key(key), limit, rate, now, ttl_ms])
        allowed = int(out[0]) == 1
        tokens = float(out[1])
        return allowed, tokens

    def reset(self) -> None:
        # Only drop our own keys: the prefix is per-deployment, not the whole database.
        pattern = f"{self.prefix}:*"
        scan = getattr(self.client, "scan_iter", None)
        if callable(scan):
            batch = [k for k in scan(match=pattern)]
            if batch:
                self.client.delete(*batch)
            return
        self.client.flushdb()

    @property
    def tracked(self) -> int:
        scan = getattr(self.client, "scan_iter", None)
        if not callable(scan):
            return -1
        return sum(1 for _ in scan(match=f"{self.prefix}:*"))


Store = MemoryBucketStore | SqliteBucketStore | RedisBucketStore


def make_store(kind: str | None, path: str | Path | None = None,
               max_keys: int = 4096) -> Store:
    """Build the store named in config. Unknown kinds fail loudly, not silently."""
    name = (kind or "memory").strip().lower()
    if name in ("memory", "in-process", "inprocess", "local"):
        return MemoryBucketStore(max_keys=max_keys)
    if name == "sqlite":
        if not path:
            raise ValueError("ratelimit store 'sqlite' needs a path")
        return SqliteBucketStore(path)
    if name == "redis":
        raise ValueError("ratelimit store 'redis' needs a URL — use build_store()")
    raise ValueError(f"unknown ratelimit store {kind!r} — use 'memory', 'sqlite' or 'redis'")


def build_store(cfg: dict[str, Any] | None = None, *, path: str | Path | None = None,
                client_factory: Callable[[], Any] | None = None,
                env: dict[str, str] | None = None,
                max_keys: int = 4096) -> tuple[Store, dict[str, Any]]:
    """Pick the store and say what actually happened.

    ``cfg`` is the ``ratelimit`` block. Returns ``(store, status)`` where status always
    carries ``backend`` (what we got), ``requested`` (what config asked for), ``shared``
    (does another process see the same budget?) and ``reason`` when the two differ.
    """
    import os as _os

    env = _os.environ if env is None else env
    cfg = dict(cfg or {})
    requested = str(cfg.get("store", "memory") or "memory").strip().lower()
    status: dict[str, Any] = {"requested": requested, "backend": "memory", "shared": False,
                              "reason": "", "path": str(path) if path else "", "url": ""}

    if requested in ("memory", "in-process", "inprocess", "local"):
        return MemoryBucketStore(max_keys=max_keys), status

    if requested == "sqlite":
        if not path:
            status["reason"] = "ratelimit.store=sqlite but no store_path — using memory"
            return MemoryBucketStore(max_keys=max_keys), status
        status.update(backend="sqlite", shared=True)
        return SqliteBucketStore(path), status

    if requested != "redis":
        raise ValueError(f"unknown ratelimit store {requested!r} — "
                         f"use 'memory', 'sqlite' or 'redis'")

    url = str(cfg.get("redis_url") or env.get("NO7_REDIS_URL", "") or "").strip()
    status["url"] = url.replace("//", "//***@") if "@" in url else url
    if not url:
        status["reason"] = ("ratelimit.store=redis but no redis_url / NO7_REDIS_URL — "
                            f"falling back to the {'sqlite' if path else 'memory'} store")
        if path:
            status.update(backend="sqlite", shared=True)
            return SqliteBucketStore(path), status
        status["reason"] += ", so limits are per process again"
        return MemoryBucketStore(max_keys=max_keys), status

    if client_factory is None:
        try:
            import redis  # type: ignore[import-not-found]
        except ImportError:
            status["reason"] = ("redis requested but the `redis` package is not installed "
                                f"(pip install redis) — falling back to the "
                                f"{'sqlite' if path else 'memory'} store")
            if path:
                status.update(backend="sqlite", shared=True)
                return SqliteBucketStore(path), status
            return MemoryBucketStore(max_keys=max_keys), status
        client_factory = lambda: redis.Redis.from_url(  # noqa: E731
            url, socket_timeout=2, socket_connect_timeout=2, decode_responses=True)

    try:
        client = client_factory()
        client.ping()
    except Exception as exc:  # noqa: BLE001 - a dead cache must not stop boot
        status["reason"] = (f"redis unreachable ({type(exc).__name__}: {exc}) — "
                            f"falling back to the {'sqlite' if path else 'memory'} store")
        if path:
            status.update(backend="sqlite", shared=True)
            return SqliteBucketStore(path), status
        return MemoryBucketStore(max_keys=max_keys), status

    status.update(backend="redis", shared=True)
    return RedisBucketStore(client, prefix=str(cfg.get("key_prefix", "no7:ratelimit"))), status


class RateLimiter:
    """Token buckets keyed by (rule, identity), backed by a pluggable store."""

    def __init__(self, rules: dict[str, dict[str, Any]] | None = None,
                 clock: Callable[[], float] | None = None, max_keys: int = 4096,
                 store: MemoryBucketStore | SqliteBucketStore | None = None) -> None:
        self.rules: dict[str, dict[str, Any]] = {**DEFAULT_RULES, **(rules or {})}
        self.store = store if store is not None else MemoryBucketStore(max_keys=max_keys)
        # A shared store can fail mid-flight. Requests keep being served (a trading
        # dashboard that 500s because a cache blipped is worse), but they are limited
        # against this process instead, and both the counter and the response header
        # say so. Silence would turn a degraded limiter into no limiter at all.
        self._fallback = MemoryBucketStore(max_keys=max_keys)
        self.degraded = 0
        self.last_error = ""
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
        now = self.clock()
        try:
            allowed, tokens = self.store.spend((rule, identity), limit, rate, now)
        except Exception as exc:  # noqa: BLE001 - see __init__ for why this is not fatal
            self.degraded += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            allowed, tokens = self._fallback.spend((rule, identity), limit, rate, now)
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
        try:
            return self.store.tracked
        except Exception:  # noqa: BLE001 - health must never raise
            return -1

    def status(self) -> dict[str, Any]:
        """What the limiter is doing right now, including how often it had to improvise."""
        return {"store": getattr(self.store, "name", type(self.store).__name__),
                "degraded": self.degraded, "last_error": self.last_error,
                "tracked": self.tracked}


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
        before = self.limiter.degraded
        allowed, remaining, retry_after = self.limiter.check(identity, rule)
        degraded = self.limiter.degraded > before
        if not allowed:
            seconds = max(1, int(retry_after + 0.999))
            body = (f'{{"detail":"rate limit exceeded for {rule}; retry in {seconds}s",'
                    f'"rule":"{rule}","retry_after":{round(retry_after, 2)}}}').encode()
            headers = [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"retry-after", str(seconds).encode()),
                (b"x-ratelimit-remaining", b"0"),
            ]
            if degraded:
                # A denial from the local fallback is not the shared budget running
                # out: the caller may well have quota left on the other workers, and
                # `retry-after` was computed from this process's bucket. Saying so on
                # the 429 — not only on the 200 — is what makes the two tellable apart.
                headers.append((b"x-ratelimit-degraded",
                                str(getattr(self.limiter.store, "name", "store")).encode()))
            await send({
                "type": "http.response.start",
                "status": 429,
                "headers": headers,
            })
            await send({"type": "http.response.body", "body": body})
            return

        async def _send_with_header(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((b"x-ratelimit-remaining", str(remaining).encode()))
                if degraded:
                    # The limit that applied was a local one, not the shared one.
                    headers.append((b"x-ratelimit-degraded",
                                    str(getattr(self.limiter.store, "name", "store")).encode()))
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
