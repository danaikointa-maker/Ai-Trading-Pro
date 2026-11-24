import pytest
from pydantic import ValidationError

from packages.shared_schemas.models import (
    PositionProtectionMode,
    PositionProtectionModeConfig,
    ProtectionEnvironment,
)

ACCOUNT_SCOPE = "a" * 64


@pytest.mark.parametrize("mode", list(PositionProtectionMode))
def test_position_protection_modes_are_distinct_and_disabled_by_default(mode):
    config = PositionProtectionModeConfig(
        config_version=1,
        account_scope_sha256=ACCOUNT_SCOPE,
        mode=mode,
    )

    assert config.mode is mode
    assert config.environment is ProtectionEnvironment.paper
    assert config.enabled is False
    assert config.authorization_ref is None


def test_mode_config_requires_a_hashed_account_scope_and_rejects_secrets():
    with pytest.raises(ValidationError):
        PositionProtectionModeConfig(
            config_version=1, account_scope_sha256="601427", mode="manual")

    with pytest.raises(ValidationError):
        PositionProtectionModeConfig(
            config_version=1, account_scope_sha256=ACCOUNT_SCOPE,
            mode="manual", broker_password="not-accepted")


def test_mode_config_versions_are_positive_strict_integers():
    with pytest.raises(ValidationError):
        PositionProtectionModeConfig(
            config_version=0, account_scope_sha256=ACCOUNT_SCOPE, mode="manual")
    with pytest.raises(ValidationError):
        PositionProtectionModeConfig(
            config_version=True, account_scope_sha256=ACCOUNT_SCOPE, mode="manual")


def test_full_auto_is_inert_without_activation_and_requires_demo_authorization_when_enabled():
    draft = PositionProtectionModeConfig(
        config_version=1, account_scope_sha256=ACCOUNT_SCOPE, mode="full_auto")
    assert draft.enabled is False

    enabled = PositionProtectionModeConfig(
        config_version=2,
        account_scope_sha256=ACCOUNT_SCOPE,
        mode="full_auto",
        environment="demo",
        enabled=True,
        authorization_ref="approval:demo:2026-11-24",
    )
    assert enabled.enabled is True

    with pytest.raises(ValidationError, match="Demo"):
        PositionProtectionModeConfig(
            config_version=2,
            account_scope_sha256=ACCOUNT_SCOPE,
            mode="full_auto",
            environment="live",
            enabled=True,
            authorization_ref="approval:live",
        )

    with pytest.raises(ValidationError, match="authorization"):
        PositionProtectionModeConfig(
            config_version=2,
            account_scope_sha256=ACCOUNT_SCOPE,
            mode="full_auto",
            environment="demo",
            enabled=True,
        )


def test_mode_config_is_immutable_after_validation():
    config = PositionProtectionModeConfig(
        config_version=1, account_scope_sha256=ACCOUNT_SCOPE, mode="manual")

    with pytest.raises(ValidationError):
        config.enabled = True
