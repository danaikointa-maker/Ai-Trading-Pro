"""The V4 risk profile remains versioned, isolated design data."""
from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from packages.shared_schemas.models import RiskLimits
from packages.shared_schemas.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_candidate_does_not_change_executable_legacy_profile(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for name in ("app.yaml", "brokers.yaml", "risk.yaml", "strategies.yaml"):
        shutil.copyfile(ROOT / "config" / name, config_dir / name)
    monkeypatch.setenv("NO7_ROOT", str(tmp_path))

    settings = Settings(config_dir=config_dir)
    candidate = _load_yaml(ROOT / "config/candidates/conservative_v4_risk.yaml")

    assert settings.risk["limits"]["max_weekly_loss_pct"] == 5.0
    assert settings.risk["limits"]["max_drawdown_pct"] == 10.0
    assert settings.risk["limits"]["min_reward_risk"] == 1.3
    assert "candidate" not in settings.risk
    assert candidate["candidate"]["activation"] == "forbidden"
    assert candidate["migration"]["automatic"] is False


def test_schema_compatible_candidate_fields_match_existing_risklimits():
    candidate = _load_yaml(ROOT / "config/candidates/conservative_v4_risk.yaml")
    proposed = candidate["runtime_compatible_limits"]
    parsed = RiskLimits(**proposed)

    assert parsed.risk_per_trade_pct == 0.5
    assert parsed.max_weekly_loss_pct == 4.0
    assert parsed.max_drawdown_pct == 8.0
    assert parsed.min_reward_risk == 1.5
    assert candidate["policy_proposals"]["enforcement_status"] == "unsupported_by_current_runtime"
    assert "aggregate_open_risk_pct" not in RiskLimits.model_fields
    assert "max_trades_per_day" not in RiskLimits.model_fields
