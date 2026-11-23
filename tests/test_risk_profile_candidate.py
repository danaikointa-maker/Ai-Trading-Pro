from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_v4_candidate_is_explicitly_inactive_and_does_not_change_legacy_profile():
    legacy = yaml.safe_load((ROOT / "config/risk.yaml").read_text(encoding="utf-8"))
    candidate = yaml.safe_load((ROOT / "config/risk_v4_candidate.yaml").read_text(encoding="utf-8"))

    assert candidate["schema_version"] == "conservative_v4_candidate"
    assert candidate["status"] == "inactive"
    assert candidate["activation_requires_review"] is True
    assert candidate["execution"] == {
        "full_auto_enabled": False,
        "live_auto_enabled": False,
        "demo_acceptance_required": True,
    }
    assert candidate["limits"]["risk_per_trade_pct"] == legacy["limits"]["risk_per_trade_pct"]
    assert candidate["limits"]["max_weekly_loss_pct"] == 4.0
    assert candidate["limits"]["max_drawdown_pct"] == 8.0
    assert candidate["limits"]["min_reward_risk"] == 1.5
    assert candidate["limits"]["max_aggregate_risk_pct"] == 1.0
    assert candidate["limits"]["max_trades_per_day"] == 5
    assert candidate["targets"]["partial_close_enabled"] is False
    assert candidate["plan_options"] == {
        "sl_policy": "atr_structure",
        "sl_structure_buffer_atr": 0.2,
        "swing_lookback_bars": 10,
        "directional_tick_rounding": True,
        "single_target_r": 2.0,
        "enforcement_status": "candidate_only",
    }


def test_v4_has_one_authoritative_inactive_risk_candidate():
    assert not (ROOT / "config/candidates/conservative_v4_risk.yaml").exists()


def test_v4_candidate_file_is_not_the_runtime_risk_config():
    settings_source = (ROOT / "packages/shared_schemas/settings.py").read_text(encoding="utf-8")
    assert 'self.risk = self._read("risk.yaml")' in settings_source
    assert 'self.risk = self._read("risk_v4_candidate.yaml")' not in settings_source
