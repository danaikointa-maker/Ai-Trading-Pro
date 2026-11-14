"""A persisted revocation must survive predictor reload without editing artifacts."""
from types import SimpleNamespace
from threading import RLock
from unittest.mock import Mock

import pytest

from packages.persistence.db import Database
from services.ai_forecast.pathprob import PathProbabilityTable
from services.ai_forecast.predictor import ForecastPredictor
from services.ai_forecast.registry import ModelRegistry
from services.api_gateway.routes.analysis import approve


@pytest.mark.parametrize('initial_approval', [True, False])
def test_db_approval_cannot_override_payload_rejection_or_revocation(tmp_path, settings, initial_approval):
    db = Database(tmp_path / 'models.db', workspace_id='team-a')
    registry = ModelRegistry(tmp_path / 'models', db)
    result = SimpleNamespace(version='owned', models={}, feature_columns=[], trained_at=1,
                             metrics={'horizons': {}, 'approval_rule': 2}, approved=initial_approval,
                             notes='fixture', samples=1, path_table=PathProbabilityTable())
    folder = registry.save(result, 'XAUUSD')
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    try:
        assert registry.approve('owned', initial_approval is False) is True
        predictor = ForecastPredictor(settings, registry)
        assert predictor.approved is False
        assert {p.name: p.read_bytes() for p in folder.iterdir()} == before
        assert db.query("SELECT * FROM kv WHERE key LIKE 'model.quarantine:%'") == []
    finally:
        db.close()


def test_revoke_route_revalidates_loaded_predictor():
    runtime = SimpleNamespace(model_registry=Mock(), predictor=Mock(), lock=RLock(), forecasts={})
    runtime.model_registry.approve.return_value = True
    result = approve('owned', {'approved': False}, runtime, {'email': 'researcher'})
    assert result['approved'] is False
    runtime.predictor.load_latest.assert_called_once_with()