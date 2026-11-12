"""Registered bytes still require a successful decode before model acceptance."""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from packages.persistence.db import Database
from services.ai_forecast.registry import ModelRegistry


@pytest.mark.parametrize('decoder', ['joblib', 'numpy'])
def test_decode_failure_latches_quarantine_without_exposing_raw_error(tmp_path, monkeypatch, decoder):
    db = Database(tmp_path / 'models.db', workspace_id='team-a')
    registry = ModelRegistry(tmp_path / 'models', db)
    result = SimpleNamespace(version='owned', models={}, feature_columns=[], trained_at=1,
                             metrics={'horizons': {}, 'approval_rule': 2}, approved=True,
                             notes='fixture', samples=1,
                             path_table=SimpleNamespace(arrays=lambda: {'x': np.array([1.])}))
    registry.save(result, 'XAUUSD')
    target = 'services.ai_forecast.registry.joblib.load' if decoder == 'joblib' else 'services.ai_forecast.registry.np.load'
    failing = Mock(side_effect=ValueError('private decoder details at C:/private/model'))
    monkeypatch.setattr(target, failing)
    try:
        assert registry.load('owned') is None
        record = db.kv_get('model.quarantine:owned')
        assert record['reason'] == 'artifact_verification_failed'
        assert 'private' not in str(record)
        assert registry.load('owned') is None
        failing.assert_called_once()
        assert registry.approve('owned') is False
        assert registry.list()[0].approved is False
    finally:
        db.close()