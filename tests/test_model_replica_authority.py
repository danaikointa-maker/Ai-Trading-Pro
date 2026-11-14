"""Account-owned replica frames still require current model authority."""
from types import SimpleNamespace

import pytest

from packages.persistence.db import Database
from services.ai_forecast.registry import ModelRegistry
from services.ai_forecast.pathprob import PathProbabilityTable
from services.api_gateway.state import TradingRuntime


@pytest.mark.parametrize('change', ['revoke', 'quarantine', 'valid'])
def test_owned_replica_frame_does_not_reassert_revoked_model(tmp_path, monkeypatch, change):
    db = Database(tmp_path / 'runtime.db', workspace_id='team-a')
    registry = ModelRegistry(tmp_path / 'models', db)
    registry.save(SimpleNamespace(version='owned', models={}, feature_columns=[], trained_at=1,
        metrics={'approval_rule': 2}, approved=True, notes='', samples=1,
        path_table=PathProbabilityTable()), 'XAUUSD')
    if change == 'revoke':
        registry.approve('owned', False)
    elif change == 'quarantine':
        registry._quarantine('owned')
    identity = {'workspace_id': 'team-a', 'broker_id': 'demo', 'login': 'fixture', 'server': 'Demo'}
    db.kv_set('account-owner:demo', identity)
    adapter = SimpleNamespace(id='demo')
    runtime = TradingRuntime.__new__(TradingRuntime)
    runtime.db = db
    runtime.model_registry = registry
    runtime.registry = SimpleNamespace(get=lambda: adapter)
    runtime.gateway = SimpleNamespace(_account=lambda *args: dict(identity))
    runtime.shared = object()
    frame = {'_account_identity': dict(identity), 'frame_age_seconds': 0,
             'account': {k: v for k, v in identity.items() if k != 'workspace_id'},
             'positions_status': {'available': True, 'age_seconds': 0}, 'positions': [],
             'model': {'version': 'owned', 'approved': True},
             'forecast': {'model_version': 'owned', 'model_approved': True}}
    monkeypatch.setattr('services.api_gateway.state.replica_payload', lambda *args: frame)
    try:
        accepted = runtime._owned_replica_payload()
        assert accepted is not None, 'valid position ownership must remain available'
        if change == 'valid':
            assert accepted['forecast']['model_approved'] is True
            assert accepted['model']['approved'] is True
            return
        assert accepted['forecast'] is None
        assert accepted['model']['approved'] is False
    finally:
        db.close()