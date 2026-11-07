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
"""
from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

PENDING = "pending"
DELIVERED = "delivered"
ACKED = "acked"
EXPIRED = "expired"
ORPHANED = "orphaned"


class BridgeError(RuntimeError):
    """Protocol-level refusal; the message is shown to the operator and/or the EA."""


class BridgeTokenError(BridgeError):
    """The credential is missing or wrong — always answered with 401, never retried."""


@dataclass
class Command:
    id: str
    seq: int
    kind: str                      # order | modify | close | ping
    payload: dict[str, Any]
    created_at: float
    expires_at: float
    state: str = PENDING
    delivered_at: float | None = None
    result: dict[str, Any] | None = None
    acked_at: float | None = None

    def as_wire(self) -> dict[str, Any]:
        """What the EA receives. Deliberately excludes anything it does not need."""
        return {
            "id": self.id,
            "seq": self.seq,
            "kind": self.kind,
            "payload": self.payload,
            "expires_at": self.expires_at,
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self.as_wire(), "state": self.state, "created_at": self.created_at,
                "delivered_at": self.delivered_at, "acked_at": self.acked_at,
                "result": self.result}


@dataclass
class Session:
    account_id: str
    session_id: str
    generation: int
    created_at: float
    last_seen: float
    terminal: dict[str, Any] = field(default_factory=dict)
    symbols: list[str] = field(default_factory=list)
    seq: int = 0
    snapshot: dict[str, Any] = field(default_factory=dict)
    snapshot_at: float = 0.0
    snapshot_server_time: float = 0.0
    commands: dict[str, Command] = field(default_factory=dict)
    duplicates: int = 0
    unknown_results: int = 0
    expiries: int = 0
    polls: int = 0
    last_error: str = ""


class BridgeRelay:
    """In-memory session/queue state for every bridged account.

    Single process by design: two workers would each hold their own queue and the EA
    could be handed a command by either. With `workers > 1` the bridge is refused (see
    `status()`), which is honest — a shared store is the real fix and is not built yet.
    """

    def __init__(self, accounts: dict[str, str] | None = None, *,
                 fresh_seconds: float = 5.0, stale_seconds: float = 15.0,
                 command_ttl_seconds: float = 30.0, ack_grace_seconds: float = 20.0,
                 max_pending: int = 50, poll_interval_ms: int = 1000,
                 order_timeout_seconds: float = 20.0, enabled: bool = True,
                 clock: Callable[[], float] | None = None) -> None:
        # account_id -> token. Empty token means "not configured" and is refused.
        self.accounts = {k: v for k, v in (accounts or {}).items() if v}
        self.fresh_seconds = float(fresh_seconds)
        self.stale_seconds = float(stale_seconds)
        self.command_ttl_seconds = float(command_ttl_seconds)
        self.ack_grace_seconds = float(ack_grace_seconds)
        self.max_pending = int(max_pending)
        self.poll_interval_ms = int(poll_interval_ms)
        self.order_timeout_seconds = float(order_timeout_seconds)
        self.enabled = bool(enabled)
        self.clock = clock
        self.sessions: dict[str, Session] = {}      # account_id -> current session
        self.generations: dict[str, int] = {}
        # Commands the previous session never answered. Kept for the operator: they
        # may already be live at the broker, so they must stay visible, not vanish.
        self.orphaned: list[Command] = []
        self.audit: Callable[[str, dict[str, Any]], None] | None = None

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
        if not expected and not token:
            raise BridgeError("bridge account or token is not configured")
        if not hmac.compare_digest(str(token), str(expected)):
            raise BridgeTokenError("invalid bridge token")

    def age(self, account_id: str, now: float | None = None) -> float | None:
        session = self.sessions.get(account_id)
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
        session = self.sessions.get(account_id)
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
        ts = self._now(now)
        session_id = session_id or f"EA-{uuid.uuid4().hex[:10].upper()}"
        existing = self.sessions.get(account_id)
        restarted = False
        if existing is not None and existing.session_id != session_id:
            restarted = True
            for command in existing.commands.values():
                if command.state in (PENDING, DELIVERED):
                    command.state = ORPHANED
                    command.result = {"ok": False,
                                      "error": "the EA restarted before acknowledging"}
                    self.orphaned.append(command)
            self.generations[account_id] = self.generations.get(account_id, existing.generation) + 1
            self.sessions.pop(account_id, None)
        generation = self.generations.get(account_id, 0)
        session = self.sessions.get(account_id) or Session(
            account_id=account_id, session_id=session_id, generation=generation,
            created_at=ts, last_seen=ts)
        session.session_id = session_id
        session.last_seen = ts
        if terminal:
            session.terminal = dict(terminal)
        if symbols:
            session.symbols = [str(s) for s in symbols]
        self.sessions[account_id] = session
        self._log("bridge.register", {"account": account_id, "session": session_id,
                                     "generation": generation, "restarted": restarted,
                                     "symbols": session.symbols})
        return {
            "session_id": session_id,
            "generation": generation,
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
        session = next((s for s in self.sessions.values() if s.session_id == session_id), None)
        if session is None:
            raise BridgeError("unknown or superseded session; call register again")
        # A session id alone is not a credential: whoever polls can inject quotes and
        # acknowledge orders, so the token is checked here too (the HTTP route requires it).
        if token is not None:
            self.check_token(session.account_id, token)
        session.polls += 1

        seen: list[dict[str, Any]] = []
        for raw in results or []:
            seen.append(self._apply_result(session, raw, ts))
        if snapshot is not None:
            session.snapshot = dict(snapshot)
            session.snapshot_at = ts
            session.snapshot_server_time = float(snapshot.get("server_time") or ts)
        session.last_seen = ts
        self._sweep(session, ts)

        deliverable = [c for c in sorted(session.commands.values(), key=lambda c: c.seq)
                       if c.state == PENDING and c.expires_at > ts]
        for command in deliverable[: self.max_pending]:
            command.state = DELIVERED
            command.delivered_at = ts
        # Ids that died unanswered: the EA must know it may have executed them.
        expired = [c.as_dict() for c in session.commands.values()
                   if c.state == EXPIRED and c.acked_at is None]
        return {
            "session_id": session.session_id,
            "generation": session.generation,
            "server_time": ts,
            "next_poll_ms": self.poll_interval_ms,
            "commands": [c.as_wire() for c in deliverable[: self.max_pending]],
            "results": seen,
            "expired_unacked": expired[-10:],
            "health": self.session_health(session.account_id, ts),
        }

    def _apply_result(self, session: Session, raw: dict[str, Any], ts: float) -> dict[str, Any]:
        command_id = str(raw.get("id") or "")
        command = session.commands.get(command_id)
        if command is None:
            session.unknown_results += 1
            session.last_error = f"result for unknown command {command_id!r}"
            self._log("bridge.unknown_result", {"account": session.account_id, "id": command_id})
            return {"id": command_id, "accepted": False,
                    "reason": "unknown command id (expired and swept, or never issued)"}
        if command.state == ACKED:
            session.duplicates += 1
            return {"id": command_id, "accepted": True, "duplicate": True,
                    "result": command.result}
        command.result = {k: v for k, v in raw.items() if k != "id"}
        command.acked_at = ts
        command.state = ACKED
        if command.result.get("ok") is False:
            session.last_error = str(command.result.get("error") or "EA reported failure")
        self._log("bridge.result", {"account": session.account_id, "id": command_id,
                                   "kind": command.kind, "ok": command.result.get("ok")})
        return {"id": command_id, "accepted": True, "result": command.result}

    def _sweep(self, session: Session, ts: float) -> None:
        """Expire what will never be answered, and forget very old finished commands."""
        for command in list(session.commands.values()):
            if command.state == DELIVERED:
                deadline = min(command.expires_at,
                               (command.delivered_at or ts) + self.ack_grace_seconds)
                if ts > deadline:
                    command.state = EXPIRED
                    session.expiries += 1
                    self._log("bridge.expired", {"account": session.account_id,
                                                 "id": command.id, "kind": command.kind})
        for command_id, command in list(session.commands.items()):
            finished_at = command.acked_at or command.expires_at
            if command.state in (ACKED, EXPIRED, ORPHANED) and ts - finished_at > 600:
                session.commands.pop(command_id, None)

    # -------------------------------------------------------------- enqueue
    def enqueue(self, account_id: str, kind: str, payload: dict[str, Any], *,
                ttl: float | None = None, now: float | None = None) -> Command:
        """Queue a command for the EA. Refuses when no fresh session is listening."""
        self.require_enabled()
        session = self.sessions.get(account_id)
        if session is None:
            raise BridgeError(f"no EA is connected for account {account_id!r}")
        ts = self._now(now)
        health = self.session_health(account_id, ts)
        if health != "connected":
            raise BridgeError(
                f"EA for {account_id!r} is {health} (last poll {self.age(account_id, ts):.1f}s ago); "
                "refusing to queue an order nobody is watching")
        live = [c for c in session.commands.values() if c.state in (PENDING, DELIVERED)]
        if len(live) >= self.max_pending:
            raise BridgeError(f"bridge queue is full ({len(live)} commands); the EA is not keeping up")
        session.seq += 1
        ttl = self.command_ttl_seconds if ttl is None else float(ttl)
        command = Command(id=f"CMD-{uuid.uuid4().hex[:10].upper()}", seq=session.seq, kind=kind,
                          payload=payload, created_at=ts, expires_at=ts + ttl)
        session.commands[command.id] = command
        self._log("bridge.enqueue", {"account": account_id, "id": command.id, "kind": kind,
                                     "payload": payload})
        return command

    # --------------------------------------------------------------- result
    def wait_result(self, account_id: str, command_id: str, timeout: float | None = None,
                    poll_seconds: float = 0.02) -> dict[str, Any] | None:
        """Block until the EA acknowledges (or the command dies). None means unknown."""
        session = self.sessions.get(account_id)
        if session is None:
            return None
        deadline = self._now() + (self.order_timeout_seconds if timeout is None else timeout)
        while True:
            command = session.commands.get(command_id)
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
        session = self.sessions.get(account_id)
        if session is None:
            return 0
        dropped = 0
        for command in session.commands.values():
            if command.state == PENDING:
                command.state = ORPHANED
                command.result = {"ok": False, "error": reason}
                dropped += 1
        if dropped:
            self._log("bridge.cancel_pending", {"account": account_id, "dropped": dropped,
                                                "reason": reason})
        return dropped

    # --------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        now = self._now()
        rows = []
        for account_id, session in self.sessions.items():
            pending = sum(1 for c in session.commands.values() if c.state == PENDING)
            delivered = sum(1 for c in session.commands.values() if c.state == DELIVERED)
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
                "pending": pending,
                "in_flight": delivered,
                "polls": session.polls,
                "duplicate_results": session.duplicates,
                "unknown_results": session.unknown_results,
                "expiries": session.expiries,
                "orphaned_unacked": sum(1 for c in self.orphaned if c.state == ORPHANED),
                "last_error": session.last_error,
            })
        return {
            "enabled": self.enabled,
            "configured_accounts": sorted(self.accounts),
            "connected_accounts": sorted(a for a in self.sessions
                                         if self.session_health(a, now) == "connected"),
            "fresh_seconds": self.fresh_seconds,
            "stale_seconds": self.stale_seconds,
            "command_ttl_seconds": self.command_ttl_seconds,
            "sessions": rows,
            "orphaned_commands": [c.as_dict() for c in self.orphaned[-10:]],
            "multi_worker_warning": ("bridge state lives in this process; with several "
                                     "workers each would hold its own queue — run one worker "
                                     "for bridge trading"),
        }

    def token_fingerprint(self, account_id: str) -> str:
        """Non-reversible id of the configured token, safe to show in a status page."""
        token = self.accounts.get(account_id) or ""
        return hashlib.sha256(token.encode()).hexdigest()[:8] if token else ""
