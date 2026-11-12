"""Model quarantine survives restart and cannot be cleared by restoring bytes."""
from types import SimpleNamespace
from unittest.mock import Mock
import sqlite3

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


def test_quarantine_survives_reopen_and_restored_artifact(registry, monkeypatch):
    artifact = registry.model_dir / 'owned' / 'metadata.json'
    original = artifact.read_bytes()
    artifact.write_bytes(b'tampered')
    assert registry.load('owned') is None
    record = registry.db.kv_get('model.quarantine:owned')
    assert record['state'] == 'quarantined'
    assert record['workspace_id'] == 'team-a'
    assert record['reason'] == 'artifact_verification_failed'
    assert str(registry.model_dir) not in str(record)
    artifact.write_bytes(original)
    other_db = Database(registry.db.path, workspace_id='team-a')
    loader = Mock(side_effect=AssertionError('quarantine must block deserialization'))
    monkeypatch.setattr('services.ai_forecast.registry.joblib.load', loader)
    try:
        reopened = ModelRegistry(registry.model_dir, other_db)
        assert reopened.load('owned') is None
        assert reopened.approve('owned') is False
        info = reopened.list()[0]
        assert info.approved is False
        assert info.artifact_status == 'quarantined'
        assert info.artifact_reason == 'artifact_verification_failed'
        assert other_db.kv_get('model.quarantine:owned') == record
        assert other_db.query_one("SELECT approved FROM models WHERE version='owned'")[0] == 1
        loader.assert_not_called()
    finally:
        other_db.close()


@pytest.mark.parametrize('entrypoint', ['list', 'approve'])
def test_disclosure_and_approval_also_latch_quarantine(registry, entrypoint):
    (registry.model_dir / 'owned' / 'metadata.json').unlink()
    if entrypoint == 'list':
        assert registry.list()[0].approved is False
    else:
        assert registry.approve('owned') is False
    assert registry.db.kv_get('model.quarantine:owned')['state'] == 'quarantined'


def test_valid_and_unknown_models_do_not_create_quarantine_records(registry):
    info = registry.list()[0]
    assert info.artifact_status == 'verified'
    assert info.artifact_reason == ''
    assert registry.load('missing') is None
    assert registry.db.query("SELECT * FROM kv WHERE key LIKE 'model.quarantine:%'") == []


def test_malformed_persisted_quarantine_cannot_auto_release_model(registry, monkeypatch):
    registry.db.execute("INSERT INTO kv(key,value,updated_at) VALUES(?,?,?)",
                        ('model.quarantine:owned', 'not-json', 1))
    loader = Mock(side_effect=AssertionError('malformed latch must fail closed'))
    monkeypatch.setattr('services.ai_forecast.registry.joblib.load', loader)
    assert registry.load('owned') is None
    assert registry.approve('owned') is False
    assert registry.list()[0].approved is False
    loader.assert_not_called()


def test_revoke_does_not_release_quarantine_or_modify_artifact(registry):
    artifact = registry.model_dir / 'owned' / 'metadata.json'
    artifact.write_bytes(b'tampered')
    assert registry.load('owned') is None
    record = registry.db.kv_get('model.quarantine:owned')
    assert registry.approve('owned', False) is True
    assert registry.db.kv_get('model.quarantine:owned') == record
    assert artifact.read_bytes() == b'tampered'
    assert registry.approve('owned', True) is False


def test_failed_quarantine_persistence_never_deserializes_or_approves(registry, monkeypatch):
    (registry.model_dir / 'owned' / 'metadata.json').write_bytes(b'tampered')
    registry.db.execute("CREATE TRIGGER fail_quarantine BEFORE INSERT ON kv "
                        "WHEN NEW.key LIKE 'model.quarantine:%' "
                        "BEGIN SELECT RAISE(ABORT, 'injected quarantine failure'); END")
    loader = Mock(side_effect=AssertionError('persistence failure must fail closed'))
    monkeypatch.setattr('services.ai_forecast.registry.joblib.load', loader)
    with pytest.raises(sqlite3.IntegrityError, match='injected quarantine failure'):
        registry.load('owned')
    assert registry.db.query_one("SELECT approved FROM models WHERE version='owned'")[0] == 1
    loader.assert_not_called()