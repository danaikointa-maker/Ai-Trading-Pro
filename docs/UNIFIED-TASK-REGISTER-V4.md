# No7 AI Trading Pro — Unified Task Register V4
This is a PLANNING SNAPSHOT created 2026-11-19 from GitHub source inspection. No new feature is certified complete by this file. Update this register with evidence in the SAME PR as each implementation. Do not infer production readiness from file presence.

Status definitions: EXISTS_CODE = seen in repository but not live certified; NEEDS_AUDIT = not verified against current branch/tests; PLANNED = authorized design only; BLOCKED = needs decision/test evidence; DONE requires exact commit + tests + acceptance receipt.

| ID | Phase | Owner code path | Baseline status | Specific next task | Acceptance evidence |
|---|---|---|---|---|---|
| U00 | Audit | docs/, tests/, config/ | DONE | Audit receipt: [U00 Project Audit V4](U00-PROJECT-AUDIT-V4.md); audit receipt commit `21a8b65cd11a81e5ac39a86da97dc6fd1564b321`; baseline `559a2ded5dc1530cfcb61072e2432220742f6d0d` | Signed gap matrix, source/test links and current host receipts in U00 report |
| U01 | Market data | services/market_data/, brokers | BLOCKED / PARTIAL | Freshness now rejects tick timestamps more than configured 2 s clock-skew tolerance in the future; real Connext Demo capture found XAUUSD.s ~7200 s ahead of PC. Resolve authoritative server-time mapping and capture symbol provenance before U02 depends on freshness | recent/stale/future/tolerance tests; normalized server-time capture, DST/offset tests and broker tick provenance still required |
| U02 | Signal confirmation | services/strategy_engine/ | PLANNED | single 100-point WAIT state + closed M1/M5, timeout, dedup | 99/100-point/expiry/replay tests |
| U03 | Risk profile | services/risk_engine/ config/risk.yaml | EXISTS_CODE | add VERSIONED candidate separately; audit precedence with legacy | invariants, no activation, config diff |
| U04 | Initial SL/TP | services/risk_engine/planner.py | EXISTS_CODE | broker-aware ATR/structure and costs with single planning source | lot min and net RR tests |
| U05 | Execution/modify | services/execution_gateway/, bridge/, broker_accounts | EXISTS_CODE / UNVERIFIED | read-only Demo positions snapshot is implemented for an already `ready_read_only` managed account; next verify on Windows/Connext. Separately inspect modify capability and durable guarded single writer | mocked identity/SLTP/auth tests pass; real broker snapshot NOT TESTED; modify response/unknown/restart tests remain |
| U06 | Position protection | services/risk_engine/manager.py | EXISTS_CODE | refactor BE+trail candidate evaluation; never double modify or widen SL | BUY/SELL/partials/BE/trail/race tests |
| U07 | Operating modes | api_gateway + UI | PLANNED | 4 protection modes, scoped RBAC, versioned override | auth, audit, concurrency tests |
| U08 | Calculators | shared calculation + Vue | PLANNED | audit current points calculator; extend to 16 without duplicate math | MT5 comparison, offline/source-label tests |
| U09 | Dashboard | apps/web-dashboard | EXISTS_CODE | Positions table can select a linked read-only Demo account and manually refresh a broker snapshot; next verify browser layout and stale/error presentation. Protection UI, short markers, stable zoom remain | frontend build/browser screenshot plus broker snapshot evidence; browser and broker acceptance NOT TESTED |
| U10 | Alerts | services/notification | EXISTS_CODE | integrate idempotent signals/protection events | no duplicate alert/trade tests |
| U11 | Demo acceptance | tests/, scripts/ | BLOCKED | approve and conduct real broker Demo/power-loss/partial-fill tests | receipts and rollback, no LIVE |
| U12 | AI Trader Team | integrations/no7_local_ai/ | PLANNED | read-only shared research/observability | explicit non-execution access test |
| U13 | Documentation sync | README/API/MATH/RUNBOOK/LIMITATIONS | PLANNED | patch tech docs only alongside code changes | docs checklist in each PR |

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
