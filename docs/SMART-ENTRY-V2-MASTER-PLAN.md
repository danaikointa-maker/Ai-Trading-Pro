# No7 AI Trading Pro V2 — Smart Entry & Auto Zone Master Plan

Status: IN PROGRESS. This is a development plan, not a trading-system acceptance or profitability claim.
Source of truth: this repository's executable code and current tests. Historical docs may be stale.
Branch: `feature/smart-entry-v2`. No changes to `main` without review.

## Goal
Extend the existing FastAPI / Vue 3 / Lightweight Charts / MT5-adapter architecture. Do not replace existing zone, structure, risk, execution, backtest, journal or authentication modules.

### Feature-to-code map
| Capability | Existing basis | V2 extension | Acceptance |
|---|---|---|---|
| W-Flip support/resistance | `packages/strategy_rules/zones.py` and `packages/market_structure/` | Detect confirmed break and subsequent retest using only closed candles; persist event evidence | Deterministic tests: break, retest, invalidation, no future leakage |
| Fibonacci 50–61.8 | Existing `fibonacci` family in zones | Named anchor swing and configurable retracement band | Tests for both directions, anchor age, no repaint |
| Multi-TF trend and momentum | `services/strategy_engine/analysis.py` M1/M5/M15/H1/H4 | Stochastic K/D on 3 selected frames, stale/missing frame veto | Alignment and conflicting-signal tests |
| Signal lifecycle | Signal score and WAIT/NO_TRADE | SCANNING → WAIT → READY / EXPIRED / BLOCKED, with reason codes | Transition tests; blocked never executes |
| Plan generation | `TradePlan`, risk engine | Up to 3 **proposals** per scan, not 3 automatic positions | Aggregate exposure and per-account limits enforced |
| Visual overlays | Vue 3 Lightweight Charts | Per-layer and per-trade toggles: SR, flip, fib, structure, entry, SL, TP, closed orders | Hiding layers never changes analysis, execution or stored plans |
| Trade snapshots | Journal, persistence, execution IDs | Immutable pre-order original plan, versioned live revisions, fill/deal ledger mapping | Reopen a closed order with its historical levels exactly preserved |
| MT5 execution | Existing gateway, EA bridge, broker adapters | Reconciliation, duplicate protection, partial fill, manual terminal changes | Demo-only disconnect/restart and fail-closed evidence |
| Validation | Existing pytest/backtest/walk-forward | Point-in-time replay, cost-aware OOS, demo forward tests | Documented pass/fail gates, not a win-rate promise |

## Mandatory architecture
1. Analytics and decision services own canonical zone/plan state; chart visibility is a user preference and must not mutate it.
2. A plan has `analysis_id`, `plan_id`, `strategy_version`, `source_timestamp`, `symbol`, `broker_id`, `timeframe`, `zone_ids`, `entry`, `sl`, `tp`, `risk_decision`, and `created_at`.
3. Persist the ORIGINAL plan before order submission. Every subsequent adjustment is a separate append-only event with time and actor. Preserve mapping to broker order, position, and deal IDs, including partial fills.
4. Only completed bars may confirm a swing, break or retest; distinguish candidates from confirmed events. Never use later candles when replaying an earlier decision.
5. LLM may explain but may not send, approve or override orders. Risk veto and account/environment authorization remain independent.
6. Default PAPER/DEMO, full auto disabled. No credentials or trading permission changes in this branch.
7. An unverified broker state, stale feed, news lockout, bad spread, missing contract spec, or duplicate/ambiguous order => block new orders.
8. Show historical levels as they existed at decision time, not levels recalculated from the present.

## Implementation stages
- P0: audit baseline, identify canonical repository/branch, inspect docs conflicts, run existing Windows verification and CI; record evidence.
- P1: extend SR/flip and Fibonacci detection with closed-bar provenance and tests.
- P2: add three-timeframe Stochastic/trend agreement, explicit WAIT/READY/EXPIRED/BLOCKED states and notification events.
- P3: build at most three independent trade proposals with risk-approved lot, stops and net RR; never assume proposals equal executions.
- P4: add Vue chart overlay toggles (global, per-layer, per-order) and keep engine independent.
- P5: add immutable original plan, append-only revisions and historical replay with broker reconciliation.
- P6: harden order lifecycle on MT5 Demo, including partial fills, duplicate commands, restart and manual broker changes.
- P7: test point-in-time correctness, walk-forward OOS on real data, realistic tick/spread/slippage costs, demo forward validation, operator release/rollback.

## Delivery rules
- Small PRs, each with changed-file inventory, tests and limitations.
- Keep `main` unchanged until reviewed.
- Never claim a successful local test, MT5 demo acceptance, or profitability without evidence.
- Preserve current server responsibilities and safety guidance; do not alter Proxmox storage, networking, or trading accounts.
- Before any LIVE enablement: independent explicit operator authorization and verified release gates.

## Draft PR #24: implemented vertical slice
- Pure SR Flip detector, plus read-only confirmed flip readings from **previously confirmed** M5 swing levels (with source swing, breakout and retest timestamps); no extra trading signal or executor action.
- Read-only named Fibonacci 50% / 61.8% band anchored to the last two confirmed opposite M5 swings, with anchor and confirmation timestamps. The existing zone-engine Fibonacci family is not replaced.
- Additive, backward-compatible `AnalysisSnapshot.sr_flips` and `AnalysisSnapshot.fibonacci_band` fields consumed by the dashboard.
- Dashboard chart switches for EMA, S/R, SR Flip, Fibonacci, BOS/CHoCH, signal plan Entry/SL/TP, and current positions. Switches are stored only in browser local storage, not in trading state.
- Closed-trade review displays a **price-level diagram**, separately switchable between the archived linked signal's original Entry/SL/TP and executed Entry/Exit. It never reconstructs missing historical levels from today's data, and is not yet a historical candlestick replay.
- Focused tests cover pre-retest silence, wrong-side and unconfirmed swings, stale Fibonacci anchors, bullish and bearish retracement maths. Dashboard bundle must build.

### What is still missing / not production-ready
- Preserve a complete, immutable per-order **pre-submission** snapshot (all zone bounds, structure, flip, Fibonacci, original plan and risk state), with append-only revisions, order/position/deal mapping and partial-fill reconciliation.
- Per-order overlays on a **historical candlestick** chart; the current closed-trade level diagram is a transparent interim visualization.
- Three-timeframe Stochastic, formal WAIT/READY/EXPIRED/BLOCKED lifecycle and alerts, up-to-three proposed entries, and integrated risk validation of those proposals.
- Full replay/walk-forward tests, MT5 demo reconciliation/disconnect testing, security and deployment gates. Auto-trade permissions and LIVE settings are **untouched**.

Do not interpret a displayed flip or Fibonacci band as a validated entry. Hidden chart lines have no influence on signal evaluation, risk checks or execution.
