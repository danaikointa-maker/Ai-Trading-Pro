"""Execution gateway: idempotent order submission, verification, reconciliation.

Local safety boundaries
-----------------------
* one retained idempotency key -> at most one adapter send attempt in this database;
* fills are checked against positions when verify_after_send is enabled;
* a broker that is not connected can never receive an order;
* every state transition is written to the audit log.

This is not broker-side exactly-once execution. A new key, a restored/deleted
database, or ambiguous broker history still needs separate operator reconciliation.
"""
from __future__ import annotations

import json
import math
import time
import uuid
from typing import Any

from integrations.brokers.base import BrokerAdapter, BrokerError
from packages.persistence.db import Database
from packages.shared_schemas.models import (
    Direction,
    Health,
    OrderRequest,
    OrderResult,
    OrderState,
    Position,
    TradeMode,
    TradeRecord,
)
from packages.shared_schemas.settings import Settings


class ExecutionGateway:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        ex = settings.execution
        # kept for visibility; submit() never resends (see the docstring there)
        self.max_retries = int(ex.get("max_retries", 0))
        self.verify_after_send = bool(ex.get("verify_after_send", True))
        self.order_timeout = float(ex.get("order_timeout_seconds", 20))

    # ----------------------------------------------------------- idempotency
    @staticmethod
    def make_key(request: OrderRequest) -> str:
        if request.idempotency_key:
            return request.idempotency_key
        raw = f"{request.broker_id or ''}:{request.symbol}:{request.side.value}:{request.volume}:{request.signal_id or ''}"
        return "idem-" + uuid.uuid5(uuid.NAMESPACE_URL, raw).hex[:20]

    def _existing(self, key: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM orders WHERE idempotency_key = ?", (key,))
        if not row:
            return None
        try:
            payload = json.loads(row["payload"])
            stored = OrderRequest(**payload["request"])
            if stored.broker_id != row["broker_id"] or stored.idempotency_key != key:
                raise ValueError("record identity mismatch")
        except (ValueError, TypeError, KeyError) as exc:
            raise BrokerError("idempotency record invalid; manual reconciliation required") from exc
        return {"id": row["id"], "state": row["state"], "result": payload.get("result"),
                "request": stored}

    def _replay(self, adapter: BrokerAdapter, request: OrderRequest,
                existing: dict[str, Any], actor: str) -> OrderResult:
        if existing["request"].model_dump() != request.model_dump():
            raise BrokerError("idempotency key already belongs to a different request")
        result = None
        if existing["result"] is not None:
            try:
                result = OrderResult(**existing["result"])
                if (result.order_id != existing["id"] or result.idempotency_key != request.idempotency_key
                        or result.status.value != existing["state"]):
                    raise ValueError("result identity mismatch")
            except (ValueError, TypeError) as exc:
                raise BrokerError("idempotency result invalid; manual reconciliation required") from exc
        if existing["state"] not in (OrderState.filled.value, OrderState.closed.value,
                                     OrderState.cancelled.value, OrderState.rejected.value):
            recovered = self._verify_existing(adapter, request.idempotency_key)
            if recovered is not None:
                return recovered
        self.db.audit(actor, "order.idempotent_hit", {"key": request.idempotency_key})
        return result or OrderResult(
            order_id=existing["id"], idempotency_key=request.idempotency_key,
            status=OrderState.pending, message="order unresolved; not resent — manual reconciliation required",
        )

    # ---------------------------------------------------------------- submit
    def submit(self, adapter: BrokerAdapter, request: OrderRequest, actor: str = "system") -> OrderResult:
        health = adapter.health()
        if health not in (Health.connected, Health.degraded):
            raise BrokerError(f"refusing to send: broker {adapter.id} is {health.value}")
        request = request.model_copy(update={"broker_id": adapter.id})
        key = self.make_key(request)
        request = request.model_copy(update={"idempotency_key": key})

        existing = self._existing(key)
        if existing:
            return self._replay(adapter, request, existing, actor)

        order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        claimed = self.db.execute(
            "INSERT INTO orders(id, created_at, idempotency_key, state, broker_id, symbol, payload) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(idempotency_key) DO NOTHING",
            (order_id, time.time(), key, OrderState.pending.value, adapter.id, request.symbol,
             json.dumps({"request": request.model_dump(), "actor": actor}, default=str)),
        )
        if not claimed:
            existing = self._existing(key)
            if existing is None:
                raise BrokerError("idempotency claim disappeared; refusing to send")
            return self._replay(adapter, request, existing, actor)
        self.db.audit(actor, "order.submit", request.model_dump())

        # One attempt only. A transport error does not prove the order was not
        # executed, so resending could duplicate the position — the operator (or
        # the reconciler) resolves it instead of the gateway guessing.
        try:
            result = adapter.order_send(request, ticket_hint="")
            result.order_id = order_id
            result.idempotency_key = key
            if self.verify_after_send and result.status == OrderState.filled:
                result.verified = self._verify_fill(adapter, result)
                if not result.verified:
                    result.message += " | fill not visible in positions (will reconcile)"
            self._persist_result(order_id, result, request)
            self.db.audit(actor, "order.result", result.model_dump())
            return result
        except BrokerError as exc:
            last_error = str(exc)
            self.db.audit(actor, "order.error", {"error": last_error, "retcode": exc.retcode,
                                                 "resent": False})
        except Exception as exc:  # noqa: BLE001
            last_error = f"unexpected: {exc}"
            self.db.audit(actor, "order.error", {"error": last_error, "resent": False})

        recovered = self._verify_existing(adapter, key)
        if recovered is not None:
            self.db.audit(actor, "order.recovered", {"key": key, "ticket": recovered.ticket})
            return recovered

        result = OrderResult(
            order_id=order_id, idempotency_key=key, status=OrderState.pending,
            message=(f"order not confirmed: {last_error} | not resent automatically — "
                     f"manual reconciliation required; do not retry with a new key"),
            created_at=time.time(),
        )
        self._persist_result(order_id, result, request)
        return result

    def _persist_result(self, order_id: str, result: OrderResult, request: OrderRequest) -> None:
        self.db.execute(
            "UPDATE orders SET state=?, payload=? WHERE id=?",
            (result.status.value, json.dumps({"request": request.model_dump(), "result": result.model_dump()},
                                             default=str), order_id),
        )

    def _verify_fill(self, adapter: BrokerAdapter, result: OrderResult) -> bool:
        """The fill only counts once the broker reports the position."""
        if not result.ticket:
            return False
        try:
            return any(p.ticket == result.ticket for p in adapter.positions())
        except Exception:  # noqa: BLE001
            return False

    def _verify_existing(self, adapter: BrokerAdapter, key: str) -> OrderResult | None:
        """Reconcile an order whose send outcome was unknown (timeout/network)."""
        try:
            positions = adapter.positions()
        except Exception:  # noqa: BLE001
            return None
        row = self.db.query_one("SELECT * FROM orders WHERE idempotency_key = ?", (key,))
        if not row:
            return None
        try:
            payload = json.loads(row["payload"] or "{}")
        except json.JSONDecodeError:
            return None
        request = payload.get("request") or {}
        signal_id = request.get("signal_id")
        matches = [pos for pos in positions
                   if signal_id and pos.signal_id == signal_id
                   and pos.broker_id == adapter.id == row["broker_id"]
                   and pos.symbol == request.get("symbol")
                   and pos.direction == (Direction.up if request.get("side") == "buy" else Direction.down)
                   and math.isclose(pos.volume, float(request.get("volume", 0)), rel_tol=1e-9, abs_tol=1e-9)
                   and pos.volume > 0 and math.isfinite(pos.entry) and pos.entry > 0]
        if len(matches) == 1:
            pos = matches[0]
            result = OrderResult(
                order_id=row["id"], idempotency_key=key, status=OrderState.filled,
                message="recovered by reconciliation (order was already live at the broker)",
                ticket=pos.ticket, filled_volume=pos.volume, fill_price=pos.entry,
                verified=True, created_at=time.time(),
            )
            self._persist_result(row["id"], result, OrderRequest(**request))
            return result
        return None

    # ------------------------------------------------------------ management
    def modify(self, adapter: BrokerAdapter, ticket: str, sl: float | None = None,
               tp: float | None = None, reason: str = "") -> bool:
        try:
            ok = adapter.modify_position(ticket, sl=sl, tp=tp)
            self.db.audit("position-manager", "position.modify",
                          {"ticket": ticket, "sl": sl, "tp": tp, "ok": ok, "reason": reason})
            return ok
        except BrokerError as exc:
            self.db.audit("position-manager", "position.modify_failed", {"ticket": ticket, "error": str(exc)})
            return False

    def close(self, adapter: BrokerAdapter, ticket: str, volume: float | None = None,
              reason: str = "manual", actor: str = "user") -> dict[str, Any]:
        """Close (or partially close) a position and normalise the two shapes.

        The simulated broker settles inside `close_position` and returns the
        finished ``TradeRecord``; the MT5 adapter returns the order's
        ``OrderResult``. Callers used to assume ``.status`` existed and crashed on
        every simulated close, so this method now returns one dict for both.
        """
        result = adapter.close_position(ticket, volume=volume, comment=reason[:24])
        payload: dict[str, Any]
        if isinstance(result, TradeRecord):
            still_open = any(p.ticket == ticket for p in adapter.positions())
            if still_open:
                # A partial close: the position lives on, so it must not be
                # written into the closed-trades table yet.
                self.db.audit(actor, "position.partial_realized",
                              {"ticket": ticket, "pnl": result.pnl, "volume": result.volume,
                               "reason": reason})
            else:
                self.record_trade(result)
            payload = {"ok": True, "trade": result.model_dump()}
        else:
            ok = result.status in (OrderState.closed, OrderState.filled)
            payload = {"ok": ok, "order": result.model_dump()}
        self.db.audit(actor, "position.close",
                      {"ticket": ticket, "volume": volume, "reason": reason, "result": payload})
        return payload

    def reconcile(self, adapter: BrokerAdapter) -> dict[str, Any]:
        """Compare remembered positions with the broker; never place orders here."""
        stored = {r["ticket"]: r for r in self.db.query("SELECT * FROM open_positions")}
        try:
            live = {p.ticket: p for p in adapter.positions()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "checked_at": time.time()}
        missing_at_broker = sorted(set(stored) - set(live))
        unknown_locally = sorted(set(live) - set(stored))
        for ticket, pos in live.items():
            self.db.execute(
                "INSERT OR REPLACE INTO open_positions(ticket, payload, updated_at) VALUES(?,?,?)",
                (ticket, json.dumps(pos.model_dump(), default=str), time.time()),
            )
        for ticket in missing_at_broker:
            self.db.execute("DELETE FROM open_positions WHERE ticket = ?", (ticket,))
        status = {
            "ok": not missing_at_broker and not unknown_locally,
            "broker_id": adapter.id,
            "positions": len(live),
            "missing_at_broker": missing_at_broker,
            "unknown_locally": unknown_locally,
            "checked_at": time.time(),
        }
        if not status["ok"]:
            self.db.audit("reconciler", "reconcile.mismatch", status)
        return status

    # ---------------------------------------------------------------- journal
    def record_trade(self, trade: TradeRecord) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO trades(ticket, opened_at, closed_at, symbol, direction, volume, entry, exit, "
            "pnl, points, exit_reason, strategy, mode, broker_id, payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (trade.ticket, trade.opened_at, trade.closed_at, trade.symbol, trade.direction.value, trade.volume,
             trade.entry, trade.exit, trade.pnl, trade.points, trade.exit_reason, trade.strategy,
             trade.mode.value if isinstance(trade.mode, TradeMode) else str(trade.mode), trade.broker_id,
             json.dumps(trade.model_dump(), default=str)),
        )
        self.db.execute("DELETE FROM open_positions WHERE ticket = ?", (trade.ticket,))

    def open_position_snapshot(self, positions: list[Position]) -> None:
        """Replace the local mirror with the broker's current position list.

        Upsert-only snapshots leave rows behind after the last position closes,
        which then shows up as a bogus "missing at broker" mismatch.
        """
        live_tickets = {pos.ticket for pos in positions}
        for pos in positions:
            self.db.execute(
                "INSERT OR REPLACE INTO open_positions(ticket, payload, updated_at) VALUES(?,?,?)",
                (pos.ticket, json.dumps(pos.model_dump(), default=str), time.time()),
            )
        for row in self.db.query("SELECT ticket FROM open_positions"):
            if row["ticket"] not in live_tickets:
                self.db.execute("DELETE FROM open_positions WHERE ticket = ?", (row["ticket"],))

    def history(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM trades ORDER BY closed_at DESC LIMIT ?", (limit,))
        out = []
        for row in rows:
            try:
                payload = json.loads(row["payload"] or "{}")
            except json.JSONDecodeError:
                payload = {}
            out.append(payload or dict(row))
        return out

    def open_positions(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM open_positions")
        out = []
        for row in rows:
            try:
                out.append(json.loads(row["payload"]))
            except json.JSONDecodeError:
                continue
        return out


def direction_from_string(value: str) -> Direction:
    return Direction.up if value.lower() in ("buy", "long", "up") else Direction.down
