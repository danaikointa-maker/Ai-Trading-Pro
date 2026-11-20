# No7 AI Trading Pro — Unified Task Register V4
This is a PLANNING SNAPSHOT created 2026-11-19 from GitHub source inspection. No new feature is certified complete by this file. Update this register with evidence in the SAME PR as each implementation. Do not infer production readiness from file presence.

Status definitions: EXISTS_CODE = seen in repository but not live certified; NEEDS_AUDIT = not verified against current branch/tests; PLANNED = authorized design only; BLOCKED = needs decision/test evidence; DONE requires exact commit + tests + acceptance receipt.

| ID | Phase | Owner code path | Baseline status | Specific next task | Acceptance evidence |
|---|---|---|---|---|---|
| U00 | Audit | docs/, tests/, config/ | DONE | Audit receipt: [U00 Project Audit V4](U00-PROJECT-AUDIT-V4.md); audit receipt commit `21a8b65cd11a81e5ac39a86da97dc6fd1564b321`; baseline `559a2ded5dc1530cfcb61072e2432220742f6d0d` | Signed gap matrix, source/test links and current host receipts in U00 report |
| U01 | Market data | services/market_data/, brokers | BLOCKED / PARTIAL | Bridge EA now declares broker-server timestamps with same-snapshot UTC anchor; adapter normalizes tick/M1/position timestamps and rejects malformed/out-of-range anchors. Need a new bridge snapshot from the compiled EA; validate DST transitions and symbol provenance before U02 consumes live data | Bridge/market/signal/API tests: 50 passed; frontend production build + Ruff + `git diff --check` passed; MetaEditor compiled worktree EA: 0 errors/0 warnings. Read-only PC MT5 Demo capture found `XAUUSD.s` tick epoch +7,200 s vs PC UTC. Post-change bridge snapshot and DST/offset transition evidence NOT TESTED |
| U02 | Signal confirmation | services/strategy_engine/ | PARTIAL / NOT ACCEPTED | Existing strategy signals now pass through an opt-in persistent 100-point confirmation candidate before the existing Risk Engine gate. Candidate profile is separate and not loaded; validate anchor/point semantics, U01 broker timestamps, Paper replay, then approved Demo before accepting | `docs/U02-SIGNAL-CONFIRMATION-V4.md`; unit evidence in `tests/test_signal_confirmation_v4.py`; Paper/Demo NOT TESTED |
| U03 | Risk profile | services/risk_engine/ config/risk.yaml | PARTIAL / NOT ACCEPTED | Candidate artifact at commit `57f34a5c83d613adbc270d7d083985c028338952`; executable `legacy_v1` remains unchanged. Current RiskLimits cannot enforce aggregate open-risk 1% or max 5 trades/day; extend only after an approved, tested migration. Paper A/B and Demo remain NOT TESTED | `docs/U03-RISK-PROFILE-V4.md`; `tests/test_v4_risk_candidate.py` 2 passed; no activation |
| U04 | Initial SL/TP | services/risk_engine/planner.py | PARTIAL / NOT ACCEPTED | Added candidate-only outward SL/TP tick rounding and a shared Auto/Manual `PlanInputs` builder in the existing `TradePlanner`; directional rounding remains off by default. Remaining gaps: ATR+structure candidate policy, single-2R/partials-off execution semantics, broker margin/freeze and post-fill confirmation | `docs/U04-INITIAL-SLTP-GAP-ANALYSIS-V4.md`; planner/spec/Risk/signal regressions: 80 passed; Paper/Demo NOT TESTED |
| U05 | Execution/modify | services/execution_gateway/, bridge/, broker_accounts | BLOCKED / PARTIAL | PR #36 adds read-only snapshot only and is not deployed. VM100 currently runs a dirty `integration/unified-tradeai` checkout with simulation feed, bridge disabled/read-only, and active API GET probes for source-defined Demo execution routes return 404. V4 dashboard exposes Demo validation/positions as read-only; `/api/trading/order` targets only the active runtime adapter, not a managed-account id. Align runtime/API ownership and resolve U01 before a guarded Demo order path; preserve the single ExecutionGateway | automated read-only identity/API tests pass; active API route mismatch receipt in U00 report; no Demo command implemented/authorized in this branch, no order/modify sent; guarded Demo execution and reconciliation tests remain |
| U06 | Position protection | services/risk_engine/manager.py | EXISTS_CODE | refactor BE+trail candidate evaluation; never double modify or widen SL | BUY/SELL/partials/BE/trail/race tests |
| U07 | Operating modes | api_gateway + UI | PLANNED | 4 protection modes, scoped RBAC, versioned override | auth, audit, concurrency tests |
| U08 | Calculators | shared calculation + Vue | PLANNED | audit current points calculator; extend to 16 without duplicate math | MT5 comparison, offline/source-label tests |
| U09 | Dashboard | apps/web-dashboard | PARTIAL / NOT DEPLOYED | PR #36 adds linked read-only positions selector/manual refresh, but it is not in the active VM/backend runtime. Current local app proxy and VM backend are from separate dirty `integration/unified-tradeai` checkouts; browser/API build alignment and trade-control status must be verified after reviewed release | Vue build passes; live API route mismatch recorded in U00; browser/session screenshot and order flow NOT TESTED |
| U10 | Alerts | services/notification | EXISTS_CODE | integrate idempotent signals/protection events | no duplicate alert/trade tests |
| U11 | Demo acceptance | tests/, scripts/ | BLOCKED | approve and conduct real broker Demo/power-loss/partial-fill tests | receipts and rollback, no LIVE |
| U12 | AI Trader Team | integrations/no7_local_ai/ | PLANNED | read-only shared research/observability | explicit non-execution access test |
| U13 | Documentation sync | README/API/MATH/RUNBOOK/LIMITATIONS | PLANNED | patch tech docs only alongside code changes | docs checklist in each PR |

### U01 implementation delta — broker-server timestamp normalization

- Branch: `feature/u05-readonly-mt5-positions`; baseline `2e47af9b34f8f819ba26b34b06a5330828164cc3`.
- EA snapshots now label broker-server timestamps and include `TimeTradeServer()` plus `TimeGMT()` as same-snapshot anchors. `BridgeBroker` computes the offset (no fixed timezone assumption), normalizes tick, M1 bars and position open times to UTC, and rejects malformed anchors or offsets outside ±14 hours. Legacy unmarked snapshots retain their prior contract.
- Tests: `python -m pytest tests/test_bridge.py tests/test_market_snapshot.py tests/test_smart_entry_continuation.py tests/test_api.py::test_market_candles_expose_broker_clock_for_chart_display -q` — **50 passed**, one existing Starlette deprecation warning; `npm run build` — passed; Ruff + `git diff --check` — passed.
- MetaEditor compiled the worktree EA: `Result: 0 errors, 0 warnings`; generated `.ex5` is a local ignored build artifact. Read-only direct MT5 probe verified a Demo terminal/server and `XAUUSD.s` quote; its tick epoch was 7,200 s ahead of PC UTC. This confirms the reported clock defect but does not certify the bridge EA's new anchor until that EA is attached and sends a snapshot.
- Market candles API returns clock metadata; chart renders broker-server clock from normalized UTC timestamps and identifies display offset. NOT TESTED: bridge EA post-change host snapshot, broker DST transitions/history, browser visual acceptance. No order/modify, account toggle, merge or deployment performed.
- Rollback: revert this focused commit; the EA will again emit unmarked timestamps and existing freshness gate will fail closed on the observed +7200-second feed.

### U05/U09 implementation evidence — read-only MT5 positions

- Work branch: `feature/u05-readonly-mt5-positions`; base commit `559a2ded5dc1530cfcb61072e2432220742f6d0d`.
- Added `GET /api/broker-accounts/{id}/positions` for a previously validated `ready_read_only` MT5 Demo account. It re-checks account identity around the read, returns broker SL/TP and fetch time, rejects unavailable/unknown position snapshots, and sets `execution_enabled:false`. Dashboard/Trades Positions now keeps this snapshot separate from runtime/simulator positions and hides close controls in read-only mode.
- Automated evidence: focused + regression command covering `tests/test_mt5_readonly.py`, `tests/test_mt5_windows_pc_readonly.py`, `tests/test_accounts.py`, `tests/test_api.py`, `tests/test_positions_ui.py`, `tests/test_bridge_readonly.py`, `tests/test_execution_recovery.py`, `tests/test_runtime_position_ownership.py`, `tests/test_mt5_reconnect_safety.py`, `tests/test_position_snapshot_atomic.py`, `tests/test_account_ownership.py`, `tests/test_history_account_ownership.py`, and `tests/test_bridge.py` — **320 passed**, 1 dependency deprecation warning. Vue production build passed.
- External acceptance: actual Windows MT5/Connext Demo read, live terminal UI, and browser screenshot **NOT TESTED**. No trade or position modification was sent. U05 remains `UNVERIFIED`; do not mark DONE until broker/host receipt is reviewed.

## Anti-duplication ledger
- Do NOT create a second RiskEngine or PositionManager. Existing: `services/risk_engine/engine.py`, `manager.py`.
- Do NOT create a second order execution gateway. Existing: `services/execution_gateway/`.
- Do NOT create a new Laravel backend or a new DB engine by default.
- Do NOT implement calculator math separately in frontend and backend; backend authoritative.
- Do NOT run earlier Master prompts as tasks. Map ideas into exactly one U-ID above.
- Do NOT mark any U-ID DONE from previous claims without independently checking current branch and supporting execution evidence.

## Task update template
ID:
Owner and branch:
Baseline commit:
As-is evidence:
Delta and why not duplicate:
Files changed:
Dependencies:
Tests and exact results:
Demo/host verified or NOT TESTED:
Security and migration impact:
Rollback:
Status and next block:
