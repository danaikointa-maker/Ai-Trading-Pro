"""EA bridge relay: an MQL5 Expert Advisor polls this server and executes for us.

Why a bridge at all
-------------------
The `mt5` adapter needs the MetaTrader5 Python package, which only exists on a Windows
host next to the terminal. A bridge flips the direction: the API server stays wherever
it runs, an Expert Advisor inside the terminal polls it over HTTP, executes, and reports
back. The wire protocol below is the whole contract, so the *same* server code talks to
the real EA and to the simulator used in tests.

The four rules that make this safe
----------------------------------
1. **One delivery.** A command is handed to the EA once. If it is not acknowledged it
   expires and is never sent again — an unacknowledged order might already be live at
   the broker, so re-sending is how you get two positions.
2. **Nothing old is reused.** Quotes, account state and positions are only served while
   their snapshot is inside `fresh_seconds`/`stale_seconds`; past that the adapter
   reports stale and refuses to price or trade. A reconnect (new session id) *clears*
   the snapshot and drops queued commands instead of merging old state with new.
3. **Tokens are per account and compared in constant time**, and an unconfigured token
   disables the account entirely (fail closed, never "open by default").
4. **Every acknowledgement is answered**, including duplicates and unknown ids, so a
   late EA learns what happened instead of guessing.

State lives in a `BridgeStore` (services/bridge/store.py). With several workers the
shared SQLite store is used, because the EA's poll can land on any of them: a queue in
one process's memory would lose the leader's orders and let the EA flap between workers.
"""
from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from typing import Any, Callable

from packages.persistence.db import Database
from services.bridge.store import (ACKED, EXPIRED, ORPHANED, PENDING, BridgeStore,
                                   CommandState, MemoryStore, SessionState,
                                   build_store)

__all__ = ["BridgeError", "BridgeTokenError", "BridgeRelay", "PENDING", "DELIVERED",
           "ACKED", "EXPIRED", "ORPHANED", "SessionState", "CommandState", "BridgeStore"]
DELIVERED = "delivered"


class BridgeError(RuntimeError):
    """Protocol-level refusal; the message is shown to the operator and/or the EA."""


class BridgeTokenError(BridgeError):
    """The credential is missing or wrong — always answered with 401, never retried."""


class BridgeRelay:
    def __init__(self, accounts: dict[str, str] | None = None, *,
                 store: BridgeStore | None = None, db: Database | None = None,
                 fresh_seconds: float = 5.0, stale_seconds: float = 15.0,
                 command_ttl_seconds: float = 30.0, ack_grace_seconds: float = 20.0,
                 max_pending: int = 50, poll_interval_ms: int = 1000,
                 order_timeout_seconds: float = 20.0, enabled: bool = True,
                 clock: Callable[[], float] | None = None,
                 read_only: bool = True, require_demo_identity: bool = True,
                 demo_identities: dict[str, dict[str, Any]] | None = None) -> None:
        # account_id -> token. An empty token means "not configured" and is refused.
        self.accounts = {k: v for k, v in (accounts or {}).items() if v}
        self.read_only = read_only
        self.require_demo_identity = require_demo_identity
        self.demo_identities = demo_identities or {}
        self.store: BridgeStore = store or build_store(db)
        self.fresh_seconds = float(fresh_seconds)
        self.stale_seconds = float(stale_seconds)
        self.command_ttl_seconds = float(command_ttl_seconds)
        self.ack_grace_seconds = float(ack_grace_seconds)
        self.max_pending = int(max_pending)
        self.poll_interval_ms = int(poll_interval_ms)
        self.order_timeout_seconds = float(order_timeout_seconds)
        self.enabled = bool(enabled)
        self.clock = clock
        self.audit: Callable[[str, dict[str, Any]], None] | None = None
        self.default_store = MemoryStore() if store is None and db is None else None

    # ------------------------------------------------------------- helpers
    def _now(self, now: float | None = None) -> float:
        if now is not None:
            return float(now)
        return float(self.clock()) if self.clock else time.time()

    def _log(self, event: str, payload: dict[str, Any]) -> None:
        if self.audit is not None:
            try:
                self.audit(event, payload)
            except Exception:  # noqa: BLE001 - auditing must never break trading state
                pass

    def require_enabled(self) -> None:
        if not self.enabled:
            raise BridgeError("EA bridge is disabled (config: bridge.enabled=false)")

    def check_token(self, account_id: str, token: str) -> None:
        """Constant-time comparison; unknown account and wrong token look the same."""
        expected = self.accounts.get(account_id)
        if not expected or not token:
            raise BridgeTokenError("bridge account or token is not configured")
        if not hmac.compare_digest(str(token), str(expected)):
            raise BridgeTokenError("invalid bridge token")

    def _check_identity(self, account_id: str, identity: dict[str, Any]) -> None:
        if not self.require_demo_identity:
            return
        expected = self.demo_identities.get(account_id, {})
        login, server = str(expected.get("login") or ""), str(expected.get("server") or "")
        if (not login or not server or str(identity.get("login") or "") != login
                or identity.get("server") != server or identity.get("trade_mode") != "demo"
                or identity.get("connected") is not True):
            raise BridgeError("Demo account identity is missing, disconnected or mismatched")

    # ------------------------------------------------------------ read-side
    def get(self, account_id: str) -> SessionState | None:
        return self.store.load(account_id)

    def sessions(self) -> dict[str, SessionState]:
        return {s.account_id: s for s in self.store.load_all()}

    def snapshot(self, account_id: str) -> dict[str, Any]:
        session = self.store.load(account_id)
        return dict(session.snapshot) if session else {}

    def symbols(self, account_id: str) -> list[str]:
        session = self.store.load(account_id)
        return list(session.symbols) if session else []

    def command(self, account_id: str, command_id: str) -> CommandState | None:
        return self.store.command(account_id, command_id)

    def commands(self, account_id: str) -> list[CommandState]:
        return self.store.commands(account_id)

    def age(self, account_id: str, now: float | None = None) -> float | None:
        session = self.store.load(account_id)
        if session is None:
            return None
        return max(0.0, self._now(now) - session.last_seen)

    def session_health(self, account_id: str, now: float | None = None) -> str:
        age = self.age(account_id, now)
        if age is None:
            return "disconnected"
        if age <= self.fresh_seconds:
            return "connected"
        if age <= self.stale_seconds:
            return "stale"
        return "disconnected"

    def snapshot_age(self, account_id: str, now: float | None = None) -> float | None:
        session = self.store.load(account_id)
        if session is None or not session.snapshot_at:
            return None
        return max(0.0, self._now(now) - session.snapshot_at)

    # ---------------------------------------------------------- registration
    def register(self, account_id: str, token: str, session_id: str = "", *,
                 terminal: dict[str, Any] | None = None,
                 symbols: list[str] | None = None, now: float | None = None) -> dict[str, Any]:
        """Start (or restart) an EA session.

        A *new* session id means the EA restarted. Anything still queued from the old
        session is dropped as `orphaned` and the snapshot is cleared: whatever the
        previous terminal knew may already be wrong, and merging it into the new
        session is exactly how stale state gets traded on.
        """
        self.require_enabled()
        if not account_id:
            raise BridgeError("account_id is required")
        self.check_token(account_id, token)
        self._check_identity(account_id, terminal or {})
        ts = self._now(now)
        session_id = session_id or f"EA-{uuid.uuid4().hex[:10].upper()}"
        session, restarted, orphaned = self.store.start_session(
            account_id, session_id, ts, dict(terminal or {}), [str(s) for s in (symbols or [])])
        self._log("bridge.register", {"account": account_id, "session": session_id,
                                     "generation": session.generation, "restarted": restarted,
                                     "orphaned": orphaned, "symbols": session.symbols})
        return {
            "session_id": session.session_id,
            "generation": session.generation,
            "read_only": self.read_only,
            "restarted": restarted,
            "server_time": ts,
            "poll_interval_ms": self.poll_interval_ms,
            "fresh_seconds": self.fresh_seconds,
            "stale_seconds": self.stale_seconds,
            "command_ttl_seconds": self.command_ttl_seconds,
            "note": ("previous session state was discarded; send a full snapshot"
                     if restarted else "session started; send a full snapshot"),
        }

    # ----------------------------------------------------------------- poll
    def poll(self, session_id: str, *, snapshot: dict[str, Any] | None = None,
             results: list[dict[str, Any]] | None = None, token: str | None = None,
             now: float | None = None) -> dict[str, Any]:
        """The EA's single round trip: deliver results for the last commands, take new ones."""
        self.require_enabled()
        ts = self._now(now)
        session = next((s for s in self.store.load_all() if s.session_id == session_id), None)
        if session is None:
            raise BridgeError("unknown or superseded session; call register again")
        # A session id alone is not a credential: whoever polls can inject quotes and
        # acknowledge orders, so the token is checked here too (the HTTP route requires it).
        if token is not None:
            self.check_token(session.account_id, token)

        try:
            self._check_identity(session.account_id,
                                 (snapshot or {}).get("account") or {})
        except BridgeError:
            self.store.save_snapshot(session.account_id, session.session_id, {}, 0.0)
            self.store.orphan_pending(session.account_id, "account identity rejected")
            raise

        seen: list[dict[str, Any]] = []
        for raw in results or []:
            seen.append(self._apply_result(session.account_id, raw, ts))

        if snapshot is not None:
            if not self.store.save_snapshot(session.account_id, session.session_id, snapshot, ts):
                raise BridgeError("unknown or superseded session; call register again")
        # Reload before writing: the results above may have changed counters, and a
        # stale object would write them back to their old values.
        session = self.store.load(session.account_id) or session
        session.last_seen = ts
        session.polls += 1
        self.store.save(session)

        if self.read_only:
            self.store.orphan_pending(session.account_id, "read-only bridge policy")
            claimed = []
        else:
            claimed = self.store.claim(session.account_id, ts, self.max_pending, self.ack_grace_seconds)
        self.store.prune(ts)
        expired = self.store.expire_unacked(session.account_id)
        return {
            "session_id": session.session_id,
            "generation": session.generation,
            "server_time": ts,
            "next_poll_ms": self.poll_interval_ms,
            "commands": [c.as_wire() for c in claimed],
            "results": seen,
            "expired_unacked": [c.as_dict() for c in expired[-10:]],
            "health": self.session_health(session.account_id, ts),
        }

    def _apply_result(self, account_id: str, raw: dict[str, Any], ts: float) -> dict[str, Any]:
        command_id = str(raw.get("id") or "")
        outcome, command = self.store.apply_result(
            account_id, command_id, {k: v for k, v in raw.items() if k != "id"}, ts)
        if outcome == "unknown":
            self._log("bridge.unknown_result", {"account": account_id, "id": command_id})
            return {"id": command_id, "accepted": False,
                    "reason": "unknown command id (expired and swept, or never issued)"}
        if outcome == "duplicate":
            return {"id": command_id, "accepted": True, "duplicate": True,
                    "result": command.result if command else None}
        self._log("bridge.result", {"account": account_id, "id": command_id,
                                   "kind": command.kind if command else "",
                                   "ok": (command.result or {}).get("ok") if command else None})
        return {"id": command_id, "accepted": True,
                "result": command.result if command else None}

    # -------------------------------------------------------------- enqueue
    def enqueue(self, account_id: str, kind: str, payload: dict[str, Any], *,
                ttl: float | None = None, now: float | None = None) -> CommandState:
        """Queue a command for the EA. Refuses when no fresh session is listening."""
        self.require_enabled()
        if self.read_only:
            raise BridgeError("read-only bridge refuses all commands")
        session = self.store.load(account_id)
        if session is None:
            raise BridgeError(f"no EA is connected for account {account_id!r}")
        ts = self._now(now)
        health = self.session_health(account_id, ts)
        if health != "connected":
            age = self.age(account_id, ts) or 0.0
            raise BridgeError(
                f"EA for {account_id!r} is {health} (last poll {age:.1f}s ago); "
                "refusing to queue an order nobody is watching")
        live = self.store.live_command_count(account_id)
        if live >= self.max_pending:
            raise BridgeError(f"bridge queue is full ({live} commands); the EA is not keeping up")
        session.seq += 1
        self.store.save(session)
        ttl = self.command_ttl_seconds if ttl is None else float(ttl)
        command = CommandState(id=f"CMD-{uuid.uuid4().hex[:10].upper()}", account_id=account_id,
                               seq=session.seq, kind=kind, payload=dict(payload),
                               created_at=ts, expires_at=ts + ttl)
        self.store.insert_command(command)
        self._log("bridge.enqueue", {"account": account_id, "id": command.id, "kind": kind,
                                     "payload": payload})
        return command

    # --------------------------------------------------------------- result
    def wait_result(self, account_id: str, command_id: str, timeout: float | None = None,
                    poll_seconds: float = 0.02) -> dict[str, Any] | None:
        """Block until the EA acknowledges (or the command dies). None means unknown."""
        deadline = self._now() + (self.order_timeout_seconds if timeout is None else timeout)
        while True:
            command = self.store.command(account_id, command_id)
            if command is None:
                return None
            if command.state == ACKED and command.result is not None:
                return command.result
            if command.state in (EXPIRED, ORPHANED):
                return None
            if self._now() >= deadline:
                return None
            time.sleep(poll_seconds)

    def cancel_pending(self, account_id: str, reason: str = "cancelled") -> int:
        """Drop queued commands (e.g. the kill switch fired before the EA polled)."""
        session = self.store.load(account_id)
        if session is None:
            return 0
        dropped = self.store.orphan_pending(account_id, reason)
        if dropped:
            self._log("bridge.cancel_pending", {"account": account_id, "dropped": dropped,
                                                "reason": reason})
        return dropped

    def forget(self, account_id: str) -> None:
        """Remove an account's session and commands (tests and operator resets)."""
        self.store.forget(account_id)

    # --------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        now = self._now()
        rows = []
        for session in self.store.load_all():
            account_id = session.account_id
            counts = self.store.live_counts(account_id)
            rows.append({
                "account": account_id,
                "session_id": session.session_id,
                "generation": session.generation,
                "health": self.session_health(account_id, now),
                "last_seen_age_seconds": round(self.age(account_id, now) or 0.0, 2),
                "snapshot_age_seconds": (round(self.snapshot_age(account_id, now) or 0.0, 2)
                                         if session.snapshot_at else None),
                "terminal": session.terminal,
                "symbols": session.symbols,
                "positions": len(session.snapshot.get("positions") or []),
                "quotes": sorted((session.snapshot.get("quotes") or {}).keys()),
                "pending": counts.get(PENDING, 0),
                "in_flight": counts.get(DELIVERED, 0),
                "polls": session.polls,
                "duplicate_results": session.duplicates,
                "unknown_results": session.unknown_results,
                "expiries": session.expiries,
                "orphaned_unacked": len(self.store.orphaned(account_id)),
                "last_error": session.last_error,
            })
        orphans = [c.as_dict() for account in self.accounts
                   for c in self.store.orphaned(account)]
        return {
            "enabled": self.enabled,
            "read_only": self.read_only,
            "require_demo_identity": self.require_demo_identity,
            "store": self.store.kind,
            "configured_accounts": sorted(self.accounts),
            "connected_accounts": sorted(r["account"] for r in rows if r["health"] == "connected"),
            "fresh_seconds": self.fresh_seconds,
            "stale_seconds": self.stale_seconds,
            "command_ttl_seconds": self.command_ttl_seconds,
            "sessions": rows,
            "orphaned_commands": orphans[-10:],
            "multi_worker_warning": (None if self.store.kind != "memory" else
                                     "bridge state lives in this process; run one worker or "
                                     "use the shared store before trading through the bridge"),
        }

    def token_fingerprint(self, account_id: str) -> str:
        """Non-reversible id of the configured token, safe to show in a status page."""
        token = self.accounts.get(account_id) or ""
        return hashlib.sha256(token.encode()).hexdigest()[:8] if token else ""
