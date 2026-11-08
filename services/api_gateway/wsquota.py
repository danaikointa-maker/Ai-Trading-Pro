"""Concurrency limit for live WebSockets, shared across processes.

The HTTP rate limiter counts *requests per minute*; a WebSocket is one request that
then costs CPU for as long as it stays open. Until now `/ws/live` had no cap at all:
one account could open sockets until the box ran out of threads, and `--workers N`
would have multiplied any per-process cap anyway.

Slots are **leases with a TTL, not counters.** A counter is wrong here: a worker that
is SIGKILLed never runs its decrement, so every crash would leak capacity until a
restart. A lease is renewed while the socket streams and simply expires when the
process holding it stops existing — the failure mode is "capacity comes back a few
seconds late", not "capacity is gone forever".

Backends mirror the rate limiter's, and for the same reason: `memory` is one process,
`sqlite` is every worker on one host, `redis` is every worker on every host. When a
shared store fails mid-flight the quota falls back to a local view, keeps the socket
alive and counts the degradation — refusing to serve a dashboard because the cache
blinked would be the worse outcome, and `/api/system/health` says when it happened.
"""
from __future__ import annotations

import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

# Keys live under this suffix so the quota cannot collide with the token buckets
# that share the same Redis/SQLite deployment.
DEFAULT_PREFIX = "no7:ws"
GLOBAL_KEY = "__all__"


@dataclass(frozen=True)
class Lease:
    """A granted slot. `degraded` means a local fallback granted it, not the shared store."""

    identity: str
    token: str
    expires_at: float
    backend: str
    degraded: bool = False


class LeaseStore(Protocol):
    name: str

    def acquire(self, identity: str, token: str, limit: int, total: int,
                ttl: float, now: float) -> tuple[bool, int, int]: ...
    def renew(self, identity: str, token: str, ttl: float, now: float) -> bool: ...
    def release(self, identity: str, token: str) -> None: ...
    def counts(self, identity: str, now: float) -> tuple[int, int]: ...
    def reset(self) -> None: ...


class MemoryLeaseStore:
    """One process's view. Correct for a single worker, nothing more."""

    name = "memory"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._leases: dict[str, dict[str, float]] = {}

    def _purge(self, now: float) -> None:
        for identity in list(self._leases):
            live = {t: e for t, e in self._leases[identity].items() if e > now}
            if live:
                self._leases[identity] = live
            else:
                self._leases.pop(identity, None)

    def acquire(self, identity: str, token: str, limit: int, total: int,
                ttl: float, now: float) -> tuple[bool, int, int]:
        with self._lock:
            self._purge(now)
            held = self._leases.get(identity, {})
            used_total = sum(len(v) for v in self._leases.values())
            if (limit > 0 and len(held) >= limit) or (total > 0 and used_total >= total):
                return False, len(held), used_total
            self._leases.setdefault(identity, {})[token] = now + ttl
            return True, len(held) + 1, used_total + 1

    def renew(self, identity: str, token: str, ttl: float, now: float) -> bool:
        with self._lock:
            held = self._leases.get(identity)
            if not held or token not in held:
                return False
            held[token] = now + ttl
            return True

    def release(self, identity: str, token: str) -> None:
        with self._lock:
            held = self._leases.get(identity)
            if held:
                held.pop(token, None)
                if not held:
                    self._leases.pop(identity, None)

    def counts(self, identity: str, now: float) -> tuple[int, int]:
        with self._lock:
            self._purge(now)
            return len(self._leases.get(identity, {})), sum(len(v) for v in self._leases.values())

    def reset(self) -> None:
        with self._lock:
            self._leases.clear()


class SqliteLeaseStore:
    """Every worker on this host shares one budget through a small WAL database.

    Acquire runs inside `BEGIN IMMEDIATE`, so two workers cannot both read "3 of 4
    used" and both take the fourth slot.
    """

    name = "sqlite"

    def __init__(self, path: str | Path, busy_timeout: float = 2.0) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, timeout=busy_timeout, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS ws_leases("
            " identity TEXT NOT NULL, token TEXT NOT NULL, expires REAL NOT NULL,"
            " PRIMARY KEY(identity, token))")
        self._conn.execute("CREATE INDEX IF NOT EXISTS ws_leases_expires ON ws_leases(expires)")
        self._conn.commit()

    def acquire(self, identity: str, token: str, limit: int, total: int,
                ttl: float, now: float) -> tuple[bool, int, int]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            try:
                cur.execute("DELETE FROM ws_leases WHERE expires <= ?", (now,))
                held = cur.execute("SELECT COUNT(*) FROM ws_leases WHERE identity = ?",
                                   (identity,)).fetchone()[0]
                used = cur.execute("SELECT COUNT(*) FROM ws_leases").fetchone()[0]
                if (limit > 0 and held >= limit) or (total > 0 and used >= total):
                    self._conn.commit()
                    return False, int(held), int(used)
                cur.execute("INSERT OR REPLACE INTO ws_leases(identity, token, expires) "
                            "VALUES(?,?,?)", (identity, token, now + ttl))
                self._conn.commit()
                return True, int(held) + 1, int(used) + 1
            except Exception:
                self._conn.rollback()
                raise

    def renew(self, identity: str, token: str, ttl: float, now: float) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE ws_leases SET expires = ? WHERE identity = ? AND token = ?",
                (now + ttl, identity, token))
            self._conn.commit()
            return cur.rowcount > 0

    def release(self, identity: str, token: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM ws_leases WHERE identity = ? AND token = ?",
                               (identity, token))
            self._conn.commit()

    def counts(self, identity: str, now: float) -> tuple[int, int]:
        with self._lock:
            self._conn.execute("DELETE FROM ws_leases WHERE expires <= ?", (now,))
            self._conn.commit()
            held = self._conn.execute("SELECT COUNT(*) FROM ws_leases WHERE identity = ?",
                                      (identity,)).fetchone()[0]
            used = self._conn.execute("SELECT COUNT(*) FROM ws_leases").fetchone()[0]
            return int(held), int(used)

    def reset(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM ws_leases")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# Purge, count, and (if there is room) take a slot — in one round trip, so two
# workers racing for the last slot cannot both win. Expiry scores are seconds.
ACQUIRE_LUA = """
local idkey, allkey = KEYS[1], KEYS[2]
local now, ttl = tonumber(ARGV[1]), tonumber(ARGV[2])
local limit, total = tonumber(ARGV[3]), tonumber(ARGV[4])
local member = ARGV[5]
redis.call('ZREMRANGEBYSCORE', idkey, '-inf', now)
redis.call('ZREMRANGEBYSCORE', allkey, '-inf', now)
local held = redis.call('ZCARD', idkey)
local used = redis.call('ZCARD', allkey)
if (limit > 0 and held >= limit) or (total > 0 and used >= total) then
  return {0, held, used}
end
local expires = now + ttl
redis.call('ZADD', idkey, expires, member)
redis.call('ZADD', allkey, expires, member)
-- Key TTL is a safety net for abandoned identities; the scores are what expire slots.
redis.call('PEXPIRE', idkey, math.floor(ttl * 2000))
redis.call('PEXPIRE', allkey, math.floor(ttl * 2000))
return {1, held + 1, used + 1}
"""

RENEW_LUA = """
local idkey, allkey = KEYS[1], KEYS[2]
local now, ttl, member = tonumber(ARGV[1]), tonumber(ARGV[2]), ARGV[3]
if redis.call('ZSCORE', idkey, member) == false then return 0 end
local expires = now + ttl
redis.call('ZADD', idkey, expires, member)
redis.call('ZADD', allkey, expires, member)
redis.call('PEXPIRE', idkey, math.floor(ttl * 2000))
redis.call('PEXPIRE', allkey, math.floor(ttl * 2000))
return 1
"""


class RedisLeaseStore:
    """Every worker on every host shares one budget."""

    name = "redis"

    def __init__(self, client: Any, prefix: str = DEFAULT_PREFIX) -> None:
        self.client = client
        self.prefix = prefix.rstrip(":")
        self._acquire = client.register_script(ACQUIRE_LUA)
        self._renew = client.register_script(RENEW_LUA)

    def _keys(self, identity: str) -> list[str]:
        return [f"{self.prefix}:id:{identity}", f"{self.prefix}:{GLOBAL_KEY}"]

    @staticmethod
    def _member(identity: str, token: str) -> str:
        return f"{identity}\x1f{token}"

    def acquire(self, identity: str, token: str, limit: int, total: int,
                ttl: float, now: float) -> tuple[bool, int, int]:
        ok, held, used = self._acquire(
            keys=self._keys(identity),
            args=[repr(float(now)), repr(float(ttl)), int(limit), int(total),
                  self._member(identity, token)])
        return bool(int(ok)), int(held), int(used)

    def renew(self, identity: str, token: str, ttl: float, now: float) -> bool:
        return bool(int(self._renew(keys=self._keys(identity),
                                    args=[repr(float(now)), repr(float(ttl)),
                                          self._member(identity, token)])))

    def release(self, identity: str, token: str) -> None:
        member = self._member(identity, token)
        idkey, allkey = self._keys(identity)
        pipe = self.client.pipeline()
        pipe.zrem(idkey, member)
        pipe.zrem(allkey, member)
        pipe.execute()

    def counts(self, identity: str, now: float) -> tuple[int, int]:
        idkey, allkey = self._keys(identity)
        pipe = self.client.pipeline()
        pipe.zremrangebyscore(idkey, "-inf", now)
        pipe.zremrangebyscore(allkey, "-inf", now)
        pipe.zcard(idkey)
        pipe.zcard(allkey)
        out = pipe.execute()
        return int(out[-2]), int(out[-1])

    def reset(self) -> None:
        """Drop only this prefix's keys — never FLUSHDB on a shared server."""
        for key in self.client.scan_iter(match=f"{self.prefix}:*", count=200):
            self.client.delete(key)


def build_lease_store(cfg: dict[str, Any] | None = None, *, path: str | Path | None = None,
                      client_factory: Callable[[], Any] | None = None,
                      env: dict[str, str] | None = None) -> tuple[LeaseStore, dict[str, Any]]:
    """Pick a backend from the same config the rate limiter uses, and say what happened.

    Operators configure one store (`ratelimit.store` + `redis_url`); the quota reuses
    it under its own key prefix rather than inventing a second thing to set up.
    """
    import os as _os

    env = _os.environ if env is None else env
    cfg = dict(cfg or {})
    requested = str(cfg.get("store", "memory") or "memory").strip().lower()
    status: dict[str, Any] = {"requested": requested, "backend": "memory", "shared": False,
                              "reason": "", "path": str(path) if path else ""}

    if requested in ("memory", "in-process", "inprocess", "local"):
        return MemoryLeaseStore(), status

    if requested == "sqlite":
        if not path:
            status["reason"] = "store=sqlite but no store_path — using memory"
            return MemoryLeaseStore(), status
        status.update(backend="sqlite", shared=True)
        return SqliteLeaseStore(path), status

    if requested != "redis":
        raise ValueError(f"unknown websocket quota store {requested!r} — "
                         f"use 'memory', 'sqlite' or 'redis'")

    url = str(cfg.get("redis_url") or env.get("NO7_REDIS_URL", "") or "").strip()
    fallback = "sqlite" if path else "memory"
    if not url:
        status["reason"] = f"store=redis but no redis_url / NO7_REDIS_URL — using {fallback}"
    elif client_factory is None:
        try:
            import redis  # type: ignore[import-not-found]

            client_factory = lambda: redis.Redis.from_url(  # noqa: E731
                url, socket_timeout=2, socket_connect_timeout=2, decode_responses=True)
        except ImportError:
            status["reason"] = ("redis requested but the `redis` package is not installed "
                                f"(pip install redis) — using {fallback}")

    if client_factory is not None and not status["reason"]:
        try:
            client = client_factory()
            client.ping()
            status.update(backend="redis", shared=True)
            return RedisLeaseStore(client, prefix=str(cfg.get("ws_key_prefix", DEFAULT_PREFIX))), status
        except Exception as exc:  # noqa: BLE001 - a dead cache must not stop boot
            status["reason"] = (f"redis unreachable ({type(exc).__name__}: {exc}) — "
                                f"using {fallback}")

    if path:
        status.update(backend="sqlite", shared=True)
        return SqliteLeaseStore(path), status
    status["reason"] += ", so the websocket cap is per process again"
    return MemoryLeaseStore(), status


class WebSocketQuota:
    """Caps concurrent live sockets per identity and in total."""

    def __init__(self, store: LeaseStore | None = None, *, per_identity: int = 4,
                 total: int = 64, ttl_seconds: float = 45.0,
                 clock: Callable[[], float] = time.time) -> None:
        self.store: LeaseStore = store or MemoryLeaseStore()
        self.per_identity = int(per_identity)
        self.total = int(total)
        self.ttl = float(ttl_seconds)
        self.clock = clock
        # Used only when the shared store throws: the socket stays up, the cap keeps
        # being enforced locally, and health reports how often that happened.
        self.fallback = MemoryLeaseStore()
        self.degraded = 0
        self.last_error = ""
        self.refused = 0
        self.granted = 0

    def _note(self, exc: Exception) -> None:
        self.degraded += 1
        self.last_error = f"{type(exc).__name__}: {exc}"

    def _mirror(self, call: Callable[[LeaseStore], Any]) -> None:
        """Keep the local store in step with what this process is really serving.

        Without the mirror, slots granted by Redis are invisible locally, so the moment
        Redis dies the fallback starts from zero and hands the same user a second full
        set of sockets — the outage would *raise* the cap instead of holding it.
        """
        try:
            call(self.fallback)
        except Exception:  # noqa: BLE001 - the mirror is best effort by definition
            pass

    def acquire(self, identity: str) -> Lease | None:
        now = self.clock()
        token = secrets.token_hex(8)
        degraded = False
        try:
            ok, _held, _used = self.store.acquire(identity, token, self.per_identity,
                                                  self.total, self.ttl, now)
        except Exception as exc:  # noqa: BLE001 - never kill a socket over the cache
            self._note(exc)
            degraded = True
            try:
                ok, _held, _used = self.fallback.acquire(identity, token, self.per_identity,
                                                         self.total, self.ttl, now)
            except Exception:  # noqa: BLE001
                ok = True  # last resort: serve the socket; health already says why
        if not ok:
            self.refused += 1
            return None
        if not degraded:
            # limit 0 = unlimited: the mirror records, it never refuses.
            self._mirror(lambda s: s.acquire(identity, token, 0, 0, self.ttl, now))
        self.granted += 1
        return Lease(identity=identity, token=token, expires_at=now + self.ttl,
                     backend=self.store.name, degraded=degraded)

    def renew(self, lease: Lease) -> bool:
        now = self.clock()
        self._mirror(lambda s: s.renew(lease.identity, lease.token, self.ttl, now))
        try:
            ok = self.store.renew(lease.identity, lease.token, self.ttl, now)
        except Exception as exc:  # noqa: BLE001
            self._note(exc)
            ok = self.fallback.renew(lease.identity, lease.token, self.ttl, now)
        if ok:
            return True
        # The lease lapsed (a long GC pause, a slow payload). Take a fresh slot rather
        # than streaming without one; if the cap is now full the caller closes us.
        try:
            regained, _h, _u = self.store.acquire(lease.identity, lease.token,
                                                  self.per_identity, self.total, self.ttl, now)
            if regained:
                self._mirror(lambda s: s.acquire(lease.identity, lease.token, 0, 0,
                                                 self.ttl, now))
        except Exception as exc:  # noqa: BLE001
            self._note(exc)
            regained, _h, _u = self.fallback.acquire(lease.identity, lease.token,
                                                     self.per_identity, self.total,
                                                     self.ttl, now)
        return bool(regained)

    def release(self, lease: Lease) -> None:
        self._mirror(lambda s: s.release(lease.identity, lease.token))
        try:
            self.store.release(lease.identity, lease.token)
        except Exception as exc:  # noqa: BLE001
            self._note(exc)

    def max_total_label(self) -> str:
        return str(self.total) if self.total > 0 else "unlimited"

    def counts(self, identity: str) -> tuple[int, int]:
        try:
            return self.store.counts(identity, self.clock())
        except Exception as exc:  # noqa: BLE001
            self._note(exc)
            try:
                return self.fallback.counts(identity, self.clock())
            except Exception:  # noqa: BLE001
                return 0, 0

    def _peek_total(self) -> int | None:
        """Live socket count for reporting — never counted as a degradation.

        Reading health must not inflate the metric health is reporting: with the
        shared store down, a 5-second poll would otherwise push `degraded` up forever
        while no socket had been affected at all.
        """
        now = self.clock()
        for store in (self.store, self.fallback):
            try:
                return store.counts(GLOBAL_KEY, now)[1]
            except Exception:  # noqa: BLE001
                continue
        return None

    def status(self) -> dict[str, Any]:
        """What the cap is, where it is kept, and whether it is being improvised."""
        live_total = self._peek_total()
        out: dict[str, Any] = {
            "store": self.store.name,
            "shared": self.store.name in ("sqlite", "redis"),
            "max_per_user": self.per_identity,
            "max_total": self.total,
            "lease_ttl_seconds": self.ttl,
            "open": live_total if live_total is not None else "unknown",
            "granted": self.granted,
            "refused": self.refused,
            "degraded": self.degraded,
        }
        if self.degraded:
            out["last_error"] = self.last_error
            out["shared"] = False
            out["warning"] = (f"the {self.store.name} store failed {self.degraded} time(s); the "
                              "cap was enforced against this process only while that lasted")
        elif not out["shared"]:
            out["warning"] = ("store=memory: each worker counts its own sockets, so "
                              "--workers N allows N times this cap. Use sqlite (one host) "
                              "or redis (several hosts).")
        return out
