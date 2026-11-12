"""File-backed private resources must not fall back to a shared legacy root."""
from pathlib import Path

import pytest

from packages.shared_schemas.settings import Settings


def test_same_storage_configuration_resolves_different_workspace_directories(tmp_path, monkeypatch):
    monkeypatch.setenv("NO7_WORKSPACE_ID", "team-a")
    first = Settings()
    monkeypatch.setenv("NO7_WORKSPACE_ID", "team-b")
    second = Settings()
    for name in ("datasets", "models", "backtests", "logs"):
        assert first.paths[name] != second.paths[name]
        assert first.paths[name].parts[-2:] == ("workspaces", "team-a")
        assert second.paths[name].parts[-2:] == ("workspaces", "team-b")


def test_legacy_files_are_not_adopted_by_new_workspace(tmp_path, monkeypatch):
    legacy = tmp_path / "datasets"
    legacy.mkdir()
    retained = legacy / "private-report.json"
    retained.write_text("private", encoding="utf-8")
    monkeypatch.setenv("NO7_DATA_DIR", str(legacy))
    monkeypatch.setenv("NO7_WORKSPACE_ID", "team-a")
    config = Settings()
    assert config.paths["datasets"] != legacy
    assert not (config.paths["datasets"] / retained.name).exists()
    assert retained.read_text(encoding="utf-8") == "private"


@pytest.mark.parametrize("workspace", ["", "../other", "a b", "a" * 65])
def test_invalid_workspace_rejected_before_private_directories_are_created(tmp_path, monkeypatch, workspace):
    target = tmp_path / "private"
    monkeypatch.setenv("NO7_DATA_DIR", str(target))
    monkeypatch.setenv("NO7_WORKSPACE_ID", workspace)
    with pytest.raises(ValueError, match="workspace"):
        Settings()
    assert not target.exists()


def test_default_local_workspace_is_also_namespaced(monkeypatch):
    monkeypatch.setenv("NO7_WORKSPACE_ID", "local")
    config = Settings()
    assert config.paths["datasets"].parts[-2:] == ("workspaces", "local")
    assert isinstance(config.database_path, Path)