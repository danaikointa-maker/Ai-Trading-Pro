"""Local development must not initialise real trading adapters."""
from pathlib import Path

import pytest
import yaml

from packages.shared_schemas.settings import Settings
import run as local_launcher


@pytest.fixture
def local_config(tmp_path):
    configs = {
        "app.yaml": {"paths": {}, "market_data": {"feed_mode": "simulate"}},
        "brokers.yaml": {
            "default_broker": "paper-demo",
            "brokers": [
                {"id": "paper-demo", "adapter": "paper"},
                {"id": "sim-demo", "adapter": "simulated_mt5"},
                {"id": "real", "adapter": "mt5"},
                {"id": "relay", "adapter": "bridge"},
            ],
        },
        "risk.yaml": {},
        "strategies.yaml": {},
    }
    for name, content in configs.items():
        (tmp_path / name).write_text(yaml.safe_dump(content), encoding="utf-8")
    return tmp_path


def test_local_simulation_excludes_terminal_and_bridge(local_config, monkeypatch):
    monkeypatch.setenv("NO7_ROOT", str(local_config))
    monkeypatch.setenv("NO7_LOCAL_SIMULATION", "true")
    settings = Settings(config_dir=local_config)
    assert [p["id"] for p in settings.brokers["brokers"]] == ["paper-demo", "sim-demo"]
    assert settings.default_broker_id() == "paper-demo"
    assert len(yaml.safe_load((local_config / "brokers.yaml").read_text())["brokers"]) == 4


def test_normal_settings_preserve_all_profiles(local_config, monkeypatch):
    monkeypatch.setenv("NO7_ROOT", str(local_config))
    monkeypatch.setenv("NO7_LOCAL_SIMULATION", "false")
    assert len(Settings(config_dir=local_config).brokers["brokers"]) == 4


def test_local_mode_selects_paper_when_default_is_live(local_config, monkeypatch):
    monkeypatch.setenv("NO7_ROOT", str(local_config))
    monkeypatch.setenv("NO7_LOCAL_SIMULATION", "true")
    path = local_config / "brokers.yaml"
    data = yaml.safe_load(path.read_text())
    data["default_broker"] = "real"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert Settings(config_dir=local_config).default_broker_id() == "paper-demo"


def test_local_mode_rejects_missing_paper_profile(local_config, monkeypatch):
    monkeypatch.setenv("NO7_ROOT", str(local_config))
    monkeypatch.setenv("NO7_LOCAL_SIMULATION", "true")
    path = local_config / "brokers.yaml"
    data = yaml.safe_load(path.read_text())
    data["brokers"] = [{"id": "real", "adapter": "mt5"}]
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValueError, match="at least one paper broker"):
        Settings(config_dir=local_config)


def test_auto_training_can_be_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("NO7_ROOT", str(tmp_path))
    monkeypatch.setenv("NO7_AUTO_TRAIN_ON_BOOT", "false")
    assert Settings().ai["training"]["auto_train_on_boot"] is False


def test_local_storage_is_ignored():
    root = Path(__file__).resolve().parents[1]
    assert "storage/local-dev/" in (root / ".gitignore").read_text()


def test_dotenv_does_not_load_credential_vault_master_key(tmp_path, monkeypatch):
    from packages.shared_schemas.settings import _load_dotenv

    monkeypatch.delenv("NO7_CREDENTIAL_VAULT_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("NO7_CREDENTIAL_VAULT_KEY=must-not-load\n", encoding="utf-8")
    _load_dotenv(env_file)
    assert "NO7_CREDENTIAL_VAULT_KEY" not in __import__("os").environ


def test_local_launcher_preserves_os_vault_key_but_clears_broker_credentials(monkeypatch):
    monkeypatch.setenv("NO7_CREDENTIAL_VAULT_KEY", "os-secret-store-key")
    monkeypatch.setenv("MT5_LOGIN", "do-not-inherit")
    monkeypatch.setenv("NO7_OTHER_RUNTIME_OVERRIDE", "do-not-inherit")

    env = local_launcher.local_environment()

    assert env["NO7_CREDENTIAL_VAULT_KEY"] == "os-secret-store-key"
    assert env["MT5_LOGIN"] == ""
    assert "NO7_OTHER_RUNTIME_OVERRIDE" not in env