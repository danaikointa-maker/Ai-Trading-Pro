"""Model approval disclosure must not advertise unverified artifacts as approved."""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from packages.persistence.db import Database
from services.ai_forecast.registry import ModelRegistry


@pytest.fixture
def registry(tmp_path):
    db = Database(tmp_path / 'models.db', workspace_id='team-a')
    registry = ModelRegistry(tmp_path / 'models', db)
    result = SimpleNamespace(version='owned', models={}, feature_columns=[], trained_at=1,
                             metrics={'horizons': {}, 'approval_rule': 2}, approved=True,
                             notes='fixture', samples=1,
                             path_table=SimpleNamespace(arrays=lambda: {'x': np.array([1.])}))
    registry.save(result, 'XAUUSD')
    yield registry
    db.close()


def test_damaged_artifact_is_not_listed_as_approved_or_deserialized(registry, monkeypatch):
    artifact = registry.model_dir / 'owned' / 'models.joblib'
    artifact.write_bytes(artifact.read_bytes() + b'tamper')
    loader = Mock(side_effect=AssertionError('listing must not deserialize'))
    monkeypatch.setattr('services.ai_forecast.registry.joblib.load', loader)
    info = registry.list()[0]
    assert info.approved is False
    loader.assert_not_called()
    assert registry.db.query_one("SELECT approved FROM models WHERE version='owned'")[0] == 1


def test_invalid_artifact_cannot_be_approved(registry):
    registry.db.execute("UPDATE models SET approved=0 WHERE version='owned'")
    (registry.model_dir / 'owned' / 'metadata.json').write_text('{}')
    assert registry.approve('owned', True) is False
    assert registry.db.query_one("SELECT approved FROM models WHERE version='owned'")[0] == 0


def test_unknown_model_approval_is_not_reported_success(registry):
    assert registry.approve('missing', True) is False


def test_valid_artifact_listing_does_not_deserialize(registry, monkeypatch):
    loader = Mock(side_effect=AssertionError('listing must not deserialize'))
    monkeypatch.setattr('services.ai_forecast.registry.joblib.load', loader)
    assert registry.list()[0].approved is True
    loader.assert_not_called()