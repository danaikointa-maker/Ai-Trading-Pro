"""Decoded invalid structures cannot bypass the durable model quarantine."""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from packages.persistence.db import Database
from services.ai_forecast.registry import ModelRegistry


@pytest.mark.parametrize('damage', ['scalar', 'list', 'version', 'symbol', 'approved',
                                   'metrics', 'models', 'horizon', 'rule',
                                   'path-pair', 'path-dimensions', 'path-nonfinite'])
def test_decoded_invalid_structure_latches_generic_quarantine(tmp_path, monkeypatch, damage):
    db = Database(tmp_path / 'models.db', workspace_id='team-a')
    registry = ModelRegistry(tmp_path / 'models', db)
    arrays = {}
    if damage == 'path-pair':
        arrays = {'high_1': np.ones((2, 1))}
    elif damage == 'path-dimensions':
        arrays = {'high_1': np.ones(2), 'low_1': np.ones(2)}
    elif damage == 'path-nonfinite':
        arrays = {'high_1': np.array([[np.nan]]), 'low_1': np.ones((1, 1))}
    result = SimpleNamespace(version='owned', models={}, feature_columns=[], trained_at=1,
                             metrics={'horizons': {}, 'approval_rule': 2}, approved=True,
                             notes='fixture', samples=1,
                             path_table=SimpleNamespace(arrays=lambda: arrays))
    registry.save(result, 'XAUUSD')
    payload = {'version': 'owned', 'symbol': 'XAUUSD', 'models': {}, 'approved': True,
               'trained_at': 1, 'metrics': {'approval_rule': 2}}
    if damage == 'scalar':
        payload = 42
    elif damage == 'list':
        payload = []
    elif damage in ('version', 'symbol'):
        payload[damage] = 'foreign'
    elif damage == 'approved':
        payload['approved'] = 'false'
    elif damage == 'metrics':
        payload['metrics'] = []
    elif damage == 'models':
        payload['models'] = []
    elif damage == 'horizon':
        payload['models'] = {'bad-horizon': object()}
    elif damage == 'rule':
        payload['metrics']['approval_rule'] = 'private-invalid-rule'
    loader = Mock(return_value=payload)
    monkeypatch.setattr('services.ai_forecast.registry.joblib.load', loader)
    try:
        assert registry.load('owned') is None
        latch = db.kv_get('model.quarantine:owned')
        assert latch['reason'] == 'artifact_verification_failed'
        assert 'private' not in str(latch)
        assert registry.load('owned') is None
        loader.assert_called_once()
    finally:
        db.close()


def test_valid_horizon_and_path_arrays_still_roundtrip(tmp_path):
    from services.ai_forecast.trainer import HorizonModel

    db = Database(tmp_path / 'models.db', workspace_id='team-a')
    registry = ModelRegistry(tmp_path / 'models', db)
    model = HorizonModel(5, 1, None, [], {}, approved=True)
    arrays = {'high_1': np.ones((2, 1)), 'low_1': -np.ones((2, 1))}
    result = SimpleNamespace(version='valid', models={5: model}, feature_columns=[], trained_at=1,
                             metrics={'horizons': {}, 'approval_rule': 2}, approved=True,
                             notes='fixture', samples=2,
                             path_table=SimpleNamespace(arrays=lambda: arrays))
    try:
        registry.save(result, 'XAUUSD')
        payload, loaded = registry.load('valid')
        assert payload['approved'] is True
        assert payload['models'][5].approved is True
        np.testing.assert_array_equal(loaded['high_1'], arrays['high_1'])
        assert db.query("SELECT * FROM kv WHERE key LIKE 'model.quarantine:%'") == []
    finally:
        db.close()