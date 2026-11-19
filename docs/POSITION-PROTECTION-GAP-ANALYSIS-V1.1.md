# Position Protection V1.1 — Gap Analysis

Date: 2026-11-19
Base: `plan/position-protection-v1-1` at `e4d0e7e`
Design authority: [`POSITION-PROTECTION-INTEGRATED-V1.1.md`](POSITION-PROTECTION-INTEGRATED-V1.1.md)

## Current behavior and safety gaps

| Area | Present in source | Gap against V1.1 | Risk / disposition |
|---|---|---|---|
| Break even and trailing | Existing `PositionManager.evaluate()` evaluates both and uses point thresholds. | No immutable initial-R state, cost-aware break even, shared candidate selection, explicit mode or version. Both can emit `modify` for one ticket in the same cycle. | Extend this manager; one candidate per position; retain legacy path and settings. |
| Partial close / exits | Same manager evaluates ladder partials, time exits and smart exits. | Partial and stop modifications may be emitted together; no policy precedence for competing actions. | Keep the single manager and define explicit candidate priority. Do not add another modifier loop. |
| Runtime dispatch | `_manage_cycle()` feeds actions to `_apply_action()`; `_apply_action()` uses `ExecutionGateway`. | It may dispatch a list of multiple actions. No per-position intent fence in this caller and no explicit protection mode. | Make planning deterministic and only pass one action/ticket/cycle; preserve the gateway as the sole write path. |
| Broker modification | `ExecutionGateway.modify()` validates account identity and appends `position_events` before/after a broker call. | `accepted_unverified` is not reconciled to a fresh broker position; no durable idempotency key/version conflict for modify, or explicit UNKNOWN lock. | Harden the existing gateway path; never blindly retry an ambiguous modification. |
| Persistence / audit | Append-only `position_events`, immutable pre-order snapshots, account identity and generic `kv` exist. | No versioned protection profile or durable per-position original risk / mode / operation state. | Add additive schema/profile migration; do not rewrite existing orders/events. |
| Risk / entry gates | RiskEngine gates entry; Smart100 and dynamic initial SL/TP are present in this branch. | Position manager has no independent veto on proposed modifications, and entry mode is not a position-protection mode. | Keep entry confirmation for entries only; require broker/risk safety checks for modifications. |
| Config | `config/risk.yaml` enables legacy BE (250 points), trailing (500 points), partials 40/30/30, and `flatten_on_breach: true`; risk limits include 5% weekly, 10% DD and 1.30 min RR. | V1.1 proposal is stricter/different and must not silently replace these values. | Preserve the current active profile. Add V1.1 as an inactive, versioned profile and explicit migration/rollback. |
| Broker / EA | Broker adapters expose `modify_position`; bridge has execution command flow. | Position-manager acceptance does not establish broker confirmation or stop/freeze validity at the final write boundary. | Re-fetch, validate, issue once, and reconcile via the existing adapter/gateway. |
| API / dashboard | Risk page, position list, point calculator, and trade review routes exist. | No protection preview/apply/pause/state endpoints or dedicated view; calculator is not linked to a shared protection policy. | Add authenticated, account-scoped read/preview/mutation routes and a Vue view; mutations require idempotency/version. |
| Analyzer | Backtest supports management rules and trade reports. | No paired comparison measuring protection performance versus no-protection using identical entries/data/costs. | Add a read-only analyzer after policy/replay evidence is stable; distinguish replay from REAL ticks. |
| Tests | Runtime ownership, account identity, gateway recovery, event log, snapshot and UI smoke tests exist. | No focused PositionManager policy suite for BUY/SELL monotonicity, initial R, modes, conflicting actions, or protection reconciliation faults. | Add deterministic unit, integration, reconciliation and failure tests before any Demo request. |

## Implementation boundary

1. Preserve current effective `config/risk.yaml` and legacy manager behavior until a reviewed migration is explicitly activated.
2. Add a separately named V1.1 profile in PAPER/manual-preview mode, with BE/trailing automatic modification disabled by default and LIVE auto permanently unavailable.
3. Reuse `PositionManager`, `ExecutionGateway`, broker adapters, `PositionEventLog`, `RiskEngine`, the existing calculator, and existing confirmation/initial-plan gates.
4. No new-position path is introduced by protection. A manager operation can only reference a freshly verified open position.
5. This worktree has no operator authorization for MT5 Demo modification. Paper tests are allowed; Demo test status remains NOT TESTED until separately authorized.

## Verification baseline

This document records source inspection, not a claim that tests passed. Baseline tests will be run before implementation; final evidence will list command, result, and explicit NOT TESTED items. No Live Auto Trading, merge, or deployment is part of this change.
