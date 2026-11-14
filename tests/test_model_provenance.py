"""Model provenance gates use temporary files and never deserialize unowned bytes."""
from types import SimpleNamespace
from unittest.mock import Mock
import sqlite3

import joblib
import numpy as np
import pytest

from packages.persistence.db import Database
from services.ai_forecast.registry import ModelRegistry


def training(version="owned-v1"):
    return SimpleNamespace(version=version, models={}, feature_columns=[], trained_at=100,
                           metrics={"horizons": {}, "approval_rule": 2}, approved=False,
                           notes="local fixture", samples=1,
                           path_table=SimpleNamespace(arrays=lambda: {"test": np.array([1., 2.])}))


@pytest.fixture
def registry(tmp_path):
    db = Database(tmp_path / "owner.db", workspace_id="team-a")
    result = ModelRegistry(tmp_path / "models", db)
    yield result
    db.close()


def test_owned_artifact_roundtrip_preserves_arrays(registry):
    registry.save(training(), "XAUUSD")
    payload, arrays = registry.load("owned-v1")
    assert payload["version"] == "owned-v1"
    assert payload["symbol"] == "XAUUSD"
    np.testing.assert_array_equal(arrays["test"], [1., 2.])


def test_unregistered_legacy_model_is_not_deserialized_or_modified(registry, monkeypatch):
    target = registry.model_dir / "legacy"
    target.mkdir()
    artifact = target / "models.joblib"
    joblib.dump({"version": "legacy", "approved": True}, artifact)
    registry.db.execute("INSERT INTO models(version,created_at,approved,path) VALUES(?,?,?,?)",
                        ("legacy", 200, 1, str(artifact)))
    before = artifact.read_bytes()
    loader = Mock()
    monkeypatch.setattr("services.ai_forecast.registry.joblib.load", loader)
    assert registry.load("legacy") is None
    loader.assert_not_called()
    assert artifact.read_bytes() == before
    assert registry.db.query_one("SELECT approved FROM models WHERE version='legacy'")[0] == 1


@pytest.mark.parametrize("file", ["models.joblib", "pathprob.npz", "metadata.json"])
@pytest.mark.parametrize("damage", ["modified", "missing"])
def test_damaged_artifact_is_quarantined_before_any_deserialization(registry, monkeypatch, file, damage):
    target = registry.save(training(), "XAUUSD")
    selected = target / file
    if damage == "modified":
        selected.write_bytes(selected.read_bytes() + b"tamper")
    else:
        selected.unlink()
    loader = Mock()
    monkeypatch.setattr("services.ai_forecast.registry.joblib.load", loader)
    assert registry.load("owned-v1") is None
    loader.assert_not_called()


def test_shared_root_does_not_grant_another_workspace_model_ownership(registry, tmp_path, monkeypatch):
    registry.save(training(), "XAUUSD")
    other_db = Database(tmp_path / "other.db", workspace_id="team-b")
    other = ModelRegistry(registry.model_dir, other_db)
    loader = Mock()
    monkeypatch.setattr("services.ai_forecast.registry.joblib.load", loader)
    try:
        assert other.load("owned-v1") is None
        loader.assert_not_called()
    finally:
        other_db.close()


def test_existing_version_cannot_be_overwritten_or_silently_adopted(registry):
    target = registry.save(training(), "XAUUSD")
    before = {path.name: path.read_bytes() for path in target.iterdir()}
    with pytest.raises(ValueError, match="exists|immutable|artifact"):
        registry.save(training(), "XAUUSD")
    assert {path.name: path.read_bytes() for path in target.iterdir()} == before


def test_saved_registration_path_is_part_of_provenance(registry, monkeypatch):
    registry.save(training(), "XAUUSD")
    registry.db.execute("UPDATE models SET path='foreign/models.joblib' WHERE version='owned-v1'")
    loader = Mock()
    monkeypatch.setattr("services.ai_forecast.registry.joblib.load", loader)
    assert registry.load("owned-v1") is None
    loader.assert_not_called()


@pytest.mark.parametrize("files", [None, [], "invalid", 1])
def test_malformed_hash_evidence_is_not_deserialized(registry, monkeypatch, files):
    registry.save(training(), "XAUUSD")
    evidence = registry.db.kv_get("model.provenance:owned-v1")
    evidence["files"] = files
    registry.db.kv_set("model.provenance:owned-v1", evidence)
    loader = Mock()
    monkeypatch.setattr("services.ai_forecast.registry.joblib.load", loader)
    assert registry.load("owned-v1") is None
    loader.assert_not_called()


def test_failed_provenance_registration_rolls_back_model_row(registry, monkeypatch):
    registry.db.execute("CREATE TRIGGER fail_provenance BEFORE INSERT ON kv "
                        "WHEN NEW.key LIKE 'model.provenance:%' "
                        "BEGIN SELECT RAISE(ABORT, 'injected provenance failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected provenance failure"):
        registry.save(training(), "XAUUSD")
    assert registry.db.query("SELECT * FROM models") == []
    loader = Mock()
    monkeypatch.setattr("services.ai_forecast.registry.joblib.load", loader)
    assert registry.load("owned-v1") is None
    loader.assert_not_called()


def test_model_root_cannot_be_rebound_after_registry_creation(registry, tmp_path, monkeypatch):
    registry.save(training(), "XAUUSD")
    import shutil

    original = registry.model_dir
    moved = tmp_path / "moved-models"
    original.rename(moved)
    replacement = tmp_path / "replacement"
    shutil.copytree(moved, replacement)
    try:
        original.symlink_to(replacement, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation requires Windows privilege")
    evidence = registry.db.kv_get("model.provenance:owned-v1")
    evidence["root"] = str(replacement.resolve())
    registry.db.kv_set("model.provenance:owned-v1", evidence)
    loader = Mock()
    monkeypatch.setattr("services.ai_forecast.registry.joblib.load", loader)
    with pytest.raises(ValueError, match="artifact|root"):
        registry.load("owned-v1")
    loader.assert_not_called()


def test_model_registry_rejects_symlinked_parent_before_creating_root(tmp_path):
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    linked_parent = tmp_path / "model-parent"
    try:
        linked_parent.symlink_to(foreign, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation requires Windows privilege")

    db = Database(tmp_path / "registry.db", workspace_id="team-a")
    selected_root = linked_parent / "models"
    try:
        with pytest.raises(ValueError, match="root|path"):
            ModelRegistry(selected_root, db)
        assert not (foreign / "models").exists()
    finally:
        db.close()


def test_quarantined_latest_model_clears_previously_installed_approval(registry, settings):
    from services.ai_forecast.predictor import ForecastPredictor

    predictor = ForecastPredictor(settings, registry)
    predictor.install_payload({"version": "previous", "approved": True, "models": {},
                               "metrics": {"approval_rule": 2}}, {})
    assert predictor.approved is True
    target = registry.model_dir / "unowned-latest"
    target.mkdir()
    joblib.dump({"version": "unowned-latest", "approved": True}, target / "models.joblib")
    registry.db.execute("INSERT INTO models(version,created_at,approved,path) VALUES(?,?,?,?)",
                        ("unowned-latest", 200, 1, str(target / "models.joblib")))
    assert predictor.load_latest() is False
    assert predictor.approved is False
    assert predictor.models == {}
    assert predictor.path_table is None
    assert predictor.version == "baseline-statistical"
    assert "provenance" in predictor.notes.lower() or "quarantin" in predictor.notes.lower()