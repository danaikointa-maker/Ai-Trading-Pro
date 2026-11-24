# U07 Position Protection Mode Schema — 2026-11-24

## Scope

Add only an inert shared-schema contract for the four Position Protection V1.1 modes. This does not implement a runtime setting or change the behavior of the existing entry `TradeMode`.

## Implemented contract

- Adds `PositionProtectionMode` (`manual`, `semi_auto`, `full_auto`, `hybrid`) separately from `TradeMode`.
- Adds immutable `PositionProtectionModeConfig` with schema/config versions, a SHA-256 account-scope identifier, environment, and an `enabled=false` default.
- Uses strict types, rejects unknown fields (including credentials), and accepts only a full lowercase 64-character account identity hash.
- Enabled Full Auto requires the Demo environment and a separate authorization reference. Disabled Full Auto remains a draft value only.
- An absent config record means existing legacy profile behavior continues. No migration or runtime code reads this schema.

## Intentionally not connected

- No API route, database table/key, UI control, Risk Engine/PositionManager/Gateway integration, or configuration activation was added.
- No mode can currently pause/approve/modify positions through this schema.
- `config/risk.yaml`, `config/risk_v4_candidate.yaml`, account, broker, Auto/Live and position state were not changed.
- U05 single-writer durable intent, restart and broker reconciliation acceptance remains a prerequisite for runtime mode controls.

## Verification

- `tests/test_protection_mode_contract.py`: **8 passed**.
- `tests/test_roles.py tests/test_risk_engine.py tests/test_v4_single_target_manager.py`: **41 passed**, one existing Starlette/httpx deprecation warning.
- Ruff `E9,F,I` and `git diff --check`: **PASS**.
- No broker command was sent; no Paper/Demo/Live state was changed.

## Status

U07 remains **PARTIAL / BLOCKED BY U05 ACCEPTANCE**. The contract is reviewable and inert; runtime modes, persistence, RBAC, approval flow, per-position Hybrid overrides, and broker acceptance remain NOT IMPLEMENTED / NOT TESTED.
