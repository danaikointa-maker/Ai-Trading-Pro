"""Unavailable risk state must never look like permission to trade."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from packages.shared_schemas.models import Health
from services.api_gateway.state import TradingRuntime


@pytest.fixture
def isolated_runtime():
    runtime = TradingRuntime.__new__(TradingRuntime)
    runtime.market = SimpleNamespace(now=lambda: 123.0)
    adapter = Mock()
    adapter.account_info.return_value = SimpleNamespace(equity=10000, health=Health.connected)
    runtime.registry = SimpleNamespace(get=lambda: adapter)
    runtime.risk = Mock()
    runtime.risk.state.side_effect = RuntimeError("risk storage unavailable")
    runtime._log_error = Mock()
    return runtime


def test_unavailable_risk_state_is_visibly_blocked(isolated_runtime):
    state = isolated_runtime.risk_state()
    assert state.kill_switch_active is True
    assert "unavailable" in state.kill_switch_reason.lower()
    isolated_runtime._log_error.assert_called_once()


def test_decision_cycle_uses_blocked_state_on_failure(isolated_runtime):
    import threading

    isolated_runtime.symbols = lambda: ["XAUUSD"]
    isolated_runtime.lock = threading.RLock()
    isolated_runtime._decide_symbol = Mock()
    isolated_runtime._decision_cycle()
    state = isolated_runtime._decide_symbol.call_args.args[3]
    assert state.kill_switch_active is True
    assert "unavailable" in state.kill_switch_reason.lower()


def test_healthy_risk_state_is_not_replaced(isolated_runtime):
    expected = object()
    isolated_runtime.risk.state.side_effect = None
    isolated_runtime.risk.state.return_value = expected
    assert isolated_runtime.risk_state() is expected
    isolated_runtime._log_error.assert_not_called()