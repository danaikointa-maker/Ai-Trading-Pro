"""Where the bridge keeps its state: one process's memory, or a shared SQLite file.

The relay's rules (one delivery, nothing stale) only hold if every process agrees on
the same state. With `uvicorn --workers N` the EA's poll can land on any worker, so a
per-process queue means an order queued by the leader is never delivered — and an EA
that re-registers on whichever worker answered gets its queue silently abandoned.

Both stores implement the same interface, so the protocol logic exists once and the
tests run every rule against both. The SQLite store is the one the runtime uses; the
memory store stays for unit tests and for the "no database" case.

Atomicity matters only in the shared store, and it is done with conditional UPDATEs:
`claim` marks rows delivered one at a time and only counts the ones *it* changed, so two
workers polling at the same instant can never both hand over the same command.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import Any, Protocol

from packages.persistence.db import Database

PENDING = "pending"
DELIVERED = "delivered"
ACKED = "acked"
EXPIRED = "expired"
ORPHANED = "orphaned"


@dataclass
class SessionState:
    account_id: str
    session_id: str = ""
    generation: int = 0
    created_at: float = 0.0
    last_seen: float = 0.0
    terminal: dict[str, Any] = field(default_factory=dict)
    symbols: list[str] = field(default_factory=list)
    seq: int = 0
    snapshot: dict[str, Any] = field(default_factory=dict)
    snapshot_at: float = 0.0
    polls: int = 0
    duplicates: int = 0
    unknown_results: int = 0
    expiries: int = 0
    last_error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id, "session_id": self.session_id,
            "generation": self.generation, "created_at": self.created_at,
            "last_seen": self.last_seen, "terminal": self.terminal,
            "symbols": self.symbols, "polls": self.polls, "duplicates": self.duplicates,
            "unknown_results": self.unknown_results, "expiries": self.expiries,
            "last_error": self.last_error, "snapshot_at": self.snapshot_at,
        }


@dataclass
class CommandState:
    id: str
    account_id: str
    seq: int
    kind: str
    payload: dict[str, Any]
    created_at: float
    expires_at: float
    state: str = PENDING
    delivered_at: float | None = None
    acked_at: float | None = None
    result: dict[str, Any] | None = None

    def as_wire(self) -> dict[str, Any]:
        return {"id": self.id, "seq": self.seq, "kind": self.kind,
                "payload": self.payload, "expires_at": self.expires_at}

    def as_dict(self) -> dict[str, Any]:
        return {**self.as_wire(), "state": self.state, "created_at": self.created_at,
                "delivered_at": self.delivered_at, "acked_at": self.acked_at,
                "result": self.result}


class BridgeStore(Protocol):
    """The persistence the relay needs. Nothing here validates — that is the relay."""

    kind: str

    def load(self, account_id: str) -> SessionState | None: ...
    def load_all(self) -> list[SessionState]: ...
    def save(self, session: SessionState) -> None: ...
    def start_session(self, account_id: str, session_id: str, now: float,
                      terminal: dict[str, Any], symbols: list[str]) -> tuple[SessionState, bool, int]:
        """Returns (session, restarted, orphaned_count)."""
    def save_snapshot(self, account_id: str, session_id: str, snapshot: dict[str, Any],
                      now: float) -> bool: ...
    def insert_command(self, command: CommandState) -> None: ...
    def live_command_count(self, account_id: str) -> int: ...
    def live_counts(self, account_id: str) -> dict[str, int]: ...
    def orphan_pending(self, account_id: str, reason: str) -> int: ...
    def command(self, account_id: str, command_id: str) -> CommandState | None: ...
    def commands(self, account_id: str, limit: int = 200) -> list[CommandState]: ...
    def claim(self, account_id: str, now: float, limit: int, ack_grace: float) -> list[CommandState]: ...
    def sweep(self, account_id: str, now: float, ack_grace: float) -> int: ...
    def apply_result(self, account_id: str, command_id: str, result: dict[str, Any],
                     now: float) -> tuple[str, CommandState | None]: ...
    def set_state(self, account_id: str, command_id: str, state: str,
                  result: dict[str, Any] | None = None) -> bool: ...
    def expire_unacked(self, account_id: str) -> list[CommandState]: ...
    def orphaned(self, account_id: str, limit: int = 10) -> list[CommandState]: ...
    def forget(self, account_id: str) -> None: ...
    def prune(self, now: float, older_than: float = 600.0) -> None: ...


def _deadline(command_delivered_at: float | None, expires_at: float, ack_grace: float) -> float:
    if command_delivered_at is None:
        return expires_at
    return min(expires_at, command_delivered_at + ack_grace)


class MemoryStore:
    """Process-local state — correct for one worker, and what the unit tests use."""

    kind = "memory"

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._commands: dict[str, dict[str, CommandState]] = {}
        self._lock = threading.RLock()

    def load(self, account_id: str) -> SessionState | None:
        with self._lock:
            session = self._sessions.get(account_id)
            return SessionState(**session.as_dict()) if session else None

    def load_all(self) -> list[SessionState]:
        with self._lock:
            return [SessionState(**s.as_dict()) for s in self._sessions.values()]

    def save(self, session: SessionState) -> None:
        with self._lock:
            fresh = SessionState(**session.as_dict())
            existing = self._sessions.get(session.account_id)
            if existing is not None:  # counters belong to the atomic updates
                fresh.duplicates = existing.duplicates
                fresh.unknown_results = existing.unknown_results
                fresh.expiries = existing.expiries
            self._sessions[session.account_id] = fresh

    def start_session(self, account_id: str, session_id: str, now: float,
                      terminal: dict[str, Any], symbols: list[str]) -> tuple[SessionState, bool, int]:
        with self._lock:
            existing = self._sessions.get(account_id)
            restarted = bool(existing and existing.session_id != session_id)
            orphaned = 0
            generation = existing.generation if existing else 0
            if restarted:
                for command in self._commands.get(account_id, {}).values():
                    if command.state in (PENDING, DELIVERED):
                        command.state = ORPHANED
                        command.result = {"ok": False,
                                          "error": "the EA restarted before acknowledging"}
                        orphaned += 1
                generation += 1
                existing = None
            session = existing or SessionState(account_id=account_id, created_at=now,
                                               last_seen=now, generation=generation)
            session.session_id = session_id
            session.last_seen = now
            session.generation = generation
            if terminal:
                session.terminal = dict(terminal)
            if symbols:
                session.symbols = [str(s) for s in symbols]
            if restarted:
                # the new terminal has its own truth; merging the old snapshot is the bug
                session.snapshot = {}
                session.snapshot_at = 0.0
            self._sessions[account_id] = session
            self._commands.setdefault(account_id, {})
            return SessionState(**session.as_dict()), restarted, orphaned

    def save_snapshot(self, account_id: str, session_id: str, snapshot: dict[str, Any],
                      now: float) -> bool:
        with self._lock:
            session = self._sessions.get(account_id)
            if session is None or session.session_id != session_id:
                return False
            session.snapshot = dict(snapshot)
            session.snapshot_at = now
            return True

    def insert_command(self, command: CommandState) -> None:
        with self._lock:
            self._commands.setdefault(command.account_id, {})[command.id] = command

    def live_command_count(self, account_id: str) -> int:
        with self._lock:
            return sum(1 for c in self._commands.get(account_id, {}).values()
                       if c.state in (PENDING, DELIVERED))

    def live_counts(self, account_id: str) -> dict[str, int]:
        with self._lock:
            counts = {PENDING: 0, DELIVERED: 0}
            for command in self._commands.get(account_id, {}).values():
                if command.state in counts:
                    counts[command.state] += 1
            return counts

    def orphan_pending(self, account_id: str, reason: str) -> int:
        with self._lock:
            dropped = 0
            for command in self._commands.get(account_id, {}).values():
                if command.state == PENDING:
                    command.state = ORPHANED
                    command.result = {"ok": False, "error": reason}
                    dropped += 1
            return dropped

    def command(self, account_id: str, command_id: str) -> CommandState | None:
        with self._lock:
            command = self._commands.get(account_id, {}).get(command_id)
            return CommandState(**command.__dict__) if command else None

    def commands(self, account_id: str, limit: int = 200) -> list[CommandState]:
        with self._lock:
            rows = sorted(self._commands.get(account_id, {}).values(), key=lambda c: c.seq)
            return [CommandState(**c.__dict__) for c in rows[-limit:]]

    def claim(self, account_id: str, now: float, limit: int, ack_grace: float) -> list[CommandState]:
        with self._lock:
            self.sweep(account_id, now, ack_grace)
            claimed = []
            for command in sorted(self._commands.get(account_id, {}).values(),
                                  key=lambda c: c.seq):
                if len(claimed) >= limit:
                    break
                if command.state == PENDING and command.expires_at > now:
                    command.state = DELIVERED
                    command.delivered_at = now
                    claimed.append(CommandState(**command.__dict__))
            return claimed

    def sweep(self, account_id: str, now: float, ack_grace: float) -> int:
        with self._lock:
            expired = 0
            session = self._sessions.get(account_id)
            for command in self._commands.get(account_id, {}).values():
                if command.state in (PENDING, DELIVERED) and now > _deadline(
                        command.delivered_at, command.expires_at, ack_grace):
                    command.state = EXPIRED
                    expired += 1
            if expired and session:
                session.expiries += expired
            return expired

    def apply_result(self, account_id: str, command_id: str, result: dict[str, Any],
                     now: float) -> tuple[str, CommandState | None]:
        with self._lock:
            command = self._commands.get(account_id, {}).get(command_id)
            session = self._sessions.get(account_id)
            if command is None:
                if session:
                    session.unknown_results += 1
                    session.last_error = f"result for unknown command {command_id!r}"
                return "unknown", None
            if command.state == ACKED:
                if session:
                    session.duplicates += 1
                return "duplicate", CommandState(**command.__dict__)
            command.result = dict(result)
            command.acked_at = now
            command.state = ACKED
            if session and result.get("ok") is False:
                session.last_error = str(result.get("error") or "EA reported failure")
            return "acked", CommandState(**command.__dict__)

    def set_state(self, account_id: str, command_id: str, state: str,
                  result: dict[str, Any] | None = None) -> bool:
        with self._lock:
            command = self._commands.get(account_id, {}).get(command_id)
            if command is None:
                return False
            command.state = state
            if result is not None:
                command.result = dict(result)
            return True

    def expire_unacked(self, account_id: str) -> list[CommandState]:
        with self._lock:
            return [CommandState(**c.__dict__) for c in self._commands.get(account_id, {}).values()
                    if c.state == EXPIRED and c.acked_at is None]

    def orphaned(self, account_id: str, limit: int = 10) -> list[CommandState]:
        with self._lock:
            rows = [CommandState(**c.__dict__) for c in self._commands.get(account_id, {}).values()
                    if c.state == ORPHANED]
            return rows[-limit:]

    def forget(self, account_id: str) -> None:
        with self._lock:
            self._sessions.pop(account_id, None)
            self._commands.pop(account_id, None)

    def prune(self, now: float, older_than: float = 600.0) -> None:
        with self._lock:
            for account_id, commands in self._commands.items():
                for command_id, command in list(commands.items()):
                    finished = command.acked_at or command.expires_at
                    if command.state in (ACKED, EXPIRED, ORPHANED) and now - finished > older_than:
                        commands.pop(command_id, None)


class SqliteStore:
    """Shared state in the app database, so any worker can accept the EA's poll.

    Claims are conditional UPDATEs: whoever changes the row owns the delivery, so two
    workers answering at the same moment still produce exactly one execution.
    """

    kind = "sqlite"

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------ sessions
    @staticmethod
    def _session(row: Any) -> SessionState:
        keys = row.keys()
        return SessionState(
            account_id=row["account_id"], session_id=row["session_id"] or "",
            generation=int(row["generation"] or 0), created_at=float(row["created_at"] or 0),
            last_seen=float(row["last_seen"] or 0),
            terminal=json.loads(row["terminal"] or "{}"),
            symbols=json.loads(row["symbols"] or "[]"),
            seq=int(row["seq"] or 0),
            snapshot=json.loads(row["snapshot"] or "{}"),
            snapshot_at=float(row["snapshot_at"] or 0),
            polls=int(row["polls"] or 0), duplicates=int(row["duplicates"] or 0),
            unknown_results=int(row["unknown_results"] or 0),
            expiries=int(row["expiries"] or 0),
            last_error=row["last_error"] or "" if "last_error" in keys else "",
        )

    @staticmethod
    def _command(row: Any) -> CommandState:
        return CommandState(
            id=row["id"], account_id=row["account_id"], seq=int(row["seq"]),
            kind=row["kind"], payload=json.loads(row["payload"] or "{}"),
            created_at=float(row["created_at"]), expires_at=float(row["expires_at"]),
            state=row["state"], delivered_at=row["delivered_at"], acked_at=row["acked_at"],
            result=json.loads(row["result"]) if row["result"] else None,
        )

    def load(self, account_id: str) -> SessionState | None:
        row = self.db.query_one("SELECT * FROM bridge_sessions WHERE account_id = ?",
                                (account_id,))
        return self._session(row) if row else None

    def load_all(self) -> list[SessionState]:
        return [self._session(row) for row in
                self.db.query("SELECT * FROM bridge_sessions ORDER BY account_id")]

    def save(self, session: SessionState) -> None:
        # Counters (duplicates/unknown_results/expiries) are incremented by the atomic
        # updates above and deliberately NOT overwritten here: a caller holding a
        # session object from before those updates would otherwise erase them.
        self.db.execute(
            "INSERT INTO bridge_sessions(account_id, session_id, generation, created_at, "
            "last_seen, terminal, symbols, seq, snapshot, snapshot_at, polls, duplicates, "
            "unknown_results, expiries, last_error) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(account_id) DO UPDATE SET session_id=excluded.session_id, "
            "generation=excluded.generation, last_seen=excluded.last_seen, "
            "terminal=excluded.terminal, symbols=excluded.symbols, seq=excluded.seq, "
            "snapshot=excluded.snapshot, snapshot_at=excluded.snapshot_at, "
            "polls=excluded.polls, last_error=excluded.last_error",
            (session.account_id, session.session_id, session.generation, session.created_at,
             session.last_seen, json.dumps(session.terminal, default=str),
             json.dumps(session.symbols), session.seq, json.dumps(session.snapshot, default=str),
             session.snapshot_at, session.polls, session.duplicates,
             session.unknown_results, session.expiries, session.last_error),
        )

    def start_session(self, account_id: str, session_id: str, now: float,
                      terminal: dict[str, Any], symbols: list[str]) -> tuple[SessionState, bool, int]:
        existing = self.load(account_id)
        restarted = bool(existing and existing.session_id != session_id)
        orphaned = 0
        generation = existing.generation if existing else 0
        if restarted:
            orphaned = self.db.execute(
                "UPDATE bridge_commands SET state = ?, result = ? "
                "WHERE account_id = ? AND state IN (?, ?)",
                (ORPHANED, json.dumps({"ok": False,
                                       "error": "the EA restarted before acknowledging"}),
                 account_id, PENDING, DELIVERED))
            generation += 1
            existing = None
        session = existing or SessionState(account_id=account_id, created_at=now,
                                          last_seen=now, generation=generation)
        session.session_id = session_id
        session.last_seen = now
        session.generation = generation
        if terminal:
            session.terminal = dict(terminal)
        if symbols:
            session.symbols = [str(s) for s in symbols]
        if restarted:
            session.snapshot = {}
            session.snapshot_at = 0.0
        self.save(session)
        return self.load(account_id) or session, restarted, orphaned

    def save_snapshot(self, account_id: str, session_id: str, snapshot: dict[str, Any],
                      now: float) -> bool:
        changed = self.db.execute(
            "UPDATE bridge_sessions SET snapshot = ?, snapshot_at = ?, last_seen = ? "
            "WHERE account_id = ? AND session_id = ?",
            (json.dumps(snapshot, default=str), now, now, account_id, session_id))
        return changed > 0

    # ------------------------------------------------------------ commands
    def insert_command(self, command: CommandState) -> None:
        self.db.execute(
            "INSERT INTO bridge_commands(id, account_id, seq, kind, payload, created_at, "
            "expires_at, state) VALUES(?,?,?,?,?,?,?,?)",
            (command.id, command.account_id, command.seq, command.kind,
             json.dumps(command.payload, default=str), command.created_at,
             command.expires_at, command.state))

    def live_command_count(self, account_id: str) -> int:
        row = self.db.query_one(
            "SELECT COUNT(*) AS n FROM bridge_commands WHERE account_id = ? AND state IN (?,?)",
            (account_id, PENDING, DELIVERED))
        return int(row["n"]) if row else 0

    def live_counts(self, account_id: str) -> dict[str, int]:
        rows = self.db.query(
            "SELECT state, COUNT(*) AS n FROM bridge_commands WHERE account_id = ? "
            "AND state IN (?, ?) GROUP BY state", (account_id, PENDING, DELIVERED))
        counts = {PENDING: 0, DELIVERED: 0}
        for row in rows:
            counts[row["state"]] = int(row["n"])
        return counts

    def orphan_pending(self, account_id: str, reason: str) -> int:
        return self.db.execute(
            "UPDATE bridge_commands SET state = ?, result = ? "
            "WHERE account_id = ? AND state = ?",
            (ORPHANED, json.dumps({"ok": False, "error": reason}), account_id, PENDING))

    def command(self, account_id: str, command_id: str) -> CommandState | None:
        row = self.db.query_one(
            "SELECT * FROM bridge_commands WHERE account_id = ? AND id = ?",
            (account_id, command_id))
        return self._command(row) if row else None

    def commands(self, account_id: str, limit: int = 200) -> list[CommandState]:
        rows = self.db.query(
            "SELECT * FROM bridge_commands WHERE account_id = ? ORDER BY seq DESC LIMIT ?",
            (account_id, int(limit)))
        return [self._command(row) for row in reversed(rows)]

    def claim(self, account_id: str, now: float, limit: int, ack_grace: float) -> list[CommandState]:
        self.sweep(account_id, now, ack_grace)
        candidates = self.db.query(
            "SELECT id FROM bridge_commands WHERE account_id = ? AND state = ? AND expires_at > ? "
            "ORDER BY seq LIMIT ?", (account_id, PENDING, now, int(limit)))
        claimed: list[CommandState] = []
        for row in candidates:
            # only the process that actually changed the row may hand it to the EA
            changed = self.db.execute(
                "UPDATE bridge_commands SET state = ?, delivered_at = ? "
                "WHERE id = ? AND state = ?", (DELIVERED, now, row["id"], PENDING))
            if changed != 1:
                continue
            command = self.command(account_id, row["id"])
            if command is not None:
                claimed.append(command)
        return claimed

    def sweep(self, account_id: str, now: float, ack_grace: float) -> int:
        expired = self.db.execute(
            "UPDATE bridge_commands SET state = ? WHERE account_id = ? AND state IN (?, ?) "
            "AND (CASE WHEN delivered_at IS NOT NULL AND delivered_at + ? < expires_at "
            "THEN delivered_at + ? ELSE expires_at END) < ?",
            (EXPIRED, account_id, PENDING, DELIVERED, ack_grace, ack_grace, now))
        if expired:
            self.db.execute(
                "UPDATE bridge_sessions SET expiries = expiries + ? WHERE account_id = ?",
                (expired, account_id))
        return expired

    def apply_result(self, account_id: str, command_id: str, result: dict[str, Any],
                     now: float) -> tuple[str, CommandState | None]:
        payload = json.dumps(result, default=str)
        changed = self.db.execute(
            "UPDATE bridge_commands SET state = ?, result = ?, acked_at = ? "
            "WHERE account_id = ? AND id = ? AND state IN (?, ?, ?)",
            (ACKED, payload, now, account_id, command_id, PENDING, DELIVERED, EXPIRED))
        command = self.command(account_id, command_id)
        if command is None:
            self.db.execute(
                "UPDATE bridge_sessions SET unknown_results = unknown_results + 1, "
                "last_error = ? WHERE account_id = ?",
                (f"result for unknown command {command_id!r}", account_id))
            return "unknown", None
        if changed != 1:
            self.db.execute(
                "UPDATE bridge_sessions SET duplicates = duplicates + 1 WHERE account_id = ?",
                (account_id,))
            return "duplicate", command
        if result.get("ok") is False:
            self.db.execute("UPDATE bridge_sessions SET last_error = ? WHERE account_id = ?",
                            (str(result.get("error") or "EA reported failure"), account_id))
        return "acked", command

    def set_state(self, account_id: str, command_id: str, state: str,
                  result: dict[str, Any] | None = None) -> bool:
        if result is None:
            return self.db.execute(
                "UPDATE bridge_commands SET state = ? WHERE account_id = ? AND id = ?",
                (state, account_id, command_id)) > 0
        return self.db.execute(
            "UPDATE bridge_commands SET state = ?, result = ? WHERE account_id = ? AND id = ?",
            (state, json.dumps(result, default=str), account_id, command_id)) > 0

    def expire_unacked(self, account_id: str) -> list[CommandState]:
        return [self._command(row) for row in self.db.query(
            "SELECT * FROM bridge_commands WHERE account_id = ? AND state = ? "
            "AND acked_at IS NULL ORDER BY seq", (account_id, EXPIRED))]

    def orphaned(self, account_id: str, limit: int = 10) -> list[CommandState]:
        rows = self.db.query(
            "SELECT * FROM bridge_commands WHERE account_id = ? AND state = ? "
            "ORDER BY seq DESC LIMIT ?", (account_id, ORPHANED, int(limit)))
        return [self._command(row) for row in reversed(rows)]

    def forget(self, account_id: str) -> None:
        self.db.execute("DELETE FROM bridge_commands WHERE account_id = ?", (account_id,))
        self.db.execute("DELETE FROM bridge_sessions WHERE account_id = ?", (account_id,))

    def prune(self, now: float, older_than: float = 600.0) -> None:
        self.db.execute(
            "DELETE FROM bridge_commands WHERE state IN (?, ?, ?) AND "
            "(CASE WHEN acked_at IS NOT NULL THEN acked_at ELSE expires_at END) < ?",
            (ACKED, EXPIRED, ORPHANED, now - older_than))


def build_store(db: Database | None, *, prefer_memory: bool = False) -> BridgeStore:
    """Shared store when a database exists — the multi-worker case must not be silent."""
    if db is not None and not prefer_memory:
        return SqliteStore(db)
    return MemoryStore()
