"""Append-only, account-scoped evidence of actions *after* the original order.

An intent is not proof of broker acceptance. A missing/ambiguous order mapping
is represented as ``None`` and must be reconciled by a human, never guessed.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any

from packages.persistence.db import Database


class PositionEventLog:
    def __init__(self, db: Database):
        self.db = db

    def linked_order(self, broker_id: str, ticket: str, account_identity: dict) -> str | None:
        if (account_identity.get("broker_id") != broker_id
                or account_identity.get("workspace_id") != self.db.workspace_id):
            return None
        rows = self.db.query(
            "SELECT o.id,p.payload,p.symbol FROM orders o "
            "JOIN pre_order_snapshots p ON p.order_id=o.id "
            "WHERE o.broker_id=? AND p.broker_id=? AND p.symbol=o.symbol "
            "AND json_extract(CASE WHEN json_valid(o.payload) THEN o.payload ELSE '{}' END, "
            "'$.result.ticket')=?", (broker_id, broker_id, ticket))
        matches: list[str] = []
        for row in rows:
            try:
                frozen = json.loads(row["payload"])
                request = frozen["request"]
                if (frozen.get("account_identity") == account_identity
                        and frozen.get("schema_version") == 1
                        and request.get("broker_id") == broker_id
                        and request.get("symbol") == row["symbol"]):
                    matches.append(str(row["id"]))
            except (ValueError, TypeError, KeyError, AttributeError):
                continue
        return matches[0] if len(matches) == 1 else None

    def append(self, *, broker_id: str, ticket: str, actor: str, kind: str,
               status: str, account_identity: dict[str, str], detail: dict[str, Any]) -> str:
        if (not all(isinstance(v, str) and v.strip() and v == v.strip()
                    for v in (broker_id, ticket, actor, kind, status))
                or not isinstance(account_identity, dict)
                or account_identity.get("broker_id") != broker_id
                or account_identity.get("workspace_id") != self.db.workspace_id):
            raise ValueError("position event identity is unavailable")
        order_id = self.linked_order(broker_id, ticket, account_identity)
        payload = {"schema_version": 1, "account_identity": account_identity,
                   "detail": detail, "order_attribution": "broker_ticket" if order_id else "unresolved"}
        serialized = json.dumps(payload, sort_keys=True, allow_nan=False)
        event_id = "PE-" + uuid.uuid4().hex
        self.db.execute(
            "INSERT INTO position_events"
            "(event_id,order_id,broker_id,ticket,actor,kind,status,created_at,payload) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (event_id, order_id, broker_id, ticket, actor, kind, status, time.time(), serialized))
        return event_id

    def observe_broker(self, *, broker_id: str, ticket: str, account_identity: dict,
                       status: str, detail: dict[str, Any]) -> str | None:
        """Atomically record a broker-position *observation*, not a verified fill.

        Repeated polling of the same discrepancy must not flood immutable events.
        A restoration is recorded only after a previously observed divergence,
        allowing a later recurrence to be recorded again. The writer lock also
        deduplicates concurrent reconciler processes sharing one SQLite file.
        """
        with self.db.cursor() as cur:
            cur.execute("BEGIN IMMEDIATE")
            return self.observe_broker_in_transaction(
                cur, broker_id=broker_id, ticket=ticket,
                account_identity=account_identity, status=status, detail=detail)

    def observe_broker_in_transaction(self, cur: sqlite3.Cursor, *, broker_id: str,
                                      ticket: str, account_identity: dict, status: str,
                                      detail: dict[str, Any]) -> str | None:
        """Append/dedupe under an existing SQLite writer lock (no nested BEGIN)."""
        if (any(not isinstance(value, str) or not value.strip() or value != value.strip()
                for value in (broker_id, ticket)) or not isinstance(account_identity, dict)
                or account_identity.get("broker_id") != broker_id
                or account_identity.get("workspace_id") != self.db.workspace_id
                or status not in ("changed_unverified", "missing_unverified",
                                  "unexpected_unverified", "baseline_restored")
                or not isinstance(detail, dict)):
            raise ValueError("broker observation identity or status is invalid")
        payload = {"schema_version": 1, "account_identity": account_identity,
                   "detail": detail, "order_attribution": "unresolved",
                   "authority": "broker_positions_poll_not_deal_confirmation"}
        serialized = json.dumps(payload, sort_keys=True, allow_nan=False)
        rows = cur.execute(
            "SELECT status,kind,payload FROM position_events "
            "WHERE broker_id=? AND ticket=? ORDER BY rowid", (broker_id, ticket)).fetchall()
        previous = None
        for row in rows:
            try:
                prior = json.loads(row["payload"])
                if prior.get("account_identity") != account_identity:
                    raise ValueError("cross-account position event collision")
            except (TypeError, AttributeError, json.JSONDecodeError) as exc:
                raise ValueError("unverifiable prior position event") from exc
            if row["kind"] == "broker_observation":
                previous = (row["status"], prior.get("detail"))
        if (previous == (status, detail)
                or (previous is None and status == "baseline_restored")
                or (previous is not None and previous[0] == "baseline_restored"
                    and status == "baseline_restored")):
            return None
        event_id = "PE-" + uuid.uuid4().hex
        # No broker I/O occurs inside the writer lock. Unknown origin is
        # explicit even when a matching pre-order ticket happens to exist.
        cur.execute(
            "INSERT INTO position_events"
            "(event_id,order_id,broker_id,ticket,actor,kind,status,created_at,payload) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (event_id, None, broker_id, ticket, "broker-reconciler", "broker_observation",
             status, time.time(), serialized))
        return event_id

    def for_ticket(self, *, broker_id: str, ticket: str, account_identity: dict) -> list[dict]:
        if account_identity.get("broker_id") != broker_id or account_identity.get("workspace_id") != self.db.workspace_id:
            return []
        out = []
        for row in self.db.query(
            "SELECT * FROM position_events WHERE broker_id=? AND ticket=? ORDER BY rowid",
            (broker_id, ticket)):
            try:
                payload = json.loads(row["payload"])
                if payload.get("account_identity") != account_identity:
                    return []  # mixed ownership is not partial evidence
                out.append({**{k: row[k] for k in ("event_id", "order_id", "ticket", "actor", "kind",
                                                   "status", "created_at")}, **payload})
            except (ValueError, TypeError, AttributeError):
                return []
        return out
