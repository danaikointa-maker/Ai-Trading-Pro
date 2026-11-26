# U02 / U04 / U05 / U06 / U07 regression recheck — 2026-11-26

## Scope and safety

Re-ran the existing dependency-ordered V4 regression set on planning base `9ce4a18983cbb96d14f95a0ad4d0e5605d5eeffa` after PR #88. The tests use unit fixtures, Paper, and fake MT5 terminals. No MT5 terminal was connected; no broker command, order, position, account, risk profile, Auto/Live setting, service, or runtime configuration was changed.

## Result

Command:

```powershell
& 'C:\workspace\Ai-Trading-Pro\.venv\Scripts\python.exe' -m pytest tests/test_signal_confirmation_v4.py tests/test_readiness.py tests/test_signal_execution.py tests/test_smart_entry_continuation.py tests/test_mt5_order_preflight.py tests/test_mt5_account_continuity.py tests/test_v4_plan_candidate.py tests/test_execution_recovery.py tests/test_position_modify_intents.py tests/test_v4_single_target_manager.py tests/test_protection_mode_contract.py tests/test_roles.py tests/test_risk_engine.py -q
```

**279 passed, 1 warning in 36.90s.** The warning is the existing Starlette `TestClient` deprecation for using `httpx`; no test failed.

## Task impact

- **U02:** confirmation/readiness/execution regression remains green. The candidate is still not accepted against fresh MT5 market data or a broker Demo session.
- **U04:** fake-terminal preflight and planner regressions remain green. Real broker margin, stops/freeze, `order_check`, fill and SL/TP readback remain NOT TESTED; candidate stays inactive.
- **U05:** durable intent/idempotency and reconciliation fixtures remain green. VM staging restart/persistence parity and broker Demo modify/readback remain NOT TESTED.
- **U06:** existing Paper PositionManager lifecycle/reconciliation coverage remains green. Broker protection behavior and real Demo restart/ambiguous-ack remain NOT TESTED.
- **U07:** immutable account-scoped mode contract/role tests remain green. Runtime mode persistence and broker behavior remain NOT TESTED; legacy risk profile remains active.

These results do not change acceptance statuses: U02/U04/U05/U06/U07 remain PARTIAL or BLOCKED as recorded in the V4 register. No acceptance gate was bypassed.

## Rollback

Documentation-only change. Revert this audit and the matching Task Register evidence entry; no runtime rollback is needed.
