"""Shared runtime state, so several processes can serve one trading runtime.

The runtime lease (see ``state.claim_runtime_lease``) makes sure exactly one
process ticks, decides and trades. That is the safety property. The missing half
was usefulness: a second process used to boot, refuse to trade, and serve an empty
dashboard forever.

With a shared backend the leader publishes its live frame, and any other process
reads it and serves it as a **replica**: same numbers, read only, no orders. That
is also what makes ``uvicorn --workers N`` viable for the API as long as the
backend is shared.

Backends:

* ``local`` (default) — a dict in this process. Correct for one worker, and the
  replica path degrades to "blocked" because there is nothing to read.
* ``redis`` — ``SET key frame EX ttl`` / ``GET key``; needs ``pip install redis``
  and a reachable server. If it is requested but unusable, the platform falls back
  to ``local`` **and reports why** rather than pretending the cluster works.
"""
from __future__ import annotations

import json
import math
import os
import time
from typing import Any, Callable

LIVE_KEY = "no7:live:v1"
DEFAULT_TTL = 10


class SharedState:
    """Minimal contract both backends implement."""

    name = "local"
    default_ttl: int = DEFAULT_TTL

    def publish(self, key: str, payload: dict[str, Any], ttl: int | None = None) -> None:
        raise NotImplementedError

    def read(self, key: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def healthy(self) -> dict[str, Any]:
        return {"ok": True, "backend": self.name, "error": ""}

    def close(self) -> None:
        return None


class LocalSharedState(SharedState):
    """In-process store with expiry. Only one process can ever see these frames."""

    name = "local"

    def __init__(self, default_ttl: int = DEFAULT_TTL) -> None:
        self.default_ttl = max(1, int(default_ttl))
        self._items: dict[str, tuple[float, dict[str, Any]]] = {}

    def publish(self, key: str, payload: dict[str, Any], ttl: int | None = None) -> None:
        ttl = self.default_ttl if ttl is None else ttl
        self._items[key] = (time.time() + max(1, int(ttl)), payload)

    def read(self, key: str) -> dict[str, Any] | None:
        item = self._items.get(key)
        if not item:
            return None
        expires_at, payload = item
        if expires_at < time.time():
            self._items.pop(key, None)
            return None
        return payload


class RedisSharedState(SharedState):
    """Frames in Redis, so a replica on another worker (or host) can read them."""

    name = "redis"

    def __init__(self, client: Any, prefix: str = "no7",
                 default_ttl: int = DEFAULT_TTL) -> None:
        self.client = client
        self.prefix = prefix
        self.default_ttl = max(1, int(default_ttl))
        self.last_error = ""

    def _key(self, key: str) -> str:
        return key if key.startswith(f"{self.prefix}:") else f"{self.prefix}:{key}"

    def publish(self, key: str, payload: dict[str, Any], ttl: int | None = None) -> None:
        ttl = self.default_ttl if ttl is None else ttl
        try:
            self.client.set(self._key(key), json.dumps(payload, default=str), ex=max(1, int(ttl)))
            self.last_error = ""
        except Exception as exc:  # noqa: BLE001 - a dying Redis must not stop trading
            self.last_error = f"{type(exc).__name__}: {exc}"

    def read(self, key: str) -> dict[str, Any] | None:
        try:
            raw = self.client.get(self._key(key))
        except Exception as exc:  # noqa: BLE001 - readers degrade to "nothing to serve"
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None
        self.last_error = ""
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def healthy(self) -> dict[str, Any]:
        try:
            pong = self.client.ping()
            if not pong:
                return {"ok": False, "backend": self.name, "error": "ping failed"}
            if self.last_error:
                # Ping works again but the last real operation failed; report it
                # until an operation succeeds, instead of a reassuring green tick.
                return {"ok": False, "backend": self.name, "error": self.last_error}
            return {"ok": True, "backend": self.name, "error": ""}
        except Exception as exc:  # noqa: BLE001 - health must never raise
            return {"ok": False, "backend": self.name,
                    "error": self.last_error or f"{type(exc).__name__}: {exc}"}


def build_shared_state(settings: Any, client_factory: Callable[[], Any] | None = None,
                       env: dict[str, str] | None = None) -> tuple[SharedState, dict[str, Any]]:
    """Pick the backend and describe what actually happened.

    Returns ``(state, status)`` where status always carries ``backend`` (what we
    got), ``requested`` (what was configured) and ``reason`` when they differ.
    """
    env = os.environ if env is None else env
    cfg = dict(getattr(settings, "cluster", {}) or {})
    requested = str(cfg.get("backend", "local") or "local").lower()
    ttl = int(cfg.get("state_ttl_seconds", DEFAULT_TTL) or DEFAULT_TTL)
    status: dict[str, Any] = {"requested": requested, "backend": "local", "reason": "",
                              "ttl_seconds": ttl}

    if requested != "redis":
        return LocalSharedState(default_ttl=ttl), status

    url = str(cfg.get("redis_url") or env.get("NO7_REDIS_URL", "") or "").strip()
    if not url:
        status["reason"] = ("cluster.backend=redis but no redis_url / NO7_REDIS_URL — "
                            "using the in-process store, so replicas cannot follow this process")
        return LocalSharedState(default_ttl=ttl), status

    if client_factory is None:
        try:
            import redis  # type: ignore[import-not-found]
        except ImportError:
            status["reason"] = ("redis requested but the `redis` package is not installed "
                                "(pip install redis) — using the in-process store")
            return LocalSharedState(default_ttl=ttl), status
        client_factory = lambda: redis.Redis.from_url(  # noqa: E731
            url, socket_timeout=2, socket_connect_timeout=2, decode_responses=True)

    try:
        client = client_factory()
    except Exception as exc:  # noqa: BLE001 - a dead backend must not stop boot
        status["reason"] = f"redis unavailable ({type(exc).__name__}: {exc}) — using the in-process store"
        return LocalSharedState(default_ttl=ttl), status

    state = RedisSharedState(client, prefix=str(cfg.get("key_prefix", "no7") or "no7"),
                             default_ttl=ttl)
    try:
        client.ping()
    except Exception as exc:  # noqa: BLE001 - a lazy client hides a dead server
        status["reason"] = (f"redis unreachable at {url} ({type(exc).__name__}: {exc}) — "
                            f"using the in-process store, so replicas cannot follow this process")
        return LocalSharedState(default_ttl=ttl), status
    status["backend"] = "redis"
    return state, status


def replica_payload(shared: SharedState, key: str = LIVE_KEY) -> dict[str, Any] | None:
    """Read the leader's frame and mark it as such, or None when there is none.

    TTL is not enough: reject malformed/future/over-age publication timestamps
    even if a backend retains the item. Account ownership is checked by runtime.
    """
    frame = shared.read(key)
    if not isinstance(frame, dict) or not isinstance(frame.get("payload"), dict):
        return None
    published = frame.get("published_at")
    now = time.time()
    if (type(published) not in (int, float) or not math.isfinite(published)
            or not 0 <= now - published <= DEFAULT_TTL):
        return None
    return {
        **frame["payload"],
        "replica": True,
        "served_by": frame.get("owner", "unknown"),
        "frame_age_seconds": now - published,
        "_account_identity": frame.get("account_identity"),
    }


def decide_role(lease_state: str, backend: str, has_replica_frame: bool) -> str:
    """What this process is, for the health panel.

    ``leader``  — it holds the lease and drives the runtime
    ``replica`` — it does not hold the lease but can serve the leader's frames
    ``blocked`` — it does not hold the lease and cannot see the leader (no shared
                backend): the previous behaviour, now explicitly labelled
    """
    if lease_state in ("held", "shared"):
        return "leader"
    if lease_state in ("blocked", "lost") and backend != "local" and has_replica_frame:
        return "replica"
    if lease_state in ("blocked", "lost"):
        return "blocked"
    return "solo"
