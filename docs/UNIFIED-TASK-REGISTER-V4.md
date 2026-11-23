# No7 AI Trading Pro — Unified Task Register V4
This is a PLANNING SNAPSHOT created 2026-11-19 from GitHub source inspection. No new feature is certified complete by this file. Update this register with evidence in the SAME PR as each implementation. Do not infer production readiness from file presence.

Status definitions: EXISTS_CODE = seen in repository but not live certified; NEEDS_AUDIT = not verified against current branch/tests; PLANNED = authorized design only; BLOCKED = needs decision/test evidence; DONE requires exact commit + tests + acceptance receipt.

| ID | Phase | Owner code path | Baseline status | Specific next task | Acceptance evidence |
|---|---|---|---|---|---|
| U00 | Audit | docs/, tests/, config/ | DONE (source audit; live feed unavailable) | See `docs/audits/U00-PROJECT-AUDIT-2026-11-21.th.md`; VM100 8000 is development/simulated, 18081 is isolated staging on another branch with stale feed | commits `85c3936`, `fe9f1c4`; baseline `559a2de`; focused test/build receipt in audit report; backup restore and fresh feed remain NOT TESTED |
| U01 | Market data | services/market_data/, brokers | PARTIAL / BLOCKED (source/tests pass; staging publisher has no PC process; full stage replacement has U05 persistence parity risk) | Freshness, explicit clock normalization and separate data-only PC publisher are in V4. Existing 18081 endpoint schema accepts the UTC payload, but feed remains stale. Publisher validates required settings together and reports per-symbol stale reasons. Configure the read-only publisher locally without exposing token; verify current Demo identity, quote/rates/specs, freshness and stale/reconnect behavior. If replacing the whole stage checkout, resolve U05 durable modify-intent parity first. Never touch 8000 | Current six-file V4 regression: 111 passed, one existing warning; Vite 5.4.21 build passed (624 modules). Stage preflight: route/health true, `fresh=false`. Still need PC Demo quote receipt, `fresh=true`, rate/spec comparison, MetaEditor compile and stale/reconnect acceptance |
| U02 | Signal confirmation | services/strategy_engine/ | PLANNED | single 100-point WAIT state + closed M1/M5, timeout, dedup | 99/100-point/expiry/replay tests |
| U03 | Risk profile | services/risk_engine/ config/risk.yaml | DONE | Inert `conservative_v4_candidate` added in commit `5386519f99f601eb7f8d735472a88332e99aab42`; runtime continues loading legacy `risk.yaml`; no migration/activation | `tests/test_risk_profile_candidate.py` and `tests/test_invariants.py tests/test_risk_engine.py` — 37 passed; candidate activation and legacy isolation assertions |
| U04 | Initial SL/TP | services/risk_engine/planner.py | PARTIAL / NOT ACCEPTED (candidate planner code and isolation tests; broker execution evidence absent) | Keep the shared planner and one inactive candidate profile; verify order_check, margin, stops/freeze constraints and post-fill accepted SL/TP through existing ExecutionGateway on explicitly approved Demo | planner/risk regression tests; candidate isolation; Demo receipts still required; no profile activation |
| U05 | Execution/modify | services/execution_gateway/, bridge/ | PARTIAL / BLOCKED (local V4 durable-ledger candidate tests pass; staging parity and Demo acceptance unverified) | Reuse the existing single ExecutionGateway path and preserve the stage ledger behavior. See `docs/U05-POSITION-MODIFY-STAGING-AUDIT-V4.md` and `docs/audits/U05-DURABLE-POSITION-MODIFY-2026-11-23.th.md`. Verify guarded single-writer/restart recovery and obtain explicitly authorized Connext-Demo modify/readback only after U01 fresh-feed acceptance; do not replace/restart staging yet | `test_position_modify_intents.py`: 35 passed; seven-file execution/account/bridge regression: 156 passed; Paper ticket reuse across epochs and legacy migration; staging regression; broker response/readback receipt; rollback preserves DB/table |
| U06 | Position protection | services/risk_engine/manager.py | EXISTS_CODE | refactor BE+trail candidate evaluation; never double modify or widen SL | BUY/SELL/partials/BE/trail/race tests |
| U07 | Operating modes | api_gateway + UI | PLANNED | 4 protection modes, scoped RBAC, versioned override | auth, audit, concurrency tests |
| U08 | Calculators | shared calculation + Vue | PLANNED | audit current points calculator; extend to 16 without duplicate math | MT5 comparison, offline/source-label tests |
| U09 | Dashboard | apps/web-dashboard | EXISTS_CODE | Protection UI, short markers, stable zoom, realtime events | screenshot/browser chart stability check |
| U10 | Alerts | services/notification | EXISTS_CODE | integrate idempotent signals/protection events | no duplicate alert/trade tests |
| U11 | Demo acceptance | tests/, scripts/ | BLOCKED | approve and conduct real broker Demo/power-loss/partial-fill tests | receipts and rollback, no LIVE |
| U12 | AI Trader Team | integrations/no7_local_ai/ | PLANNED | read-only shared research/observability | explicit non-execution access test |
| U13 | Documentation sync | README/API/MATH/RUNBOOK/LIMITATIONS | PLANNED | patch tech docs only alongside code changes | docs checklist in each PR |

### U01 implementation delta — future-tick refusal and broker clock normalization

- Source commits reused from the existing feature branch: `21a8b65` (reject future ticks) and `5952e42` (same-snapshot broker-server/UTC normalization). No second market service was created.
- `MarketDataService.data_quality()` now fails closed when a tick is beyond the configured clock-skew tolerance. `BridgeBroker` normalizes quote, candle and position timestamps only when a declared broker-server snapshot has a valid, fresh UTC anchor; the EA now emits that anchor. Market candles expose display-clock metadata.
- V4 focused rerun: included with the publisher regression command below; MetaEditor compilation and live Demo post-change capture remain NOT TESTED. Rollback: revert the focused clock/freshness commits; no runtime/config defaults were activated beyond the 2-second future-tick tolerance.
- No EA compile, publisher start, service restart, order or deployment was performed by these source commits.

### U01 implementation delta — isolated market publisher (source only)

- Reused `POST /api/market/publish/mt5` and `scripts/mt5_market_publisher.py` from existing commit `329ebc9`; separate publisher token and exact Demo identity are required. Its strict data-only schema cannot carry positions or commands and it does not call BridgeRelay register/poll/enqueue/ack. The route remains disabled by default and uses an isolated account cache namespace.
- `scripts/check_mt5_market_runtime.py` checks health and OpenAPI only; it performs no POST and does not need a bridge token. V4 focused regression command passed **99 tests** with one pre-existing Starlette/httpx deprecation warning; dashboard build passed (Vite 5.4.21, 624 modules). Preflight via PC tunnel port 18181 found health and route, but `publisher_fresh=false`, `ready=false`. VM100 port 18081 still runs `feature/u02-100pt-confirmation` at `06642a0`, `feed_mode=mt5_demo_publisher_stale`; PC tunnel responds but no publisher process is running.
- Runtime acceptance is blocked, not source implementation: do not use the older poll-based publisher because it can drain bridge commands when the EA bridge is writable. No bridge flags were changed, no order sent, and no VM restart/deploy was performed. Rollback: set the separate publisher enable flag false or revert the focused source commits.
- Follow-up safety comparison: VM100 staging commit `06642a0` contains `position_modify_intents` persistence and reservation/reconciliation helpers. The V4 candidate now carries the additive table and existing gateway integration; see the U05 audit and PR evidence. Actual staging runtime parity remains NOT TESTED. Staging was deliberately not restarted or switched. The existing 18081 publisher endpoint schema accepts the V4 UTC payload shape; it remains stale because the read-only PC publisher has not been started. PC-local publisher credentials are not configured in the workspace `.env`; provision them through the user's local secret mechanism without copying or displaying token values.
- U05 read-only staging audit (2026-11-23): see `docs/U05-POSITION-MODIFY-STAGING-AUDIT-V4.md`. At `/home/danai/no7-ai-trading-pro-v4-staging` (`06642a0`), opened `storage/db/no7-v4-staging.sqlite3` via SQLite `mode=ro`; `PRAGMA quick_check=ok`, composite account/ticket/idempotency primary key and partial unique unresolved-intent index present, aggregate row count **0**. No payload/ticket/account rows were read. V4 candidate adds an additive ledger and guarded gateway reconciliation; local parity is not VM100 runtime acceptance. Port 18081 returned health OK but feed remained stale (`fresh=false`, about 164,222s old). No restart, write, order or deployment occurred.
- Freshness diagnostic follow-up: `scripts/mt5_market_publisher.py` now identifies per-symbol reasons when withholding a quote (missing symbol info/tick, invalid Bid/Ask/timestamp, future tick or stale tick age). It does not loosen the 1–15 second freshness bound. Regression command over the six U01 test files: **106 passed**, one existing Starlette/httpx deprecation warning; no MT5 orders or staging changes.
- Recheck on 2026-11-22: V4 worktree and `origin/plan/unified-development-v4` both at `9c980ed`; the six U01 regression files again passed **106 tests** (one existing deprecation warning). GET-only preflight through `127.0.0.1:18181` returned `health_api=true`, `publisher_route=true`, `publisher_fresh=false`, `feed_mode=mt5_demo_publisher_stale`, `ready=false`. User-provided publisher output on 2026-11-21 reported `XAUUSD` tick age **45,990.2s** against a 10s maximum. This is explicitly a stale-data rejection, not API readiness; no snapshot was forwarded. U01 remains blocked on a fresh verified Demo tick.
- Publisher configuration follow-up: startup now validates all five required PC settings at once and lists only missing key names; invalid/non-positive expected login is rejected with a clear message. Publisher script/API/preflight tests: **39 passed**, one existing warning; all six U01 regression files: **111 passed**, one existing warning. `RUNBOOK.md` documents the VM `.env` key location and the need to configure a separate PC process value without exposing the token. No runtime config was changed.
- Windows publisher configuration follow-up (2026-11-23): the publisher now reads only its explicit `NO7_MT5_MARKET_*` allowlist (plus terminal path) from the checkout `.env` when a process value is absent; process values win, and bridge/broker credentials are excluded. Added local `.env.example` guidance and tests. `python -m pytest -q tests/test_mt5_market_publisher_script.py tests/test_mt5_market_publisher.py tests/test_mt5_runtime_preflight.py`: **41 passed**, one existing Starlette/httpx deprecation warning. Current developer shell has no MT5 terminal process and no publisher settings in its process environment; the user's checkout `.env` key-name check also found the five required PC settings absent. Therefore no MT5/API publish was attempted, real Demo freshness remains NOT TESTED, and U01 stays BLOCKED pending a verified fresh tick and provisioned server token.

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
