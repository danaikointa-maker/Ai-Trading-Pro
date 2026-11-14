"""An obsolete authority check cannot approve a replacement model generation."""
from types import SimpleNamespace
import pytest

from packages.persistence.db import Database
from services.ai_forecast.pathprob import PathProbabilityTable
from services.ai_forecast.predictor import ForecastPredictor
from services.ai_forecast.registry import ModelRegistry


@pytest.mark.parametrize('replacement_version', ['new-rejected', 'old'])
def test_inflight_authority_check_cannot_approve_replacement_payload(tmp_path, monkeypatch, replacement_version):
    db = Database(tmp_path / 'models.db', workspace_id='team-a')
    registry = ModelRegistry(tmp_path / 'models', db)
    registry.save(SimpleNamespace(version='old', models={}, feature_columns=[], trained_at=1,
        metrics={'approval_rule': 2}, approved=True, notes='', samples=1,
        path_table=PathProbabilityTable()), 'XAUUSD')
    predictor = ForecastPredictor(SimpleNamespace(ai={}), registry)

    def change_during_check(version):
        assert version == 'old'
        predictor.install_payload({'version': replacement_version, 'approved': False,
            'models': {}, 'metrics': {'approval_rule': 2}}, {})
        return True

    monkeypatch.setattr(registry, 'inference_allowed', change_during_check)
    try:
        assert predictor.revalidate() is False
        assert predictor.version == replacement_version
        assert predictor.approved is False
    finally:
        db.close()