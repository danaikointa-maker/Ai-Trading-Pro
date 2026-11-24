"""Persistent, candidate-only 100 MT5-point signal confirmation gate.

This gate owns signal confirmation state only. It does not size risk, approve an
order, or call the execution gateway. The candidate profile is disabled unless
the runtime is explicitly configured to enable it.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from typing import Any

from packages.persistence.db import Database
from packages.shared_schemas.models import Direction

WAIT = "WAIT_100_POINTS"
CONFIRMED = "M1_M5_CONFIRMED"
EXPIRED = "EXPIRED"
BLOCKED = "BLOCKED"
INVALIDATED = "INVALIDATED"


def confirmation_movement_points(direction: Direction, reference_price: float,
                                 price: float, point: float) -> float:
    """Shared directional point-distance formula for gate and read-only previews."""
    sign = 1.0 if direction == Direction.up else -1.0
    return (float(price) - float(reference_price)) * sign / float(point)


@dataclass(frozen=True)
class ConfirmationResult:
    state: str
    candidate_id: str | None
    expires_at: int | None
    reason: str
    reference_price: float | None = None
    confirmation_bar_t: int | None = None
    confirmation_close: float | None = None
    confirmation_points: float = 0.0
    chase_points: float | None = None


class SignalConfirmationGate:
    """One persistent candidate per workspace/broker/symbol, deduplicated in SQLite."""

    def __init__(self, db: Database, *, confirmation_points: float = 100.0,
                 max_chase_points: float = 30.0, expiry_seconds: int = 300,
                 max_closed_m1_age_seconds: int = 75) -> None:
        values = (confirmation_points, max_chase_points, expiry_seconds,
                  max_closed_m1_age_seconds)
        if not all(math.isfinite(float(value)) and float(value) > 0 for value in values):
            raise ValueError("confirmation thresholds must be finite and positive")
        if int(expiry_seconds) != expiry_seconds or int(max_closed_m1_age_seconds) != max_closed_m1_age_seconds:
            raise ValueError("confirmation time limits must be whole seconds")
        self.db = db
        self.confirmation_points = float(confirmation_points)
        self.max_chase_points = float(max_chase_points)
        self.expiry_seconds = int(expiry_seconds)
        self.max_closed_m1_age_seconds = int(max_closed_m1_age_seconds)

    @staticmethod
    def _signature(direction: Direction, strategy: str, zone_ids: list[str]) -> str:
        payload = json.dumps([direction.value, strategy, sorted(set(zone_ids))], separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()[:24]

    def _account_scope(self, broker_id: str, identity: dict[str, Any] | None) -> str | None:
        """Hash the verified broker identity so pending state cannot cross logins."""
        required = ("broker_id", "login", "server", "currency", "workspace_id")
        if not isinstance(identity, dict) or identity.get("broker_id") != broker_id:
            return None
        if identity.get("workspace_id") != self.db.workspace_id:
            return None
        if any(not isinstance(identity.get(key), str) or not identity[key].strip()
               or identity[key] != identity[key].strip() or identity[key] == "—"
               for key in required):
            return None
        canonical = json.dumps({key: identity[key] for key in required},
                               sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _key(self, broker_id: str, symbol: str, account_scope: str) -> str:
        return (f"signal-confirmation-v4:{self.db.workspace_id}:{broker_id}:"
                f"{account_scope}:{symbol}")

    def advance(self, *, broker_id: str, symbol: str, direction: Direction,
                strategy: str, zone_ids: list[str], now: float, point: float,
                reference_price: float, execution_price: float,
                m1_bars: list[dict[str, Any]], m5_direction: Direction,
                data_fresh: bool, broker_healthy: bool,
                account_identity: dict[str, Any] | None = None) -> ConfirmationResult:
        """Advance one signal candidate using UTC market time and closed M1 evidence.

        Chosen candidate interpretation: confirmation is a closed M1 close at
        least 100 broker points beyond the first observed quote. Entry may be no
        more than 30 broker points from that confirming close. This lives in the
        OFF-by-default candidate profile and needs Demo acceptance before use.
        """
        if direction not in (Direction.up, Direction.down):
            return ConfirmationResult(BLOCKED, None, None, "candidate has no trade direction")
        if not broker_id.strip() or not symbol.strip() or not strategy.strip():
            return ConfirmationResult(BLOCKED, None, None, "candidate identity is incomplete")
        if not math.isfinite(float(now)) or not math.isfinite(float(point)) or point <= 0:
            return ConfirmationResult(BLOCKED, None, None, "market clock or broker point is invalid")
        if not math.isfinite(float(reference_price)) or reference_price <= 0:
            return ConfirmationResult(BLOCKED, None, None, "reference quote is invalid")
        if not math.isfinite(float(execution_price)) or execution_price <= 0:
            return ConfirmationResult(BLOCKED, None, None, "execution-side quote is invalid")

        account_scope = self._account_scope(broker_id, account_identity)
        if account_scope is None:
            return ConfirmationResult(BLOCKED, None, None,
                                      "verified broker account identity is required")
        key = self._key(broker_id, symbol, account_scope)
        signature = self._signature(direction, strategy, zone_ids)
        candidate_bar = self._latest_closed_bar(m1_bars, int(now))
        candidate_bar_t = int(candidate_bar["t"]) if candidate_bar else None
        existing: dict[str, Any] | None = None

        # The single SQLite writer lock makes concurrent workers converge on the
        # same candidate ID and release transition; a retry cannot create a second
        # confirmation candidate for the same broker/symbol setup.
        with self.db.cursor() as cur:
            cur.execute("BEGIN IMMEDIATE")
            row = cur.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            if row:
                try:
                    parsed = json.loads(row["value"])
                    existing = parsed if isinstance(parsed, dict) else None
                except (TypeError, json.JSONDecodeError):
                    existing = None

            same_candidate = bool(
                existing and existing.get("signature") == signature
                and existing.get("account_scope") == account_scope
                and isinstance(existing.get("candidate_id"), str)
                and isinstance(existing.get("expires_at"), int)
                and existing.get("state") in (WAIT, CONFIRMED, INVALIDATED)
            )
            if (same_candidate and existing["state"] == INVALIDATED
                    and int(existing["expires_at"]) > int(now)):
                return self._result(existing)
            if (same_candidate and existing["state"] in (WAIT, CONFIRMED)
                    and int(existing["expires_at"]) <= int(now)):
                existing.update(state=EXPIRED, updated_at=int(now), reason="confirmation expired")
                cur.execute("UPDATE kv SET value=?,updated_at=? WHERE key=?",
                            (json.dumps(existing, sort_keys=True, allow_nan=False), time.time(), key))
                return self._result(existing)
            reusable = bool(same_candidate and existing.get("state") in (WAIT, CONFIRMED)
                            and int(existing["expires_at"]) > int(now))
            if reusable:
                state = existing
            else:
                if not broker_healthy or not data_fresh:
                    return ConfirmationResult(BLOCKED, None, None,
                                              "fresh broker data is required to start confirmation")
                if candidate_bar is None:
                    return ConfirmationResult(BLOCKED, None, None,
                                              "a fresh, closed M1 candle is required")
                seed = (f"{self.db.workspace_id}:{broker_id}:{account_scope}:"
                        f"{symbol}:{signature}:{candidate_bar_t}")
                candidate_id = "C-" + hashlib.sha256(seed.encode()).hexdigest()[:20]
                state = {
                    "schema_version": 1, "candidate_id": candidate_id,
                    "broker_id": broker_id, "symbol": symbol, "signature": signature,
                    "account_scope": account_scope,
                    "direction": direction.value, "strategy": strategy,
                    "zone_ids": sorted(set(zone_ids)), "state": WAIT,
                    "started_at": int(now), "source_bar_t": candidate_bar_t,
                    "reference_price": float(reference_price),
                    "expires_at": int(now) + self.expiry_seconds,
                    "updated_at": int(now), "confirmation_bar_t": None,
                    "confirmation_close": None, "confirmation_points": 0.0,
                    "chase_points": None, "reason": "waiting for 100 MT5 points, closed M1 and aligned M5 trend",
                }
            if int(state["expires_at"]) <= int(now):
                state.update(state=EXPIRED, updated_at=int(now), reason="confirmation expired")
            elif state["state"] == WAIT:
                reason = "waiting for 100 MT5 points, closed M1 and aligned M5 trend"
                bar = candidate_bar
                if not broker_healthy or not data_fresh:
                    reason = "fresh broker data is unavailable; confirmation remains blocked"
                elif bar is None:
                    reason = "a fresh, closed M1 candle is required"
                elif m5_direction != direction:
                    reason = "M5 trend is not aligned with the candidate"
                else:
                    movement = confirmation_movement_points(
                        direction, float(state["reference_price"]), float(bar["c"]), point)
                    chase = abs(execution_price - float(bar["c"])) / point
                    state.update(confirmation_bar_t=int(bar["t"]),
                                 confirmation_close=float(bar["c"]),
                                 confirmation_points=round(movement, 2),
                                 chase_points=round(chase, 2))
                    # Binary floats can represent an exact broker-point move as
                    # 99.999999999...; allow only tiny numerical tolerance.
                    if (movement >= self.confirmation_points
                            or math.isclose(movement, self.confirmation_points, abs_tol=1e-7)):
                        movement_confirmed = True
                    else:
                        movement_confirmed = False
                    chase_within_limit = (
                        chase <= self.max_chase_points
                        or math.isclose(chase, self.max_chase_points, abs_tol=1e-7)
                    )
                    if movement_confirmed and chase_within_limit:
                        state.update(state=CONFIRMED, updated_at=int(now),
                                     reason="100-point closed M1 confirmation and M5 trend aligned")
                    elif movement_confirmed:
                        reason = (f"confirmation reached but entry is {chase:.1f} points from the close; "
                                  f"maximum chase is {self.max_chase_points:.0f}")
                    else:
                        reason = f"M1 confirmation is {movement:.1f}/{self.confirmation_points:.0f} points"
                if state["state"] == WAIT:
                    state.update(updated_at=int(now), reason=reason)

            cur.execute(
                "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                (key, json.dumps(state, sort_keys=True, allow_nan=False), time.time()),
            )

        return self._result(state)

    @staticmethod
    def _result(state: dict[str, Any]) -> ConfirmationResult:
        return ConfirmationResult(
            state=state["state"], candidate_id=state["candidate_id"],
            expires_at=int(state["expires_at"]), reason=state["reason"],
            reference_price=float(state["reference_price"]),
            confirmation_bar_t=state.get("confirmation_bar_t"),
            confirmation_close=state.get("confirmation_close"),
            confirmation_points=float(state.get("confirmation_points") or 0.0),
            chase_points=state.get("chase_points"),
        )

    def validate_execution(self, *, broker_id: str, symbol: str, candidate_id: str,
                           direction: Direction, now: float, point: float,
                           execution_price: float, m1_bars: list[dict[str, Any]],
                           m5_direction: Direction, data_fresh: bool,
                           broker_healthy: bool,
                           account_identity: dict[str, Any] | None = None) -> ConfirmationResult:
        """Recheck persisted confirmation at the final execution boundary.

        A signal payload or an earlier confirmation cannot authorize a later
        command by itself. The stored candidate must still be confirmed, fresh,
        aligned, unexpired, and within its chase limit at the current quote.
        """
        try:
            now_value = float(now)
            point_value = float(point)
            price_value = float(execution_price)
        except (TypeError, ValueError):
            return ConfirmationResult(BLOCKED, None, None,
                                      "execution confirmation inputs are invalid")
        if (not all(isinstance(value, str) and value.strip()
                    for value in (broker_id, symbol, candidate_id))
                or not math.isfinite(now_value) or not math.isfinite(point_value)
                or point_value <= 0 or not math.isfinite(price_value) or price_value <= 0):
            return ConfirmationResult(BLOCKED, None, None,
                                      "execution confirmation inputs are invalid")
        account_scope = self._account_scope(broker_id, account_identity)
        if account_scope is None:
            return ConfirmationResult(BLOCKED, candidate_id, None,
                                      "verified broker account identity is required at execution")
        now_int = int(now_value)

        key = self._key(broker_id, symbol, account_scope)
        with self.db.cursor() as cur:
            cur.execute("BEGIN IMMEDIATE")
            row = cur.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            if not row:
                return ConfirmationResult(BLOCKED, None, None,
                                          "persisted 100-point confirmation is missing")
            try:
                state = json.loads(row["value"])
            except (TypeError, json.JSONDecodeError):
                return ConfirmationResult(BLOCKED, None, None,
                                          "persisted 100-point confirmation is invalid")
            if (not isinstance(state, dict) or state.get("candidate_id") != candidate_id
                    or state.get("broker_id") != broker_id or state.get("symbol") != symbol
                    or state.get("account_scope") != account_scope
                    or state.get("direction") != direction.value):
                return ConfirmationResult(BLOCKED, None, None,
                                          "signal does not match the persisted confirmation")
            try:
                expires_at = int(state["expires_at"])
            except (KeyError, TypeError, ValueError, OverflowError):
                return ConfirmationResult(BLOCKED, candidate_id, None,
                                          "persisted confirmation expiry is invalid")
            if state.get("state") in (EXPIRED, INVALIDATED):
                return self._result(state)
            if state.get("state") != CONFIRMED:
                return ConfirmationResult(BLOCKED, candidate_id,
                                          expires_at,
                                          "100-point confirmation is not complete")
            if expires_at <= now_int:
                state.update(state=EXPIRED, updated_at=now_int,
                             reason="confirmation expired before execution")
                cur.execute("UPDATE kv SET value=?,updated_at=? WHERE key=?",
                            (json.dumps(state, sort_keys=True, allow_nan=False),
                             time.time(), key))
                return self._result(state)
            if not broker_healthy or not data_fresh:
                return ConfirmationResult(BLOCKED, candidate_id,
                                          expires_at,
                                          "fresh broker data is required at execution")
            bar = self._latest_closed_bar(m1_bars, now_int)
            if bar is None:
                return ConfirmationResult(BLOCKED, candidate_id,
                                          expires_at,
                                          "a fresh, closed M1 candle is required at execution")

            reason = ""
            if m5_direction != direction:
                reason = "M5 trend changed before execution"
            else:
                confirmation_close = state.get("confirmation_close")
                confirmation_points = state.get("confirmation_points")
                if (not isinstance(confirmation_close, (int, float))
                        or not math.isfinite(float(confirmation_close))
                        or not isinstance(confirmation_points, (int, float))
                        or not math.isfinite(float(confirmation_points))
                        or confirmation_points < self.confirmation_points):
                    return ConfirmationResult(BLOCKED, candidate_id,
                                              expires_at,
                                              "persisted confirmation evidence is incomplete")
                chase = abs(price_value - float(confirmation_close)) / point_value
                within_limit = (chase <= self.max_chase_points
                                or math.isclose(chase, self.max_chase_points, abs_tol=1e-7))
                if not within_limit:
                    reason = (f"entry moved {chase:.1f} points from the confirming close; "
                              f"maximum chase is {self.max_chase_points:.0f}")
                else:
                    refreshed = dict(state)
                    refreshed["chase_points"] = round(chase, 2)
                    return self._result(refreshed)

            state.update(state=INVALIDATED, updated_at=int(now), reason=reason)
            cur.execute("UPDATE kv SET value=?,updated_at=? WHERE key=?",
                        (json.dumps(state, sort_keys=True, allow_nan=False),
                         time.time(), key))
            return self._result(state)

    def invalidate(self, *, broker_id: str, symbol: str, candidate_id: str,
                   reason: str = "signal rejected by user", now: float | None = None,
                   account_identity: dict[str, Any] | None = None) -> bool:
        account_scope = self._account_scope(broker_id, account_identity)
        if account_scope is None:
            return False
        key = self._key(broker_id, symbol, account_scope)
        try:
            stamp = float(time.time() if now is None else now)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(stamp):
            return False
        invalidated_at = int(stamp)
        with self.db.cursor() as cur:
            cur.execute("BEGIN IMMEDIATE")
            row = cur.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            if not row:
                return False
            try:
                state = json.loads(row["value"])
            except (TypeError, json.JSONDecodeError):
                return False
            if (not isinstance(state, dict) or state.get("candidate_id") != candidate_id
                    or state.get("broker_id") != broker_id or state.get("symbol") != symbol
                    or state.get("account_scope") != account_scope
                    or state.get("state") not in (WAIT, CONFIRMED)):
                return False
            state.update(state=INVALIDATED, reason=reason[:200], updated_at=invalidated_at)
            cur.execute("UPDATE kv SET value=?,updated_at=? WHERE key=?",
                        (json.dumps(state, sort_keys=True, allow_nan=False), time.time(), key))
        self.db.audit("signal-confirmation", "signal.confirmation.invalidated",
                      {"broker_id": broker_id, "symbol": symbol,
                       "candidate_id": candidate_id, "reason": reason[:200]})
        return True

    def _latest_closed_bar(self, bars: list[dict[str, Any]], now: int) -> dict[str, float | int] | None:
        if not isinstance(bars, list):
            return None
        for row in reversed(bars):
            try:
                opened = int(row["t"])
                close = float(row["c"])
            except (KeyError, TypeError, ValueError):
                continue
            age = now - (opened + 60)
            if (opened > 0 and math.isfinite(close) and close > 0
                    and 0 <= age <= self.max_closed_m1_age_seconds):
                return {"t": opened, "c": close}
        return None
