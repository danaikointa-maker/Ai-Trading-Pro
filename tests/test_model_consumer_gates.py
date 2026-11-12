"""Model consumers must not retain revoked or unverified research evidence."""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from packages.persistence.db import Database
from services.ai_forecast.pathprob import PathProbabilityTable
from services.ai_forecast.predictor import ForecastPredictor
from services.ai_forecast.registry import ModelRegistry
from services.api_gateway.routes.analysis import approve
from services.api_gateway.state import TradingRuntime


@pytest.fixture
def predictor(tmp_path, settings):
    db = Database(tmp_path / 'models.db', workspace_id='team-a')
    registry = ModelRegistry(tmp_path / 'models', db)
    yield ForecastPredictor(settings, registry)
    db.close()


def test_revoked_path_table_is_not_consulted(predictor):
    table = SimpleNamespace(samples=100, p_tp_before_sl=Mock(return_value=(0.9, 100)))
    predictor.path_table = table
    predictor.approved = False
    assert predictor.p_tp_before_sl(10, 10, 5, 0.8, 100) == (0.0, 0)
    table.p_tp_before_sl.assert_not_called()


def test_install_empty_arrays_cannot_retain_previous_path_table(predictor):
    predictor.path_table = PathProbabilityTable(samples=100)
    predictor.install_payload({'version': 'next', 'approved': False, 'models': {},
                               'metrics': {'approval_rule': 2}}, {})
    assert predictor.path_table is None


def test_training_install_revalidates_persisted_artifacts(predictor, monkeypatch):
    result = SimpleNamespace(version='fresh', models={}, feature_columns=[], trained_at=1,
                             metrics={'horizons': {}, 'approval_rule': 2}, approved=True,
                             notes='fixture', samples=1, path_table=PathProbabilityTable())
    save = predictor.registry.save

    def corrupt_after_save(*args, **kwargs):
        folder = save(*args, **kwargs)
        (folder / 'models.joblib').write_bytes(b'changed after registration')
        return folder

    monkeypatch.setattr(predictor.registry, 'save', corrupt_after_save)
    predictor.install(result, 'XAUUSD')
    assert predictor.approved is False
    assert predictor.version == 'baseline-statistical'
    assert predictor.registry.load('fresh') is None


@pytest.mark.parametrize('approved', [True, False])
def test_approval_change_discards_all_cached_forecasts(approved):
    runtime = SimpleNamespace(model_registry=Mock(), predictor=Mock(),
                              forecasts={'XAUUSD': object(), 'EURUSD': object()})
    import threading
    runtime.lock = threading.RLock()
    runtime.model_registry.approve.return_value = True
    approve('owned', {'approved': approved}, runtime, {'email': 'researcher'})
    assert runtime.forecasts == {}


def test_approved_path_table_remains_available(predictor):
    predictor.registry.save(SimpleNamespace(version='approved-path', models={}, feature_columns=[],
        trained_at=1, metrics={'approval_rule': 2}, approved=True, notes='', samples=2,
        path_table=PathProbabilityTable()), 'XAUUSD')
    predictor.load_latest()
    table = PathProbabilityTable.from_arrays({'high_1': np.ones((2, 1)),
                                             'low_1': -np.ones((2, 1))})
    predictor.path_table = table
    probability, count = predictor.p_tp_before_sl(10, 10, 5, 0.8, 100)
    assert 0.0 <= probability <= 1.0
    assert count == 2


def test_training_worker_uses_verified_install_and_invalidates_cache(predictor, monkeypatch):
    import threading

    result = SimpleNamespace(version='fresh-worker', models={}, feature_columns=[], trained_at=1,
                             metrics={'horizons': {}, 'approval_rule': 2}, approved=True,
                             notes='fixture', samples=1, path_table=PathProbabilityTable())
    runtime = SimpleNamespace(training={}, predictor=predictor, model_registry=predictor.registry,
                              trainer=SimpleNamespace(train=lambda *args: result),
                              feed=SimpleNamespace(warm_history=lambda *args: [1]),
                              forecasts={'XAUUSD': object()}, lock=threading.RLock(),
                              notifier=Mock(), _log_error=Mock())
    save = predictor.registry.save

    def corrupt_after_save(*args, **kwargs):
        folder = save(*args, **kwargs)
        (folder / 'models.joblib').write_bytes(b'changed after registration')
        return folder

    monkeypatch.setattr(predictor.registry, 'save', corrupt_after_save)
    monkeypatch.setattr('services.api_gateway.state.threading.Thread',
                        lambda target, **kwargs: SimpleNamespace(start=target))
    assert TradingRuntime.train_async(runtime, 'XAUUSD', force=True)['ok']
    assert runtime.training['state'] == 'done'
    assert predictor.approved is False
    assert runtime.model_approved is False
    assert runtime.forecasts == {}


@pytest.mark.parametrize('value', ['false', 'true', 0, 1, None, [], {}])
def test_approval_requires_explicit_boolean(value):
    from fastapi import HTTPException
    import threading

    runtime = SimpleNamespace(model_registry=Mock(), predictor=Mock(),
                              forecasts={}, lock=threading.RLock())
    with pytest.raises(HTTPException) as exc:
        approve('owned', {'approved': value}, runtime, {'email': 'researcher'})
    assert exc.value.status_code == 422
    runtime.model_registry.approve.assert_not_called()


@pytest.mark.parametrize('version,approved', [('old', True), ('current', False)])
def test_forecast_reader_refuses_stale_approved_cache(version, approved):
    import threading

    cached = SimpleNamespace(model_version=version, model_approved=True)
    runtime = SimpleNamespace(lock=threading.RLock(), forecasts={'XAUUSD': cached},
                              predictor=SimpleNamespace(version='current', approved=approved,
                                                        revalidate=lambda: approved),
                              analysis=SimpleNamespace(snapshot=Mock(side_effect=ValueError('no data'))))
    assert TradingRuntime.forecast_for(runtime, 'XAUUSD') is None
    assert runtime.forecasts == {}