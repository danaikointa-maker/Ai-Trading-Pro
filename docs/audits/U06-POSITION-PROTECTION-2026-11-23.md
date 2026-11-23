# U06 — Position Protection Candidate Audit

Date: 2026-11-23  
Plan: Unified Master Plan V4 / Unified Task Register V4  
Branch: `feature/u06-position-protection-v4`

## Gap and change

The existing `PositionManager` could emit separate break-even and trailing-stop
modifications for one ticket during the same evaluation. Both actions would flow
through the existing `ExecutionGateway`, where durable intent fencing permits
only one unresolved modification at a time. This candidate reduces the policy
output to one strict-improvement SL action per position/evaluation, choosing the
most protective valid candidate for the trade direction.

The existing manager and gateway are reused. The candidate rejects a stop at or
through the current price, does not widen an existing stop, and fails closed if
the current SL is missing or unknown. It does not alter legacy risk-profile
values or activate a new profile.

## Evidence

| Check | Result |
|---|---|
| Position protection and regression set | PASS — `pytest tests/test_v4_single_target_manager.py tests/test_smart_entry_continuation.py tests/test_runtime_position_ownership.py tests/test_risk_engine.py -q` — 146 passed after review follow-up |
| Selected Ruff checks | PASS — changed Python files, `--select F,E9` |
| Whitespace | PASS — `git diff --check` |
| Broker stop/freeze constraints and accepted readback | NOT TESTED |
| Paper replay, restart and ambiguous acknowledgement | NOT TESTED |
| Connext-Demo modification receipt | NOT TESTED; no broker command was sent |
| Live modification | NOT TESTED / DISABLED |

Review follow-up: trailing candidates now require a strict directional SL
improvement independently of the configured step threshold. This prevents
duplicate or weakening candidates when `step_points` is zero or negative.
Regression coverage checks both settings. The updated local regression set has
146 passing tests; hosted CI must rerun against the revised PR head.

Latest V4 follow-up adds a Paper integration case for a lost modify acknowledgement:
the simulated broker applies the stop, the adapter reports an exception, and the
existing `ExecutionGateway` confirms only after reading the broker-held SL/TP.
Repeating the same protection level is a no-op and does not issue a second
modification. `pytest tests/test_v4_single_target_manager.py -q` — **9 passed**.
This tests the Paper adapter path only; it is not proof of MT5 restart, power-loss,
stops/freeze, or Demo behavior.

## Remaining gates and rollback

U06 remains **PARTIAL / NOT ACCEPTED**. U05 durable modification intents are
available on the planning branch, but U01 still lacks a verified fresh market
quote and U05 staging/broker acceptance is incomplete. Before U06 acceptance,
verify broker stop/freeze checks, restart reconciliation, one-writer behavior,
and Paper then explicitly authorized Demo readback. No runtime, profile, broker,
or VM100 state was changed by this candidate.

Rollback is a revert of the U06 code/documentation commit. No schema migration,
configuration activation, service restart, or broker-state rollback is required.
