"""Append-only, account-scoped evidence of actions *after* the original order.

An intent is not proof of broker acceptance. A missing/ambiguous order mapping
is represented as ``None`` and must be reconciled by a human, never guessed.
"""
from __future__ import annotations

import json
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
