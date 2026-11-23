"""Append-only, account-scoped evidence of actions *after* the original order.

An intent is not proof of broker acceptance. A missing/ambiguous order mapping
is represented as ``None`` and must be reconciled by a human, never guessed.
"""
from __future__ import annotations

import json
import hashlib
import math
import sqlite3
import time
import uuid
from typing import Any

from packages.persistence.db import Database


class PositionEventLog:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _account_fingerprint(account_identity: dict[str, str]) -> str:
        required = ("broker_id", "login", "server", "currency", "workspace_id")
        if (not isinstance(account_identity, dict)
                or any(not isinstance(account_identity.get(key), str)
                       or not account_identity[key].strip()
                       for key in required)):
            raise ValueError("modify intent account identity is incomplete")
        canonical = json.dumps({key: account_identity[key] for key in required},
                               sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def reserve_modify(self, *, broker_id: str, ticket: str, idempotency_key: str,
                       account_identity: dict[str, str], detail: dict[str, Any]) -> dict[str, Any]:
        """Durably claim one account/ticket modify before broker I/O.

        Any unresolved intent fences later changes to the same position. The
        caller must reconcile it; an ambiguous request is never retried here.
        """
        if (not all(isinstance(value, str) and value.strip() and value == value.strip()
                    for value in (broker_id, ticket, idempotency_key))
                or not isinstance(account_identity, dict)
                or account_identity.get("broker_id") != broker_id
                or account_identity.get("workspace_id") != self.db.workspace_id
                or not isinstance(detail, dict)):
            raise ValueError("modify intent identity or payload is invalid")
        fingerprint = self._account_fingerprint(account_identity)
        serialized_detail = json.dumps(detail, sort_keys=True, allow_nan=False)
        request_hash = hashlib.sha256(serialized_detail.encode("utf-8")).hexdigest()
        now = time.time()
        with self.db.cursor() as cur:
            cur.execute("BEGIN IMMEDIATE")
            existing = cur.execute(
                "SELECT request_hash,state,updated_at FROM position_modify_intents "
                "WHERE broker_id=? AND account_fingerprint=? AND ticket=? AND idempotency_key=?",
                (broker_id, fingerprint, ticket, idempotency_key)).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise ValueError("modify idempotency key belongs to another request")
                return {"created": False, "state": existing["state"],
                        "age_seconds": max(0.0, now - float(existing["updated_at"])),
                        "account_fingerprint": fingerprint}
            unresolved = cur.execute(
                "SELECT idempotency_key,state,updated_at FROM position_modify_intents "
                "WHERE broker_id=? AND account_fingerprint=? AND ticket=? "
                "AND state IN ('reserved','sending','accepted_unverified','unknown')",
                (broker_id, fingerprint, ticket)).fetchone()
            if unresolved:
                return {"created": False, "blocked": True,
                        "state": unresolved["state"],
                        "age_seconds": max(0.0, now - float(unresolved["updated_at"])),
                        "idempotency_key": unresolved["idempotency_key"],
                        "account_fingerprint": fingerprint}
            cur.execute(
                "INSERT INTO position_modify_intents"
                "(broker_id,account_fingerprint,ticket,idempotency_key,request_hash,request_payload,state,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,'reserved',?,?)",
                (broker_id, fingerprint, ticket, idempotency_key, request_hash,
                 serialized_detail, now, now))
            event_id = "PE-" + uuid.uuid4().hex
            payload = {"schema_version": 1, "account_identity": account_identity,
                       "detail": {**detail, "idempotency_key": idempotency_key},
                       "order_attribution": "unresolved"}
            cur.execute(
                "INSERT INTO position_events"
                "(event_id,order_id,broker_id,ticket,actor,kind,status,created_at,payload) "
                "VALUES(?,NULL,?,?,?,'modify','reserved',?,?)",
                (event_id, broker_id, ticket, "position-manager",
                 now, json.dumps(payload, sort_keys=True, allow_nan=False)))
        return {"created": True, "state": "reserved", "account_fingerprint": fingerprint}

    def transition_modify(self, *, broker_id: str, ticket: str, idempotency_key: str,
                          account_identity: dict[str, str], state: str,
                          detail: dict[str, Any] | None = None) -> bool:
        """Advance an intent projection and append immutable transition evidence."""
        allowed = {
            "reserved": {"sending", "unknown", "rejected", "abandoned"},
            "sending": {"accepted_unverified", "unknown", "rejected", "confirmed"},
            "accepted_unverified": {"confirmed", "unknown"},
            "unknown": {"confirmed", "rejected"},
        }
        if state not in {"sending", "accepted_unverified", "unknown", "rejected",
                         "confirmed", "abandoned"}:
            raise ValueError("modify intent state is invalid")
        if (not isinstance(account_identity, dict)
                or account_identity.get("broker_id") != broker_id
                or account_identity.get("workspace_id") != self.db.workspace_id):
            raise ValueError("modify intent account scope is invalid")
        fingerprint = self._account_fingerprint(account_identity)
        now = time.time()
        safe_detail = detail or {}
        with self.db.cursor() as cur:
            cur.execute("BEGIN IMMEDIATE")
            row = cur.execute(
                "SELECT state FROM position_modify_intents WHERE broker_id=? "
                "AND account_fingerprint=? AND ticket=? AND idempotency_key=?",
                (broker_id, fingerprint, ticket, idempotency_key)).fetchone()
            if row is None:
                raise ValueError("modify intent does not exist")
            current = str(row["state"])
            if state not in allowed.get(current, set()):
                return False
            cur.execute(
                "UPDATE position_modify_intents SET state=?,updated_at=? WHERE broker_id=? "
                "AND account_fingerprint=? AND ticket=? AND idempotency_key=?",
                (state, now, broker_id, fingerprint, ticket, idempotency_key))
            event_id = "PE-" + uuid.uuid4().hex
            payload = {"schema_version": 1, "account_identity": account_identity,
                       "detail": {**safe_detail, "idempotency_key": idempotency_key},
                       "order_attribution": "unresolved"}
            cur.execute(
                "INSERT INTO position_events"
                "(event_id,order_id,broker_id,ticket,actor,kind,status,created_at,payload) "
                "VALUES(?,NULL,?,?,?,'modify',?,?,?)",
                (event_id, broker_id, ticket, "position-manager", state, now,
                 json.dumps(payload, sort_keys=True, allow_nan=False)))
        return True

    def reconcile_modify_intents(self, *, broker_id: str, account_identity: dict[str, str],
                                 positions: list[Any], tick_size_by_symbol: dict[str, float]) -> list[str]:
        """Confirm unresolved intents only when a fresh exact position matches."""
        if (not isinstance(account_identity, dict)
                or account_identity.get("broker_id") != broker_id
                or account_identity.get("workspace_id") != self.db.workspace_id):
            raise ValueError("modify reconciliation account scope is invalid")
        fingerprint = self._account_fingerprint(account_identity)
        by_ticket = {str(pos.ticket): pos for pos in positions
                     if getattr(pos, "broker_id", None) == broker_id}
        rows = self.db.query(
            "SELECT ticket,idempotency_key,state,request_payload FROM position_modify_intents "
            "WHERE broker_id=? AND account_fingerprint=? "
            "AND state IN ('sending','accepted_unverified','unknown')",
            (broker_id, fingerprint))
        confirmed: list[str] = []
        for row in rows:
            pos = by_ticket.get(str(row["ticket"]))
            if pos is None:
                continue
            try:
                request = json.loads(row["request_payload"])
                sl = request["sl"]
                tp = request.get("tp")
                before_tp = request.get("before_tp")
                tolerance = float(tick_size_by_symbol.get(pos.symbol, 0.0)) * 1e-6
                sl_match = (type(sl) in (int, float) and tolerance > 0
                            and abs(float(pos.sl) - float(sl)) <= tolerance)
                tp_target = before_tp if tp is None else tp
                tp_match = (type(tp_target) in (int, float)
                            and abs(float(pos.tp) - float(tp_target)) <= tolerance)
                if not (sl_match and tp_match):
                    continue
            except (ValueError, TypeError, KeyError, AttributeError):
                continue
            changed = self.transition_modify(
                broker_id=broker_id, ticket=str(row["ticket"]),
                idempotency_key=str(row["idempotency_key"]),
                account_identity=account_identity, state="confirmed",
                detail={"broker_sl": pos.sl, "broker_tp": pos.tp,
                        "confirmation_source": "fresh_broker_position_reconciliation"})
            if changed:
                confirmed.append(str(row["ticket"]))
        return confirmed

    def confirmed_modify_matches_in_transaction(self, cur: sqlite3.Cursor, *,
                                               broker_id: str, ticket: str,
                                               account_identity: dict[str, str],
                                               before: dict[str, Any],
                                               observed: dict[str, Any]) -> bool:
        """Check whether only SL/TP changed to the latest confirmed intent."""
        if (not isinstance(account_identity, dict)
                or account_identity.get("broker_id") != broker_id
                or account_identity.get("workspace_id") != self.db.workspace_id):
            return False
        fingerprint = self._account_fingerprint(account_identity)
        try:
            changed = {key for key in before if before.get(key) != observed.get(key)}
            if not changed or not changed.issubset({"sl", "tp"}):
                return False

            rows = cur.execute(
                "SELECT state,request_payload FROM position_modify_intents "
                "WHERE broker_id=? AND account_fingerprint=? AND ticket=? "
                "ORDER BY created_at ASC,rowid ASC", (broker_id, fingerprint, ticket)).fetchall()
            if not rows:
                return False

            # A management cycle can confirm more than one strictly improving
            # stop before the next snapshot is taken. Reconcile the ordered
            # before/after chain from the stored baseline instead of comparing
            # only with the latest intent's intermediate before-state.
            expected_sl = float(before["sl"])
            expected_tp = float(before["tp"])
            started = False
            final_tolerance = 0.0
            for row in rows:
                if row["state"] != "confirmed":
                    if started:
                        return False
                    continue
                request = json.loads(row["request_payload"])
                if request.get("symbol") != observed.get("symbol"):
                    if started:
                        return False
                    continue
                tick_size = float(request.get("tick_size", 0.0))
                tolerance = tick_size * 1e-6
                if tolerance <= 0 or not math.isfinite(tolerance):
                    if started:
                        return False
                    continue
                request_before_sl = float(request["before_sl"])
                request_before_tp = float(request["before_tp"])
                links_to_chain = (abs(expected_sl - request_before_sl) <= tolerance
                                  and abs(expected_tp - request_before_tp) <= tolerance)
                if not started:
                    if not links_to_chain:
                        continue
                    started = True
                elif not links_to_chain:
                    return False

                expected_sl = float(request["sl"])
                expected_tp = (request_before_tp if request.get("tp") is None
                               else float(request["tp"]))
                final_tolerance = tolerance

            if not started or final_tolerance <= 0:
                return False
            return (abs(float(observed["sl"]) - expected_sl) <= final_tolerance
                    and abs(float(observed["tp"]) - expected_tp) <= final_tolerance)
        except (ValueError, TypeError, KeyError, AttributeError):
            return False

    def confirmed_modify_matches(self, *, broker_id: str, ticket: str,
                                  account_identity: dict[str, str],
                                  before: dict[str, Any], observed: dict[str, Any]) -> bool:
        with self.db.cursor() as cur:
            return self.confirmed_modify_matches_in_transaction(
                cur, broker_id=broker_id, ticket=ticket,
                account_identity=account_identity, before=before, observed=observed)

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
