"""Approving a signal must never bypass the gate.

`POST /api/signals/{id}/approve` looks like a manual override button, so the risk
is structural: someone presses it on a blocked setup and the platform executes
anyway. Execution re-runs the whole gate and refuses when it says no — these
tests pin that, plus the other refusals (expired, already executed, no plan,
nothing to trade) and the fact that a refusal leaves no order behind.
"""
from __future__ import annotations

import pytest

from packages.shared_schemas.models import (Direction, OrderState, PartialTarget, Signal,
                                            SignalAction, SignalStatus, TradePlan)


def _plan(direction=Direction.up, entry=2000.0) -> TradePlan:
    sign = 1.0 if direction is Direction.up else -1.0
    return TradePlan(
        direction=direction,
        entry=entry,
        sl=entry - sign * 5.0,
        tp1=entry + sign * 10.0,
        tp2=entry + sign * 20.0,
        tp3=entry + sign * 30.0,
        sl_points=500.0,
        tp_points=[1000.0, 2000.0, 3000.0],
        lot=0.1,
        risk_amount=50.0,
        risk_pct=0.5,
        reward_risk=2.0,
        reward_risk_net=1.9,
        estimated_cost=1.0,
        expected_value=1.5,
        p_tp_before_sl=0.55,
        partials=[PartialTarget(level=1, price=entry + sign * 10.0, points=1000.0,
                                close_pct=50.0, volume=0.05)],
    )


def _signal(runtime, **overrides) -> Signal:
    base = dict(
        id=overrides.pop("id", "TEST-SIG-1"),
        t=int(runtime.market.now()),
        symbol="XAUUSD",
        timeframe="5m",
        broker_id=runtime.adapter.id,
        action=SignalAction.buy,
        status=SignalStatus.valid,
        score=70.0,
        strategy="trend_pullback",
        regime="trend_up",
        plan=_plan(),
        mode=runtime.mode,
        expires_at=int(runtime.market.now()) + 600,
    )
    base.update(overrides)
    return Signal(**base)


def _order_count(runtime) -> int:
    row = runtime.db.query_one("SELECT COUNT(*) AS c FROM orders")
    return int(row["c"])


@pytest.fixture
def registered(runtime):
    """Put a signal where `execute_signal` looks for it, and clean up after."""
    created: list[str] = []

    def _register(signal: Signal) -> Signal:
        with runtime.lock:
            runtime.plans[signal.id] = signal
        created.append(signal.id)
        return signal

    yield _register
    with runtime.lock:
        for sid in created:
            runtime.plans.pop(sid, None)


def test_unknown_signal_is_refused(runtime):
    result = runtime.execute_signal("NO-SUCH-SIGNAL")
    assert result["ok"] is False
    assert "not found" in result["error"]


@pytest.mark.parametrize("failure", [RuntimeError, ValueError])
def test_risk_state_failure_refuses_before_gateway(runtime, registered, monkeypatch, failure):
    from unittest.mock import Mock

    sig = registered(_signal(runtime, id=f"TEST-RISK-FAIL-{failure.__name__}", score=75.0))
    monkeypatch.setattr(runtime.risk, "state", Mock(side_effect=failure("risk storage unavailable")))
    submit = Mock()
    monkeypatch.setattr(runtime.gateway, "submit", submit)
    result = runtime.execute_signal(sig.id)
    assert result["ok"] is False
    assert "risk state unavailable" in result["error"].lower()
    submit.assert_not_called()


def test_signal_without_a_plan_is_refused(runtime, registered):
    result = runtime.execute_signal(registered(_signal(runtime, plan=None)).id)
    assert result["ok"] is False
    assert "no trade plan" in result["error"]


@pytest.mark.parametrize("failure", ["positions", "spec", "rate"])
def test_exposure_failure_refuses_before_gateway(runtime, registered, monkeypatch, failure):
    from types import SimpleNamespace
    from unittest.mock import Mock

    sig = registered(_signal(runtime, id=f"TEST-EXPOSURE-{failure}", score=75.0))
    if failure == "positions":
        monkeypatch.setattr(runtime.adapter, "positions", Mock(side_effect=RuntimeError("unavailable")))
    else:
        monkeypatch.setattr(runtime.adapter, "positions", lambda: [SimpleNamespace(
            symbol="XAUUSD", volume=0.1, current_price=2000.0, unrealized=0.0)])
        if failure == "spec":
            monkeypatch.setattr(runtime.adapter, "symbol_spec", Mock(side_effect=RuntimeError("unavailable")))
        else:
            spec = runtime.adapter.symbol_spec("XAUUSD").model_copy(update={
                "profit_currency": "JPY", "rate_source": "unknown"})
            monkeypatch.setattr(runtime.adapter, "symbol_spec", lambda _: spec)
    submit = Mock()
    monkeypatch.setattr(runtime.gateway, "submit", submit)
    kill_before = runtime.db.kv_get("kill_switch", None)
    result = runtime.execute_signal(sig.id)
    assert result["ok"] is False
    assert "risk state unavailable" in result["error"]
    submit.assert_not_called()
    assert runtime.db.kv_get("kill_switch", None) == kill_before


def test_non_actionable_signal_is_refused(runtime, registered):
    sig = registered(_signal(runtime, action=SignalAction.no_trade))
    result = runtime.execute_signal(sig.id)
    assert result["ok"] is False
    assert "not actionable" in result["error"]


def test_expired_signal_is_refused(runtime, registered):
    sig = registered(_signal(runtime, expires_at=int(runtime.market.now()) - 1))
    result = runtime.execute_signal(sig.id)
    assert result["ok"] is False
    assert "expired" in result["error"]


def test_signal_cannot_execute_twice(runtime, registered):
    sig = registered(_signal(runtime, executed_order_id="ORD-EXISTING"))
    result = runtime.execute_signal(sig.id)
    assert result["ok"] is False
    assert "already executed" in result["error"]
    assert result["order_id"] == "ORD-EXISTING"


def test_weak_signal_cannot_be_approved_by_hand(runtime, registered):
    """A signal under the execution threshold stays unactionable even when a human asks."""
    before = _order_count(runtime)
    sig = registered(_signal(runtime, id="TEST-SIG-WEAK", score=10.0, status=SignalStatus.weak))
    result = runtime.execute_signal(sig.id, actor="demo@no7.ai")
    assert result["ok"] is False
    assert "execution threshold" in result["error"], result
    assert _order_count(runtime) == before


def test_gate_rejection_cannot_be_overridden_by_approve(runtime, registered, monkeypatch):
    """The approve button re-runs the gate; a blocked gate means no order, full stop."""
    from services.risk_engine.engine import RiskGate

    def blocked(*_args, **_kwargs):
        gate = RiskGate(allow=True)
        gate.add("spread", False, "spread 41.0 pts above the 35.0 ceiling")
        return gate

    monkeypatch.setattr(runtime.strategy, "evaluate_gate", blocked)
    before = _order_count(runtime)
    sig = registered(_signal(runtime, id="TEST-SIG-BLOCKED", score=75.0))
    result = runtime.execute_signal(sig.id, actor="demo@no7.ai")
    assert result["ok"] is False
    assert "risk gate" in result["error"], result
    assert "spread" in " ".join(result["blockers"])
    assert _order_count(runtime) == before, "a rejected signal must not leave an order"


def test_broken_plan_never_becomes_a_position(runtime, registered):
    """A stale plan (target on the wrong side of price) is refused by the gateway."""
    before = len(runtime.gateway.open_positions())
    # entry/TP carry volume/price from a different price regime on purpose
    sig = registered(_signal(runtime, id="TEST-SIG-STALE", score=75.0))
    result = runtime.execute_signal(sig.id, actor="demo@no7.ai")
    assert result["ok"] is False
    assert "wrong side" in result["error"] or "rejected" in str(result.get("order", {})), result
    # An adapter exception is not a broker rejection receipt. Keep the attempt
    # unresolved/reserved even when this paper adapter reports invalid geometry.
    assert result["order"]["status"] == OrderState.pending, result
    assert len(runtime.gateway.open_positions()) == before


def test_approve_endpoint_surfaces_the_refusal(client, token, runtime, registered):
    """The UI gets a 400 with the reason, not a silent no-op."""
    sig = registered(_signal(runtime, id="TEST-SIG-API-WEAK", score=10.0, status=SignalStatus.weak))
    res = client.post(f"/api/signals/{sig.id}/approve",
                      headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 400
    assert "execution threshold" in res.json()["detail"]["error"]
