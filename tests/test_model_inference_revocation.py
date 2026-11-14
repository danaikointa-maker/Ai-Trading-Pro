"""Revocation must stop approved horizon inference, not only change a label."""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pandas as pd

from packages.persistence.db import Database
from packages.shared_schemas.models import SymbolSpec
from services.ai_forecast.predictor import ForecastPredictor
from services.ai_forecast.registry import ModelRegistry


def test_revoked_predictor_never_calls_approved_horizon_model(tmp_path, settings, monkeypatch):
    db = Database(tmp_path / 'models.db', workspace_id='team-a')
    registry = ModelRegistry(tmp_path / 'models', db)
    predictor = ForecastPredictor(settings, registry)
    model = SimpleNamespace(approved=True, metrics={},
        predict_proba=Mock(return_value=np.array([[0.1, 0.1, 0.8]])),
        predict_quantiles=Mock(return_value={0.1: np.array([-1.]), 0.5: np.array([0.]), 0.9: np.array([1.])}))
    predictor.install_payload({'version': 'revoked', 'approved': False,
                               'models': {5: model}, 'metrics': {'approval_rule': 2}}, {})
    predictor.horizons = [5]
    monkeypatch.setattr('services.ai_forecast.predictor.inference_vector',
                        lambda frame: (np.zeros(1), frame))
    frame = pd.DataFrame({'c': np.linspace(2000., 2010., 300), 'atr': np.full(300, 2.)})
    spec = SymbolSpec(symbol='XAUUSD', digits=2, point=0.01, contract_size=100)
    try:
        bundle = predictor.forecast(frame, spec, 'XAUUSD')
        assert bundle.method == 'statistical-baseline'
        assert bundle.model_approved is False
        assert all(not h.calibrated for h in bundle.horizons)
        model.predict_proba.assert_not_called()
        model.predict_quantiles.assert_not_called()
    finally:
        db.close()