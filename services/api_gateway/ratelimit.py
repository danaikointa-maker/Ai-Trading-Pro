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

import time
from dataclasses import dataclass
from typing import Any, Callable

# rule -> {limit, window_seconds}; `default` covers everything not listed below.
DEFAULT_RULES: dict[str, dict[str, float]] = {
    "order": {"limit": 10, "window_seconds": 60},
    "explain": {"limit": 20, "window_seconds": 60},
    "backtest": {"limit": 6, "window_seconds": 60},
    "train": {"limit": 2, "window_seconds": 3600},
    "default": {"limit": 300, "window_seconds": 60},
}

# Longest prefix wins, so `/api/trading/close-all` lands in `order` too.
RULE_PATHS: tuple[tuple[str, str], ...] = (
    ("/api/trading/order", "order"),
    ("/api/trading/close", "order"),
    ("/api/explain", "explain"),
    ("/api/backtests", "backtest"),
    ("/api/forecast/train", "train"),
)

# Nothing here costs anything, and blocking the health probe or static assets
# would break the dashboard for no reason.
SKIP_PREFIXES = ("/ws", "/assets", "/api/docs", "/api/openapi.json", "/api/system/health")


@dataclass
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    """In-process token buckets keyed by (rule, identity)."""

    def __init__(self, rules: dict[str, dict[str, Any]] | None = None,
                 clock: Callable[[], float] = time.monotonic, max_keys: int = 4096) -> None:
        self.rules: dict[str, dict[str, Any]] = {**DEFAULT_RULES, **(rules or {})}
        self.clock = clock
        self.max_keys = max_keys
        self._buckets: dict[tuple[str, str], _Bucket] = {}

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
        key = (rule, identity)
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
            return True, int(bucket.tokens), 0.0

        # Never report 0 seconds: the caller would retry tighter than the refill.
        retry_after = min(window, max(rate and (1.0 - bucket.tokens) / rate, 1.0))
        return False, 0, retry_after

    # ------------------------------------------------------------------ upkeep
    def _evict(self) -> None:
        ordered = sorted(self._buckets.items(), key=lambda item: item[1].updated)
        for key, _ in ordered[: max(1, len(ordered) // 2)]:
            self._buckets.pop(key, None)

    def reset(self) -> None:
        self._buckets.clear()

    @property
    def tracked(self) -> int:
        return len(self._buckets)


class RateLimitMiddleware:
    """ASGI middleware that answers 429 once an identity spends its budget.

    Implemented as a plain ASGI middleware (not BaseHTTPMiddleware) so it stays
    cheap on the hot path and works for every response type.
    """

    def __init__(self, app: Any, limiter: RateLimiter, settings: Any | None = None) -> None:
        self.app = app
        self.limiter = limiter
        self.settings = settings
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
        client = scope.get("client") or ("unknown", 0)
        return f"ip:{client[0]}"
