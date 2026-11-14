"""Readiness is explanatory and cannot grant execution authority."""
from packages.shared_schemas.models import (
    Direction,
    Signal,
    SignalAction,
    SignalReadiness,
    SignalStatus,
    TradePlan,
)
from services.strategy_engine.readiness import assess_readiness


def _signal(action: SignalAction = SignalAction.wait, **changes) -> Signal:
    values = dict(
        id="S1", t=1000, symbol="XAUUSD", timeframe="M5", broker_id="sim",
        action=action, status=SignalStatus.weak, score=55.0, strategy="trend_pullback",
        regime="trending", expires_at=1180,
    )
    values.update(changes)
    return Signal(**values)


def _plan() -> TradePlan:
    return TradePlan(direction=Direction.up, entry=2000, sl=1990, tp1=2010,
                     tp2=2020, tp3=2030, sl_points=100)


def test_ready_requires_both_actionable_plan_and_gate():
    signal = _signal(SignalAction.buy, plan=_plan())
    before = signal.model_dump()
    assessed = assess_readiness(signal, gate_allow=True, was_tradable=True, as_of=1000)
    assert assessed.state == SignalReadiness.ready
    assert signal.model_dump() == before
    assert assess_readiness(signal, gate_allow=False, was_tradable=True).state == SignalReadiness.blocked


def test_gate_rejected_buy_remains_blocked_after_action_rewritten_to_wait():
    signal = _signal(SignalAction.wait, plan=_plan(), blockers=["margin limit"])
    assert assess_readiness(signal, gate_allow=False, was_tradable=True).state == SignalReadiness.blocked


def test_safety_veto_takes_priority_over_waiting_entry():
    signal = _signal(blockers=["news lockout"], blocker_codes=["news_lockout"])
    assert assess_readiness(signal, gate_allow=False, as_of=1001).state == SignalReadiness.blocked


def test_incomplete_entry_waits_but_no_direction_scans():
    waiting = _signal(blockers=["entry conditions missing"], blocker_codes=["entry_conditions"])
    assert assess_readiness(waiting, gate_allow=True).state == SignalReadiness.wait
    scanning = _signal(SignalAction.no_trade, blockers=["no direction"],
                       blocker_codes=["no_direction"])
    assert assess_readiness(scanning, gate_allow=True).state == SignalReadiness.scanning


def test_expiry_uses_supplied_market_time_not_wall_clock():
    signal = _signal(SignalAction.buy, plan=_plan())
    assert assess_readiness(signal, gate_allow=True, as_of=1179).state == SignalReadiness.ready
    assert assess_readiness(signal, gate_allow=True, as_of=1180).state == SignalReadiness.expired
    assert assess_readiness(signal, gate_allow=True).state == SignalReadiness.ready


def test_existing_signal_payload_without_readiness_remains_compatible():
    signal = _signal()
    payload = signal.model_dump(exclude={"readiness", "readiness_reason"})
    restored = Signal.model_validate(payload)
    assert restored.readiness is None
    assert restored.readiness_reason == ""
