"""Loaded model consumers recheck registry authority without executable reloads."""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from packages.persistence.db import Database
from packages.shared_schemas.models import SymbolSpec
from services.ai_forecast.predictor import ForecastPredictor
from services.ai_forecast.registry import ModelRegistry
from services.ai_forecast.pathprob import PathProbabilityTable


@pytest.mark.parametrize('consumer', ['forecast', 'path', 'status', 'cache'])
@pytest.mark.parametrize('change', ['revoke', 'quarantine', 'tamper'])
def test_loaded_model_stops_inference_after_registry_authority_changes(tmp_path, monkeypatch, change, consumer):
    settings = SimpleNamespace(ai={'horizons_minutes': [5]},
                               risk_cfg=lambda: {'targets': {'min_points': 10, 'max_points': 1000}})
    db = Database(tmp_path / 'models.db', workspace_id='team-a')
    registry = ModelRegistry(tmp_path / 'models', db)
    result = SimpleNamespace(version='owned', models={}, feature_columns=[], trained_at=1,
                             metrics={'horizons': {}, 'approval_rule': 2}, approved=True,
                             notes='fixture', samples=1, path_table=PathProbabilityTable())
    folder = registry.save(result, 'XAUUSD')
    predictor = ForecastPredictor(settings, registry)
    model = SimpleNamespace(approved=True, metrics={},
        predict_proba=Mock(return_value=np.array([[0.1, 0.1, 0.8]])),
        predict_quantiles=Mock(return_value={0.1: np.array([-1.]), 0.5: np.array([0.]), 0.9: np.array([1.])}))
    predictor.models = {5: model}
    predictor.horizons = [5]
    table = SimpleNamespace(samples=10, p_tp_before_sl=Mock(return_value=(0.9, 10)))
    predictor.path_table = table
    if change == 'revoke':
        registry.approve('owned', False)
    elif change == 'quarantine':
        registry._quarantine('owned')
    else:
        (folder / 'metadata.json').write_bytes(b'tampered')
    monkeypatch.setattr('services.ai_forecast.predictor.inference_vector',
                        lambda frame: (np.zeros(1), frame))
    frame = pd.DataFrame({'c': np.linspace(2000., 2010., 300), 'atr': np.full(300, 2.)})
    spec = SymbolSpec(symbol='XAUUSD', digits=2, point=0.01, contract_size=100)
    try:
        if consumer == 'cache':
            from threading import RLock
            from packages.shared_schemas.models import ForecastBundle
            from services.api_gateway.state import TradingRuntime

            runtime = TradingRuntime.__new__(TradingRuntime)
            runtime.lock = RLock()
            runtime.predictor = predictor
            runtime.forecasts = {'XAUUSD': ForecastBundle(symbol='XAUUSD', generated_at=1,
                price=2000, model_version='owned', model_approved=True)}
            assert runtime.cached_forecast('XAUUSD') is None
            return
        if consumer == 'path':
            assert predictor.p_tp_before_sl(10, 10, 5, 0.8, 100) == (0.0, 0)
            table.p_tp_before_sl.assert_not_called()
            return
        if consumer == 'status':
            status = predictor.status()
            assert status is None or status.approved is False
            return
        bundle = predictor.forecast(frame, spec, 'XAUUSD')
        assert bundle.model_approved is False
        assert bundle.method == 'statistical-baseline'
        model.predict_proba.assert_not_called()
        model.predict_quantiles.assert_not_called()
    finally:
        db.close()


def test_unchanged_registered_authority_does_not_decode_again(tmp_path, monkeypatch):
    db = Database(tmp_path / 'models.db', workspace_id='team-a')
    registry = ModelRegistry(tmp_path / 'models', db)
    registry.save(SimpleNamespace(version='valid', models={}, feature_columns=[], trained_at=1,
        metrics={'approval_rule': 2}, approved=True, notes='', samples=1,
        path_table=PathProbabilityTable()), 'XAUUSD')
    predictor = ForecastPredictor(SimpleNamespace(ai={}), registry)
    decoder = Mock(side_effect=AssertionError('must not decode during authority check'))
    monkeypatch.setattr('services.ai_forecast.registry.joblib.load', decoder)
    try:
        assert predictor.revalidate() is True
        assert predictor.approved is True
        decoder.assert_not_called()
    finally:
        db.close()