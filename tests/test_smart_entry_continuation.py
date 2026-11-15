"""Decision-time replay, append-only lifecycle and read-only aggregate proposals."""
from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from packages.persistence.db import Database
from packages.persistence.position_events import PositionEventLog
from packages.shared_schemas.models import (AnalysisSnapshot, Health, RiskLimits, SignalReadiness,
                                            Signal, TradePlan, TradeRecord, Zone)
from services.execution_gateway.gateway import ExecutionGateway
from services.api_gateway.state import TradingRuntime
from services.risk_engine.engine import default_risk_state
from services.risk_engine.planner import PlanResult
from services.strategy_engine.analysis import decision_candles
from services.strategy_engine.proposals import entry_proposals


def test_historical_candles_never_include_open_or_future_bars():
    frame = pd.DataFrame([
        {"t": t, "o": 2000., "h": 2005., "l": 1995., "c": 2001., "v": 5.}
        for t in [100, 400, 700, 1000]])
    bars = decision_candles(frame, as_of=1000)
    assert [bar["t"] for bar in bars] == [100, 400, 700]
    assert all(bar["t"] + 300 <= 1000 for bar in bars)
    assert decision_candles(frame.assign(h=1990), as_of=1000) == []


def test_position_event_store_is_append_only_and_account_scoped(tmp_path):
    db = Database(tmp_path / "events.db")
    log = PositionEventLog(db)
    owner = {"broker_id": "demo", "login": "123", "server": "Demo",
             "currency": "USD", "workspace_id": db.workspace_id}
    try:
        first = log.append(broker_id="demo", ticket="T-1", actor="user", kind="modify",
                           status="requested", account_identity=owner, detail={"sl": 1990})
        log.append(broker_id="demo", ticket="T-1", actor="user", kind="modify",
                   status="accepted_unverified", account_identity=owner, detail={"sl": 1990})
        rows = log.for_ticket(broker_id="demo", ticket="T-1", account_identity=owner)
        assert len(rows) == 2 and rows[0]["event_id"] == first
        assert rows[0]["order_attribution"] == "unresolved"
        assert log.for_ticket(broker_id="other", ticket="T-1", account_identity=owner) == []
        with pytest.raises(ValueError, match="identity"):
            log.append(broker_id="other", ticket="T-1", actor="user", kind="close",
                       status="requested", account_identity=owner, detail={})
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE position_events SET status='confirmed'")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM position_events")
    finally:
        db.close()


def test_event_link_uses_unique_broker_ticket_not_unrelated_signal(tmp_path):
    db = Database(tmp_path / "ticket.db")
    owner = {"broker_id": "demo", "login": "123", "server": "Demo",
             "currency": "USD", "workspace_id": db.workspace_id}
    try:
        with db.cursor() as cur:
            cur.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?)", (
                "ORD-1", 1.0, "idem-1", "filled", "demo", "XAUUSD",
                json.dumps({"result": {"ticket": "T-3"}})))
            cur.execute("INSERT INTO pre_order_snapshots VALUES(?,?,?,?,?,?)", (
                "ORD-1", "demo", "sig-1", "XAUUSD", 1.0,
                json.dumps({"schema_version": 1, "account_identity": owner,
                            "request": {"broker_id": "demo", "symbol": "XAUUSD"}})))
        ledger = PositionEventLog(db)
        assert ledger.linked_order("demo", "T-3", owner) == "ORD-1"
        assert ledger.linked_order("demo", "T-3", {**owner, "login": "other-account"}) is None
        ledger.append(broker_id="demo", ticket="T-3", actor="user", kind="modify",
                      status="requested", account_identity=owner, detail={"sl": 1995})
        assert ledger.for_ticket(broker_id="demo", ticket="T-3", account_identity=owner)[0]["order_id"] == "ORD-1"
    finally:
        db.close()


def test_management_revision_records_request_before_broker_io(tmp_path):
    db = Database(tmp_path / "modifications.db")
    adapter = Mock()
    adapter.id = "demo"
    adapter.account_info.return_value = SimpleNamespace(
        broker_id="demo", login="123", server="Demo", currency="USD")
    adapter.health.return_value = Health.connected
    gateway = ExecutionGateway(SimpleNamespace(execution={}), db)

    def modify(*_args, **_kwargs):
        assert db.query_one("SELECT kind,status FROM position_events")["status"] == "requested"
        return True

    adapter.modify_position.side_effect = modify
    try:
        assert gateway.modify(adapter, "T-2", sl=1995, reason="trailing") is True
        rows = PositionEventLog(db).for_ticket(
            broker_id="demo", ticket="T-2", account_identity=gateway._assert_account(adapter))
        assert [e["status"] for e in rows] == ["requested", "accepted_unverified"]
    finally:
        db.close()


def test_partial_close_is_not_mistaken_for_fully_closed_trade(tmp_path):
    db = Database(tmp_path / "partial.db")
    adapter = Mock()
    adapter.id = "demo"
    adapter.account_info.return_value = SimpleNamespace(
        broker_id="demo", login="123", server="Demo", currency="USD")
    adapter.close_position.return_value = TradeRecord(
        ticket="T-4", symbol="XAUUSD", direction="up", volume=0.04,
        entry=2000, exit=2004, opened_at=1, closed_at=2,
        points=400, gross_pnl=16, costs=1, pnl=15, broker_id="demo")
    adapter.positions.return_value = [SimpleNamespace(ticket="T-4")]
    gateway = ExecutionGateway(SimpleNamespace(execution={}), db)
    try:
        result = gateway.close(adapter, "T-4", volume=0.04, reason="tp1")
        assert result["ok"] is True
        assert db.query("SELECT * FROM trades") == []
        owner = gateway._assert_account(adapter)
        events = PositionEventLog(db).for_ticket(broker_id="demo", ticket="T-4", account_identity=owner)
        assert [event["status"] for event in events] == ["requested", "partial_realized"]
    finally:
        db.close()


def _context():
    spec = {"symbol": "XAUUSD", "point": 0.01, "min_lot": 0.01, "max_lot": 1.0}
    zones = [Zone(id=f"z-{i}", kind="support", low=1999.0 - i,
                  high=2000.0 - i, mid=1999.5 - i, strength=0.9,
                  quality="high", status="confirmed") for i in range(2)]
    analysis = AnalysisSnapshot(symbol="XAUUSD", timeframe="M5", broker_id="demo", price=2000,
                                server_time=1000, spec=spec, supports=zones, zones=zones)
    analysis.indicators.atr14 = 3
    analysis.indicators.atr_points = 300
    signal = Signal(id="P-SIG", t=1000, symbol="XAUUSD", timeframe="M5", broker_id="demo",
                    action="BUY", status="valid", score=80, strategy="zones", regime="trend_up",
                    plan=TradePlan(direction="up", entry=2000, sl=1990,
                                   tp1=2010, tp2=2020, tp3=2030, sl_points=1000, lot=0.1))
    return signal, analysis


def test_three_proposals_never_exceed_aggregate_budget_or_create_orders():
    signal, analysis = _context()

    class FakePlanner:
        cfg = {}

        def build(self, ctx):
            return PlanResult(plan=TradePlan(direction=ctx.direction, entry=ctx.entry,
                sl=ctx.entry - 5, tp1=ctx.entry + 10, tp2=ctx.entry + 20,
                tp3=ctx.entry + 30, sl_points=500, lot=0.1,
                risk_amount=round(ctx.equity * ctx.risk_pct / 100, 2)), blockers=[], notes=[])

    risk = default_risk_state(10000)
    limits = RiskLimits(max_open_trades=3, max_open_per_symbol=3,
                        max_exposure_lots=0.3, risk_per_trade_pct=1.5)
    options = entry_proposals(signal, analysis, FakePlanner(), limits, risk, 10000, 20, gate_allow=True)
    assert options["executable"] is False
    assert 1 <= len(options["proposals"]) <= 3
    assert sum(p["plan"]["risk_amount"] for p in options["proposals"]) <= 150
    assert options["aggregate_lots"] <= 0.3
    blocked = entry_proposals(signal, analysis, FakePlanner(), limits, risk, 10000, 20,
                              gate_allow=False)
    assert blocked["proposals"] == []
    risk.open_trades = 3
    assert entry_proposals(signal, analysis, FakePlanner(), limits, risk, 10000, 20,
                           gate_allow=True)["proposals"] == []
    risk.open_trades = 0
    risk.exposure_pct = limits.max_leverage_notional_x_equity * 100
    assert entry_proposals(signal, analysis, FakePlanner(), limits, risk, 10000, 20,
                           gate_allow=True)["proposals"] == []


def test_blocked_readiness_deduplicates_after_restart(tmp_path):
    db = Database(tmp_path / "readiness.db")

    class Recorder:
        def __init__(self):
            self.calls = []

        def emit(self, *args, **kwargs):
            self.calls.append((args, kwargs))

    signal, _ = _context()
    signal.readiness = SignalReadiness.blocked
    recorder = Recorder()
    try:
        initial = SimpleNamespace(db=db, _last_readiness={}, notifier=recorder)
        TradingRuntime._maybe_alert_readiness(initial, signal)
        assert len(recorder.calls) == 1
        assert db.kv_get("readiness-state:demo:XAUUSD")["state"] == "BLOCKED"
        restarted = SimpleNamespace(db=db, _last_readiness={}, notifier=recorder)
        TradingRuntime._maybe_alert_readiness(restarted, signal)
        assert len(recorder.calls) == 1
        signal.readiness = SignalReadiness.wait
        TradingRuntime._maybe_alert_readiness(restarted, signal)
        assert len(recorder.calls) == 2
    finally:
        db.close()
