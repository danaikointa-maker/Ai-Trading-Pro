"""V4 confirmation candidates are deterministic, persistent and non-executing."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from packages.persistence.db import Database
from packages.shared_schemas.models import Direction
from services.strategy_engine.confirmation import (
    BLOCKED,
    CONFIRMED,
    EXPIRED,
    INVALIDATED,
    WAIT,
    SignalConfirmationGate,
)

NOW = 1_700_000_120
POINT = 0.01


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "confirm.sqlite")
    try:
        yield database
    finally:
        database.close()


def advance(gate, *, direction=Direction.up, now=NOW, close=2000.0,
            reference=2000.0, quote=2000.0, m5=Direction.up,
            fresh=True, healthy=True, bar_t=NOW - 60, broker="demo", zones=None):
    return gate.advance(
        broker_id=broker, symbol="XAUUSD", direction=direction,
        strategy="breakout_continuation", zone_ids=zones or ["zone-a"],
        now=now, point=POINT, reference_price=reference, execution_price=quote,
        m1_bars=[{"t": bar_t, "o": close, "h": close, "l": close, "c": close, "v": 1}],
        m5_direction=m5, data_fresh=fresh, broker_healthy=healthy,
    )


def test_buy_waits_for_100_closed_m1_points_and_aligned_m5(db):
    gate = SignalConfirmationGate(db)
    first = advance(gate)
    assert first.state == WAIT
    assert first.candidate_id and first.expires_at == NOW + 300

    not_enough = advance(gate, now=NOW + 10, close=2000.999, quote=2000.999,
                         bar_t=NOW - 60)
    assert not_enough.state == WAIT
    assert not_enough.candidate_id == first.candidate_id
    assert not_enough.confirmation_points == pytest.approx(99.9)

    wrong_trend = advance(gate, now=NOW + 10, close=2001.0, quote=2001.0,
                          m5=Direction.down, bar_t=NOW - 60)
    assert wrong_trend.state == WAIT

    confirmed = advance(gate, now=NOW + 10, close=2001.0, quote=2001.2,
                        bar_t=NOW - 60)
    assert confirmed.state == CONFIRMED
    assert confirmed.candidate_id == first.candidate_id
    assert confirmed.confirmation_points == pytest.approx(100)
    assert confirmed.chase_points == pytest.approx(20)
    assert db.query_one("SELECT 1 FROM orders") is None


def test_sell_uses_sell_side_and_negative_price_direction(db):
    gate = SignalConfirmationGate(db)
    first = advance(gate, direction=Direction.down, reference=2000.0,
                    quote=2000.0, close=2000.0)
    assert first.state == WAIT
    confirmed = advance(gate, direction=Direction.down, reference=2000.0,
                        quote=1999.2, close=1999.0, m5=Direction.down,
                        now=NOW + 5, bar_t=NOW - 60)
    assert confirmed.state == CONFIRMED
    assert confirmed.confirmation_points == pytest.approx(100)


def test_chase_over_30_points_never_releases_order(db):
    gate = SignalConfirmationGate(db)
    first = advance(gate)
    too_far = advance(gate, now=NOW + 5, close=2001.0, quote=2001.31,
                      bar_t=NOW - 60)
    assert too_far.state == WAIT
    assert too_far.candidate_id == first.candidate_id
    assert too_far.chase_points == pytest.approx(31)
    assert "maximum chase" in too_far.reason


@pytest.mark.parametrize("kwargs,reason", [
    ({"fresh": False}, "fresh broker data"),
    ({"healthy": False}, "fresh broker data"),
    ({"bar_t": NOW - 180}, "closed M1 candle"),
])
def test_missing_or_unsafe_market_evidence_blocks_new_candidate(db, kwargs, reason):
    result = advance(SignalConfirmationGate(db), **kwargs)
    assert result.state == BLOCKED
    assert reason in result.reason
    assert db.query_one("SELECT 1 FROM orders") is None


def test_expiry_uses_market_time_and_not_wall_clock(db):
    gate = SignalConfirmationGate(db)
    first = advance(gate)
    expired = advance(gate, now=first.expires_at, close=2001.0, quote=2001.0,
                      bar_t=NOW + 180)
    assert expired.state == EXPIRED


def test_confirmed_candidate_survives_restart_and_deduplicates(tmp_path):
    path = tmp_path / "restart.sqlite"
    first_db = Database(path)
    second_db = Database(path)
    try:
        first_gate = SignalConfirmationGate(first_db)
        initial = advance(first_gate)
        ready = advance(first_gate, now=NOW + 5, close=2001.0, quote=2001.1,
                        bar_t=NOW - 60)
        assert ready.state == CONFIRMED

        restarted = SignalConfirmationGate(second_db)
        duplicate = advance(restarted, now=NOW + 10, close=2001.1, quote=2001.1,
                            bar_t=NOW - 60)
        assert duplicate.state == CONFIRMED
        assert duplicate.candidate_id == initial.candidate_id == ready.candidate_id
        assert second_db.query_one("SELECT COUNT(*) AS c FROM orders")["c"] == 0
    finally:
        first_db.close()
        second_db.close()


def test_simultaneous_workers_converge_on_single_candidate(tmp_path):
    path = tmp_path / "concurrent.sqlite"
    db_a = Database(path)
    db_b = Database(path)
    gate_a = SignalConfirmationGate(db_a)
    gate_b = SignalConfirmationGate(db_b)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda gate: advance(gate), [gate_a, gate_b]))
        assert results[0].candidate_id == results[1].candidate_id
        rows = db_a.query("SELECT value FROM kv WHERE key LIKE 'signal-confirmation-v4:%'")
        assert len(rows) == 1
    finally:
        db_a.close()
        db_b.close()


def test_reject_invalidates_and_holds_candidate_until_expiry(db):
    gate = SignalConfirmationGate(db)
    first = advance(gate)
    ready = advance(gate, now=NOW + 5, close=2001.0, quote=2001.0,
                    bar_t=NOW - 60)
    assert ready.state == CONFIRMED
    assert gate.invalidate(broker_id="demo", symbol="XAUUSD",
                           candidate_id=ready.candidate_id)
    result = advance(gate, now=NOW + 10, close=2001.0, quote=2001.0,
                     bar_t=NOW - 60)
    assert result.state == INVALIDATED
    assert result.candidate_id == first.candidate_id
