# Position Protection V1.1 — Release Readiness Report

## Scope and safety boundary

This implementation is staged on `plan/position-protection-v1-1`. It preserves the current runtime risk configuration and legacy `PositionManager.evaluate()` behavior. The new profile is separate and has automation disabled. Automatic order modification is not enabled for Demo or Live. The UI can preview positions and apply a protection change only in Paper/simulated mode.

No Demo order or Live order was sent. Demo verification remains pending explicit approval. No merge or deployment has been performed.

## Evidence

| Check | Result | Evidence |
|---|---|---|
| Targeted unit/API/account ownership/safety suite | PASS | `166 passed, 1 warning` across `test_position_protection_v1_1.py`, `test_position_modification_safety.py`, `test_position_protection_api.py`, `test_account_ownership.py`, `test_smart_entry_continuation.py`, and `test_runtime_position_ownership.py` |
| Vue production build | PASS | `npm run build`, Vite 5.4.21, 625 modules transformed |
| Whitespace/conflict check | PASS | `git diff --check` |
| Full repository suite | NOT TESTED to completion | Started, but execution was interrupted after prolonged stall; partial progress showed failures. The cached failed test entry `tests/test_positions_ui.py::test_position_disclosure_ui` was rerun after installing frontend dependencies and passed independently. Full-suite failures need a complete rerun and triage before release. |
| Paper broker execution | NOT TESTED | No end-to-end Paper broker session was available in this run. Apply endpoint is restricted to Paper/simulated adapters. |
| Broker Demo execution and reconciliation | NOT TESTED | Requires explicit Demo approval and an authenticated Demo terminal/session. |
| Live execution | NOT RUN / LOCKED | Live Auto Trading remains prohibited and no Live order was sent. |
| Performance Analyzer causal comparison | NOT IMPLEMENTED | Current analyzer endpoint reports that paired counterfactual data is unavailable. It does not claim BE/trailing improved outcomes. |

## Known release gaps

1. Finish the full repository test run and investigate every failure.
2. Run end-to-end Paper-mode tests against the configured paper adapter, including broker rejection, requote, timeout, partial fill, and reconnect reconciliation.
3. After explicit approval, run Demo-only validation and collect broker-confirmed modification evidence.
4. Build the Protection Performance Analyzer using paired replays over the same frozen entry decisions and market data. Report drawdown, average net R, expectancy, and missed-profit differences with sample size and uncertainty; do not infer causality from successful SL modifications alone.
5. Review dependency audit findings from `npm ci` (2 moderate, 1 high) before production release.

## Rollback plan

1. Disable the Position Protection route/view or revert this branch; legacy `PositionManager.evaluate()` and active `config/risk.yaml` remain the runtime path.
2. Keep `position_modification_intents` as an additive audit/reconciliation table during rollback. Do not delete rows or the table while unresolved operations exist.
3. If a Paper modification is unresolved, stop new modifications, fetch a fresh broker position snapshot, reconcile the intent, then resume only after the operator confirms state.
4. Restore the previous application build and restart the app using the project runbook. No schema downgrade is required because the database addition is additive.
5. Verify the legacy risk configuration checksum recorded by the staged migration manifest and confirm automatic protection remains disabled.

## Pull request status

This report is prepared for a draft pull request. Merge and deployment are intentionally excluded. Full-suite and Paper/Demo evidence are release gates, not assumed passes.
