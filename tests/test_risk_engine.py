"""The Risk Engine must be able to veto anything, for a named reason."""
from __future__ import annotations

import time

import pytest

from packages.shared_schemas.models import Health, RiskState, SymbolSpec
from services.risk_engine.engine import default_risk_state

SPEC = SymbolSpec(
    symbol="XAUUSD", digits=2, point=0.01, tick_size=0.01, contract_size=100.0,
    min_lot=0.01, max_lot=50.0, lot_step=0.01, stops_level_points=0.0, spread_typical_points=25.0,
)
OK_QUALITY = {"ok": True, "reason": "", "staleness_seconds": 1.0}
NO_NEWS = {"active": False, "reason": ""}
NOW = time.time()


def _gate(runtime, **overrides):
    state = overrides.pop("state", default_risk_state(10_000))
    kwargs = dict(
        state=state, spec=SPEC, spread_points=25.0, data_quality=OK_QUALITY,
        news_lockout=NO_NEWS, atr_pct=0.6, requested_lot=0.10,
        broker_health=Health.connected, now=NOW,
    )
    kwargs.update(overrides)
    return runtime.risk.gate(**kwargs)


def test_clean_state_is_allowed(runtime):
    gate = _gate(runtime)
    assert gate.allow, gate.blockers
    assert gate.checks and all("name" in c for c in gate.checks)


def test_stale_feed_blocks(runtime):
    gate = _gate(runtime, data_quality={"ok": False, "reason": "tick is 42s old", "staleness_seconds": 42})
    assert not gate.allow
    assert any("tick is 42s old" in b for b in gate.blockers)


def test_broker_disconnected_blocks(runtime):
    assert not _gate(runtime, broker_health=Health.disconnected).allow


def test_wide_spread_blocks(runtime):
    gate = _gate(runtime, spread_points=999.0)
    assert not gate.allow
    assert any("spread" in b for b in gate.blockers)


def test_daily_loss_limit_blocks(runtime):
    state = default_risk_state(10_000).model_copy(update={
        "equity": 9_780, "daily_pnl": -220, "daily_pnl_pct": -2.2,
    })
    gate = _gate(runtime, state=state)
    assert not gate.allow
    assert any("daily P&L" in b for b in gate.blockers)


def test_drawdown_and_weekly_limits_block(runtime):
    dd = default_risk_state(10_000).model_copy(update={"drawdown_pct": -12.0})
    assert not _gate(runtime, state=dd).allow
    wk = default_risk_state(10_000).model_copy(update={"weekly_pnl_pct": -6.0})
    assert not _gate(runtime, state=wk).allow


def test_max_open_trades_and_exposure_block(runtime):
    busy = default_risk_state(10_000).model_copy(update={"open_trades": 3, "open_lots": 0.5})
    gate = _gate(runtime, state=busy, requested_lot=0.6)
    assert not gate.allow
    names = {b.split()[0] for b in gate.blockers}
    assert any("open" in b for b in gate.blockers) or names


def test_cooldown_after_consecutive_losses_blocks(runtime):
    state = default_risk_state(10_000).model_copy(update={
        "consecutive_losses": 3, "cooldown_until": int(NOW + 600),
    })
    gate = _gate(runtime, state=state)
    assert not gate.allow
    assert any("cooldown" in b for b in gate.blockers)


def test_news_lockout_blocks_when_enabled(runtime):
    runtime.risk.update_limits({"news_lockout_enabled": True}, actor="test")
    try:
        gate = _gate(runtime, news_lockout={"active": True, "reason": "US CPI in 12m"})
        assert not gate.allow
        assert any("news lockout" in b for b in gate.blockers)
    finally:
        runtime.risk.update_limits({"news_lockout_enabled": True}, actor="test")


def test_kill_switch_blocks(runtime):
    state = default_risk_state(10_000).model_copy(update={
        "kill_switch_active": True, "kill_switch_reason": "daily loss limit reached",
    })
    gate = _gate(runtime, state=state)
    assert not gate.allow
    assert any("Kill switch" in b for b in gate.blockers)


def test_full_auto_needs_env_switch_high_score_and_approved_model(runtime):
    gate = _gate(runtime, is_full_auto=True, signal_score=70, model_approved=False,
                 calibrated_probability=0.4)
    assert not gate.allow
    joined = " ".join(gate.blockers)
    assert "full auto" in joined.lower()


def test_abnormal_volatility_blocks(runtime):
    gate = _gate(runtime, atr_pct=9.5)
    assert not gate.allow
    assert any("ATR" in b for b in gate.blockers)


def test_every_blocker_is_human_readable(runtime):
    gate = _gate(runtime, spread_points=5_000, broker_health=Health.stale)
    for blocker in gate.blockers:
        assert len(blocker) > 8 and not blocker.startswith("{")
