"""Versioned position-protection profile and non-activating migration preview."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any

import yaml

from packages.shared_schemas.settings import CONFIG_DIR


PROFILE_PATH = CONFIG_DIR / "risk-profiles" / "position-protection-v1.1.yaml"


def load_v1_1_profile(path: str | Path = PROFILE_PATH) -> dict[str, Any]:
    profile = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    validate_v1_1_profile(profile)
    return profile


def validate_v1_1_profile(profile: dict[str, Any]) -> None:
    if profile.get("id") != "position-protection-v1.1" or profile.get("version") != "1.1":
        raise ValueError("unsupported protection profile identity")
    if profile.get("status") != "staged" or profile.get("default_mode") != "MANUAL":
        raise ValueError("V1.1 must remain staged and default to MANUAL")
    automation = profile.get("automation") or {}
    if automation.get("enabled") is not False or automation.get("live_allowed") is not False:
        raise ValueError("V1.1 automatic modification must remain disabled and LIVE locked")
    protection = profile.get("protection") or {}
    required = ("sl_required", "tp_required", "never_widen_stop_loss",
                "never_increase_risk_after_entry", "reject_invalid_stop_levels",
                "reject_unknown_position_identity")
    if any(protection.get(key) is not True for key in required):
        raise ValueError("V1.1 hard protection constraints may not be weakened")
    if profile.get("partial_close", {}).get("enabled") is not False:
        raise ValueError("V1.1 partial close remains disabled pending separate evidence")


def migration_manifest(current_risk: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Describe a staged profile migration without editing the active config."""
    validate_v1_1_profile(profile)
    legacy = copy.deepcopy(current_risk.get("management", {}))
    raw = yaml.safe_dump(current_risk, sort_keys=True, allow_unicode=True).encode("utf-8")
    return {
        "schema_version": 1,
        "source_profile": "legacy",
        "target_profile": profile["id"],
        "source_risk_config_sha256": hashlib.sha256(raw).hexdigest(),
        "legacy_management_preserved": legacy,
        "target_profile_status": profile["status"],
        "activation_required": True,
        "rollback_profile": "legacy",
        "active_config_changed": False,
        "live_auto_enabled": False,
    }
