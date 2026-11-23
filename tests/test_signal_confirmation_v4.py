"""V4 confirmation candidates are deterministic, persistent and non-executing."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import pandas as pd
from threading import RLock

from packages.persistence.db import Database
from packages.shared_schemas.models import (
    Direction,
    Health,
    Signal,
    SignalAction,
    SignalStatus,
    SymbolSpec,
    Tick,
    TradePlan,
    TradeMode,
)
from services.api_gateway.state import TradingRuntime
from services.market_data.replay import ReplayFeed
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


def identity(db, broker="demo", login="demo-123"):
    return {"broker_id": broker, "login": login, "server": "Demo-Server",
            "currency": "USD", "workspace_id": db.workspace_id}


def advance(gate, *, direction=Direction.up, now=NOW, close=2000.0,
            reference=2000.0, quote=2000.0, m5=Direction.up,
            fresh=True, healthy=True, bar_t=NOW - 60, broker="demo", zones=None,
            account_login="demo-123"):
    return gate.advance(
        broker_id=broker, symbol="XAUUSD", direction=direction,
        strategy="breakout_continuation", zone_ids=zones or ["zone-a"],
        now=now, point=POINT, reference_price=reference, execution_price=quote,
        m1_bars=[{"t": bar_t, "o": close, "h": close, "l": close, "c": close, "v": 1}],
        m5_direction=m5, data_fresh=fresh, broker_healthy=healthy,
        account_identity=identity(gate.db, broker, account_login),
    )


def test_paper_replay_feed_confirms_runtime_signal_without_creating_an_order(db, monkeypatch):
    start = NOW - (NOW % 60)
    rows = [{"t": start + i * 60, "o": 2000.0, "h": 2000.2,
             "l": 1999.8, "c": 2000.0, "v": 1.0}
            for i in range(62)]
    rows[60].update(o=2000.0, h=2001.11, l=2000.0, c=2001.10)
    frame = pd.DataFrame(rows)
    feed = ReplayFeed(
        {"XAUUSD": frame},
        {"XAUUSD": {"point": POINT, "digits": 2, "spread_typical_points": 2}},
        warmup_bars=60, speed_minutes_per_second=60, tick_seconds=1, seed=5,
    )
    gate = SignalConfirmationGate(db)

    def context():
        bars = feed.warm_history("XAUUSD", 120)
        snapshot = SimpleNamespace(
            spec=SymbolSpec(symbol="XAUUSD", point=POINT, digits=2),
            trend=[SimpleNamespace(timeframe="M5", direction=Direction.up)],
            data_quality={"ok": True}, news_lockout={},
            indicators=SimpleNamespace(atr14=1.0), price=feed.last_bar_price("XAUUSD"),
            regime=None, model_dump=lambda **_kwargs: {"symbol": "XAUUSD"},
        )
        return SimpleNamespace(snapshot=snapshot, frames={"M1": bars, "M5": bars})

    scan = {"count": 0}

    def generate_signal(*_args, **_kwargs):
        scan["count"] += 1
        now = int(feed.end_time)
        return Signal(
            id=f"paper-scan-{scan['count']}", t=now, symbol="XAUUSD",
            timeframe="M1", broker_id="paper-replay", action=SignalAction.buy,
            status=SignalStatus.valid, score=90, strategy="breakout_continuation",
            regime="trending", expires_at=now + 120, zones_used=["replay-zone"],
            plan=TradePlan(direction=Direction.up, entry=2000.0, sl=1990.0,
                           tp1=2010.0, tp2=2020.0, tp3=2030.0, sl_points=100),
        )

    monkeypatch.setattr(
        "services.api_gateway.state.entry_proposals",
        lambda signal, *_args, **_kwargs: {
            "signal_id": signal.id, "proposals": [], "executable": False,
        },
    )
    runtime = SimpleNamespace(
        analysis=SimpleNamespace(snapshot=lambda _symbol: context()),
        predictor=SimpleNamespace(
            forecast=lambda *_args: SimpleNamespace(regime=""), approved=True),
        market=SimpleNamespace(ticker=lambda symbol: feed.ticker(symbol)),
        strategy=SimpleNamespace(
            generate=generate_signal,
            evaluate_gate=lambda *_args: SimpleNamespace(
                allow=True, blockers=[], warnings=[], checks=[]),
        ),
        adapter=SimpleNamespace(id="paper-replay"), mode=TradeMode.manual,
        confirmation_gate=gate, planner=object(),
        gateway=SimpleNamespace(_account=lambda _adapter: identity(db, "paper-replay", "replay-1")),
        risk=SimpleNamespace(limits=lambda: None),
        lock=RLock(), attribution={}, contexts={}, forecasts={}, signals={},
        plans={}, proposals={}, gates={}, signal_log=[], plan_analyses={}, version=0,
        _log_error=lambda *_args: None,
        _persist_signal=lambda *_args: None,
        _maybe_alert=lambda *_args: None,
        _maybe_alert_readiness=lambda *_args: None,
    )

    TradingRuntime._decide_symbol(runtime, "XAUUSD", 10_000.0,
                                  Health.connected, SimpleNamespace(), feed.end_time)
    first = runtime.signals["XAUUSD"]
    assert first.action == SignalAction.wait
    assert first.explanation["signal_confirmation_v4"]["state"] == WAIT

    for _ in range(feed.ticks_per_bar):
        feed.tick()
        feed.advance_clock()

    TradingRuntime._decide_symbol(runtime, "XAUUSD", 10_000.0,
                                  Health.connected, SimpleNamespace(), feed.end_time)
    confirmed = runtime.signals["XAUUSD"]
    assert confirmed.action == SignalAction.buy
    assert confirmed.explanation["signal_confirmation_v4"]["state"] == CONFIRMED
    assert db.query("SELECT * FROM orders") == []


def test_buy_waits_for_100_closed_m1_points_and_aligned_m5(db):
    gate = SignalConfirmationGate(db)
    first = advance(gate)
    assert first.state == WAIT
    assert first.candidate_id and first.expires_at == NOW + 300

    not_enough = advance(gate, now=NOW + 10, close=2000.99, quote=2000.99,
                         bar_t=NOW - 60)
    assert not_enough.state == WAIT
    assert not_enough.candidate_id == first.candidate_id
    assert not_enough.confirmation_points == pytest.approx(99)

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


def test_confirmation_state_is_isolated_by_verified_account_identity(db):
    gate = SignalConfirmationGate(db)
    first = advance(gate, account_login="demo-111")
    second = advance(gate, account_login="demo-222")
    assert first.state == second.state == WAIT
    assert first.candidate_id != second.candidate_id
    rows = db.query("SELECT key FROM kv WHERE key LIKE 'signal-confirmation-v4:%'")
    assert len(rows) == 2


def test_confirmation_blocks_when_account_identity_is_unverified(db):
    gate = SignalConfirmationGate(db)
    result = gate.advance(
        broker_id="demo", symbol="XAUUSD", direction=Direction.up,
        strategy="breakout_continuation", zone_ids=["zone-a"], now=NOW,
        point=POINT, reference_price=2000.0, execution_price=2000.0,
        m1_bars=[{"t": NOW - 60, "c": 2000.0}], m5_direction=Direction.up,
        data_fresh=True, broker_healthy=True,
        account_identity={"broker_id": "demo", "login": "123", "server": "Demo-Server",
                          "currency": "USD", "workspace_id": "another-workspace"},
    )
    assert result.state == BLOCKED
    assert "account identity" in result.reason
    assert db.query("SELECT key FROM kv WHERE key LIKE 'signal-confirmation-v4:%'") == []


def test_reject_invalidates_and_holds_candidate_until_expiry(db):
    gate = SignalConfirmationGate(db)
    first = advance(gate)
    ready = advance(gate, now=NOW + 5, close=2001.0, quote=2001.0,
                    bar_t=NOW - 60)
    assert ready.state == CONFIRMED
    assert gate.invalidate(broker_id="demo", symbol="XAUUSD",
                           candidate_id=ready.candidate_id,
                           account_identity=identity(db))
    result = advance(gate, now=NOW + 10, close=2001.0, quote=2001.0,
                     bar_t=NOW - 60)
    assert result.state == INVALIDATED
    assert result.candidate_id == first.candidate_id


def _confirm(gate):
    initial = advance(gate)
    confirmed = advance(gate, now=NOW + 5, close=2001.0, quote=2001.1,
                        bar_t=NOW - 60)
    assert confirmed.state == CONFIRMED
    assert confirmed.candidate_id == initial.candidate_id
    return confirmed


def _validate(gate, candidate, *, now=NOW + 6, quote=2001.2,
              m5=Direction.up, fresh=True, healthy=True, bar_t=NOW - 60,
              account_login="demo-123"):
    return gate.validate_execution(
        broker_id="demo", symbol="XAUUSD", candidate_id=candidate.candidate_id,
        direction=Direction.up, now=now, point=POINT, execution_price=quote,
        m1_bars=[{"t": bar_t, "c": 2001.0}], m5_direction=m5,
        data_fresh=fresh, broker_healthy=healthy,
        account_identity=identity(gate.db, "demo", account_login),
    )


def test_execution_revalidates_persisted_candidate_and_current_chase(db):
    gate = SignalConfirmationGate(db)
    candidate = _confirm(gate)
    current = _validate(gate, candidate)
    assert current.state == CONFIRMED
    assert current.chase_points == pytest.approx(20)

    stale = _validate(gate, candidate, now=NOW + 7, fresh=False)
    assert stale.state == BLOCKED
    assert "fresh broker data" in stale.reason

    switched_account = _validate(gate, candidate, account_login="demo-222")
    assert switched_account.state == BLOCKED

    too_far = _validate(gate, candidate, now=NOW + 8, quote=2001.31)
    assert too_far.state == INVALIDATED
    assert "maximum chase" in too_far.reason
    replay = _validate(gate, candidate, now=NOW + 9, quote=2001.0)
    assert replay.state == INVALIDATED
    assert replay.candidate_id == candidate.candidate_id


def test_execution_invalidates_candidate_when_m5_trend_flips(db):
    gate = SignalConfirmationGate(db)
    candidate = _confirm(gate)
    result = _validate(gate, candidate, m5=Direction.down)
    assert result.state == INVALIDATED
    assert "M5 trend changed" in result.reason


def test_execution_requires_recent_closed_m1_and_unexpired_state(db):
    gate = SignalConfirmationGate(db)
    candidate = _confirm(gate)
    old_bar = _validate(gate, candidate, bar_t=NOW - 180)
    assert old_bar.state == BLOCKED
    assert "closed M1" in old_bar.reason

    expired = _validate(gate, candidate, now=candidate.expires_at)
    assert expired.state == EXPIRED


def test_legacy_buy_signal_cannot_bypass_enabled_confirmation(db):
    signal = Signal(
        id="legacy-buy", t=NOW, symbol="XAUUSD", timeframe="M1", broker_id="demo",
        action=SignalAction.buy, status=SignalStatus.valid, score=90,
        strategy="legacy", regime="trending", expires_at=NOW + 120,
        plan=TradePlan(direction=Direction.up, entry=2000, sl=1990,
                       tp1=2010, tp2=2020, tp3=2030, sl_points=100),
    )
    runtime = SimpleNamespace(
        plans={signal.id: signal}, signals={signal.symbol: signal},
        adapter=SimpleNamespace(id="demo"), lock=RLock(),
        market=Mock(), confirmation_gate=SignalConfirmationGate(db),
    )
    runtime.market.now.return_value = NOW
    result = TradingRuntime.execute_signal(runtime, signal.id)
    assert result["ok"] is False
    assert "100-point confirmation" in result["error"]


def test_execute_signal_rechecks_quote_before_gateway_submission(db):
    gate = SignalConfirmationGate(db)
    candidate = _confirm(gate)
    signal = Signal(
        id=candidate.candidate_id, t=NOW, symbol="XAUUSD", timeframe="M1",
        broker_id="demo", action=SignalAction.buy, status=SignalStatus.valid,
        score=90, strategy="breakout_continuation", regime="trending",
        expires_at=candidate.expires_at, plan=TradePlan(
            direction=Direction.up, entry=2001, sl=1990, tp1=2010,
            tp2=2020, tp3=2030, sl_points=110),
        explanation={"signal_confirmation_v4": candidate.__dict__},
    )
    runtime = SimpleNamespace(
        plans={signal.id: signal}, signals={signal.symbol: signal},
        adapter=Mock(), market=Mock(),
        confirmation_gate=gate, strategy=Mock(), gateway=Mock(), risk=Mock(),
        predictor=SimpleNamespace(approved=True), contexts={}, lock=RLock(),
        news=Mock(), mode="manual", plan_analyses={},
    )
    runtime.adapter.id = "demo"
    runtime.adapter.health.return_value = Health.connected
    runtime.adapter.symbol_spec.return_value = SymbolSpec(
        symbol="XAUUSD", source="broker", spec_complete=True)
    runtime.market.now.return_value = NOW + 6
    runtime.market.ticker.return_value = Tick(
        t=NOW + 6, bid=2001.31, ask=2001.32, spread_points=1, last=2001.31)
    runtime.strategy.scoring = {"min_score_to_execute": 70}
    runtime.gateway.unresolved_orders.return_value = []
    runtime.gateway._account.return_value = identity(db)
    runtime.risk.state.return_value = SimpleNamespace()
    context = SimpleNamespace(
        snapshot=SimpleNamespace(
            data_quality={"ok": True}, news_lockout={},
            indicators=SimpleNamespace(atr14=1.0), price=2001.0,
            trend=[SimpleNamespace(timeframe="M5", direction=Direction.up)],
        ),
        frames={"M1": pd.DataFrame([{"t": NOW - 60, "c": 2001.0}])},
    )
    runtime.contexts["XAUUSD"] = context

    result = TradingRuntime.execute_signal(runtime, signal.id)
    assert result["ok"] is False
    assert "maximum chase" in result["error"]
    runtime.gateway.submit.assert_not_called()


def test_outdated_buy_candidate_is_rejected_after_signal_turns_to_wait(db):
    gate = SignalConfirmationGate(db)
    candidate = _confirm(gate)
    old_signal = Signal(
        id=candidate.candidate_id, t=NOW, symbol="XAUUSD", timeframe="M1",
        broker_id="demo", action=SignalAction.buy, status=SignalStatus.valid,
        score=90, strategy="breakout_continuation", regime="trending",
        expires_at=candidate.expires_at, plan=TradePlan(
            direction=Direction.up, entry=2001, sl=1990, tp1=2010,
            tp2=2020, tp3=2030, sl_points=110),
        explanation={"signal_confirmation_v4": candidate.__dict__},
    )
    current = old_signal.model_copy(update={"id": "next-scan", "action": SignalAction.wait})
    runtime = SimpleNamespace(
        plans={old_signal.id: old_signal}, signals={"XAUUSD": current},
        adapter=SimpleNamespace(id="demo"), lock=RLock(),
        market=Mock(), confirmation_gate=gate,
    )
    runtime.market.now.return_value = NOW + 6
    result = TradingRuntime.execute_signal(runtime, old_signal.id)
    assert result["ok"] is False
    assert "current actionable setup" in result["error"]
