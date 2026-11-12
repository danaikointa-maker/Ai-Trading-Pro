"""Negative path checks never deserialize external model files or read foreign datasets."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from packages.persistence.db import Database
from services.ai_forecast.registry import ModelRegistry
from services.market_data.replay import build_feed


@pytest.mark.parametrize("version", ["../foreign", "a/b", "a\\b", "", ".", "..", "C:\\foreign", "a:stream"])
def test_model_version_cannot_select_a_path(tmp_path, monkeypatch, version):
    db = Database(tmp_path / "test.db")
    registry = ModelRegistry(tmp_path / "models", db)
    loader = Mock()
    monkeypatch.setattr("services.ai_forecast.registry.joblib.load", loader)
    try:
        with pytest.raises(ValueError, match="artifact|version"):
            registry.load(version)
        loader.assert_not_called()
    finally:
        db.close()


@pytest.mark.parametrize("part", ["version", "models.joblib", "pathprob.npz"])
def test_model_symlinks_are_blocked_before_deserialization(tmp_path, monkeypatch, part):
    db = Database(tmp_path / "test.db")
    registry = ModelRegistry(tmp_path / "models", db)
    external = tmp_path / "external"
    external.mkdir()
    (external / "models.joblib").write_bytes(b"not a model")
    target = registry.model_dir / "v1"
    try:
        if part == "version":
            target.symlink_to(external, target_is_directory=True)
        else:
            target.mkdir()
            (target / "models.joblib").write_bytes(b"not a model")
            (target / part).unlink(missing_ok=True)
            (target / part).symlink_to(external / "models.joblib")
    except OSError:
        db.close()
        pytest.skip("symlink creation requires Windows privilege")
    loader = Mock()
    monkeypatch.setattr("services.ai_forecast.registry.joblib.load", loader)
    try:
        with pytest.raises(ValueError, match="artifact|path"):
            registry.load("v1")
        loader.assert_not_called()
    finally:
        db.close()


@pytest.mark.parametrize("selection", ["absolute", "traversal", "symlink"])
def test_custom_replay_cannot_read_outside_workspace(tmp_path, monkeypatch, selection):
    owned = tmp_path / "owned"
    foreign = tmp_path / "foreign"
    owned.mkdir()
    foreign.mkdir()
    selected = foreign if selection == "absolute" else owned / ".." / "foreign"
    if selection == "symlink":
        selected = owned / "linked"
        try:
            selected.symlink_to(foreign, target_is_directory=True)
        except OSError:
            pytest.skip("symlink creation requires Windows privilege")
    settings = SimpleNamespace(root=tmp_path, paths={"datasets": owned}, market_data={
        "feed_mode": "replay", "history_bars": 100,
        "replay": {"dataset_dir": str(selected)}})
    loader = Mock(side_effect=AssertionError("foreign dataset must not be read"))
    monkeypatch.setattr("services.market_data.dataset.load_dataset", loader)
    _feed, mode, note = build_feed(settings, {"XAUUSD": {"point": 0.01, "digits": 2}})
    assert mode == "simulate"
    assert "workspace" in note
    assert str(foreign) not in note
    loader.assert_not_called()


def test_custom_replay_rejects_symlinked_configured_dataset_root(tmp_path, monkeypatch):
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    owned = tmp_path / "owned"
    try:
        owned.symlink_to(foreign, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation requires Windows privilege")
    settings = SimpleNamespace(root=tmp_path, paths={"datasets": owned}, market_data={
        "feed_mode": "replay", "history_bars": 100,
        "replay": {"dataset_dir": str(owned)}})
    loader = Mock(side_effect=AssertionError("symlinked dataset root must not be read"))
    monkeypatch.setattr("services.market_data.dataset.load_dataset", loader)

    _, mode, note = build_feed(settings, {"XAUUSD": {"point": 0.01, "digits": 2}})

    assert mode == "simulate"
    assert note and "workspace" in note
    loader.assert_not_called()


def test_model_save_rejects_linked_metadata_before_writing(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    registry = ModelRegistry(tmp_path / "models", db)
    target = registry.model_dir / "v1"
    target.mkdir()
    external = tmp_path / "private.json"
    external.write_text("keep", encoding="utf-8")
    try:
        (target / "metadata.json").symlink_to(external)
    except OSError:
        db.close()
        pytest.skip("symlink creation requires Windows privilege")
    writer = Mock()
    monkeypatch.setattr("services.ai_forecast.registry.joblib.dump", writer)
    try:
        with pytest.raises(ValueError, match="artifact|path"):
            registry.save(SimpleNamespace(version="v1", models={}, feature_columns=[], trained_at=1,
                                          metrics={}, approved=False, notes="", samples=1,
                                          path_table=SimpleNamespace(arrays=lambda: {})), "XAUUSD")
        writer.assert_not_called()
        assert external.read_text(encoding="utf-8") == "keep"
    finally:
        db.close()