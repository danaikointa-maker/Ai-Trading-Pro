"""API consumers must not disclose obsolete cached model approval."""
from threading import RLock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from packages.shared_schemas.models import ForecastBundle, TradeMode
from services.api_gateway.routes.signals import latest
from services.api_gateway.state import TradingRuntime


@pytest.mark.parametrize('version,approved', [('old', True), ('current', False)])
def test_signals_route_does_not_disclose_stale_approved_cache(version, approved):
    runtime = TradingRuntime.__new__(TradingRuntime)
    runtime.lock = RLock()
    runtime.active_symbol = 'XAUUSD'
    runtime.mode = TradeMode.manual
    runtime.signals, runtime.gates = {}, {}
    runtime.forecasts = {'XAUUSD': ForecastBundle(symbol='XAUUSD', generated_at=1, price=2000,
        model_version=version, model_approved=True)}
    runtime.predictor = SimpleNamespace(version='current', approved=approved, revalidate=lambda: approved)
    result = latest('XAUUSD', runtime, {})
    assert result['forecast'] is None


def test_explain_route_does_not_reuse_revoked_cache(monkeypatch):
    from services.api_gateway.routes.explain import ExplainRequest, explain

    runtime = TradingRuntime.__new__(TradingRuntime)
    runtime.lock = RLock()
    runtime.active_symbol = 'XAUUSD'
    runtime.signals, runtime.plans = {}, {}
    runtime.snapshot = Mock(return_value=None)
    runtime.forecasts = {'XAUUSD': ForecastBundle(symbol='XAUUSD', generated_at=1, price=2000,
        model_version='current', model_approved=True)}
    runtime.predictor = SimpleNamespace(version='current', approved=False, revalidate=lambda: False)
    explainer = Mock()
    explainer.explain.return_value = {}
    monkeypatch.setattr('services.api_gateway.routes.explain.TradeExplainer', lambda *args: explainer)
    monkeypatch.setattr('services.api_gateway.routes.explain.No7LocalAI', Mock())
    explain(ExplainRequest(), runtime, {})
    assert explainer.explain.call_args.args[-1] is None


def test_live_payload_does_not_reuse_revoked_cache():
    runtime = TradingRuntime.__new__(TradingRuntime)
    runtime.lock = RLock()
    runtime.replica = False
    runtime.active_symbol = 'XAUUSD'
    runtime.mode = TradeMode.manual
    runtime.contexts, runtime.signals, runtime.gates, runtime.ticks = {}, {}, {}, {}
    runtime.version, runtime.errors, runtime.training, runtime.last_reconcile = 1, [], {}, {}
    runtime.predictor = SimpleNamespace(version='current', approved=False, metrics={}, trained_at=1, notes='',
                                       revalidate=lambda: False)
    runtime.forecasts = {'XAUUSD': ForecastBundle(symbol='XAUUSD', generated_at=1, price=2000,
        model_version='current', model_approved=True)}
    runtime.market = Mock()
    runtime.market.now.return_value = 1
    runtime.market.ticker.return_value.model_dump.return_value = {}
    runtime.account = Mock(return_value={})
    runtime.risk_state = Mock()
    runtime.risk_state.return_value.model_dump.return_value = {}
    runtime.risk, runtime.notifier, runtime.gateway = Mock(), Mock(), Mock()
    runtime.risk.limits.return_value.model_dump.return_value = {}
    runtime.notifier.recent.return_value = []
    runtime.gateway.unresolved_orders.return_value = []
    runtime.registry = SimpleNamespace(get=lambda: SimpleNamespace(id='test', adapter_type='simulated_mt5'))
    runtime.position_view = Mock(return_value={})
    assert runtime.live_payload()['forecast'] is None


@pytest.mark.parametrize('approved', [True, False])
def test_current_cache_remains_available_without_recomputation(approved):
    runtime = TradingRuntime.__new__(TradingRuntime)
    runtime.lock = RLock()
    runtime.predictor = SimpleNamespace(version='current', approved=approved, revalidate=lambda: approved)
    bundle = ForecastBundle(symbol='XAUUSD', generated_at=1, price=2000,
                            model_version='current', model_approved=approved)
    runtime.forecasts = {'XAUUSD': bundle}
    assert runtime.cached_forecast('XAUUSD') is bundle
    assert runtime.forecast_for('XAUUSD') is bundle