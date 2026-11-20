# No7 AI Trading Pro — Unified Task Register V4
This is a PLANNING SNAPSHOT created 2026-11-19 from GitHub source inspection. No new feature is certified complete by this file. Update this register with evidence in the SAME PR as each implementation. Do not infer production readiness from file presence.

Status definitions: EXISTS_CODE = seen in repository but not live certified; NEEDS_AUDIT = not verified against current branch/tests; PLANNED = authorized design only; BLOCKED = needs decision/test evidence; DONE requires exact commit + tests + acceptance receipt.

| ID | Phase | Owner code path | Baseline status | Specific next task | Acceptance evidence |
|---|---|---|---|---|---|
| U00 | Audit | docs/, tests/, config/ | DONE (source audit; live feed unavailable) | See `docs/audits/U00-PROJECT-AUDIT-2026-11-21.th.md`; VM100 8000 is development/simulated, 18081 is isolated staging on another branch with stale feed | commits `85c3936`, `fe9f1c4`; baseline `559a2de`; focused test/build receipt in audit report; backup restore and fresh feed remain NOT TESTED |
| U01 | Market data | services/market_data/, brokers | PARTIAL / BLOCKED (publisher code added; staging still stale/old branch) | freshness rejects excessive future ticks; bridge normalizes its explicit server clock; add a separate, data-only publisher endpoint and PC publisher. Next align isolated 18081 to this V4 source, verify canonical Demo symbol and capture fresh quote/rates; do not touch 8000 | run future/stale/clock-skew, bridge, publisher and preflight tests; MetaEditor compile + fresh timestamped Demo quote + V4 staging health receipt |
| U02 | Signal confirmation | services/strategy_engine/ | PLANNED | single 100-point WAIT state + closed M1/M5, timeout, dedup | 99/100-point/expiry/replay tests |
| U03 | Risk profile | services/risk_engine/ config/risk.yaml | EXISTS_CODE | add VERSIONED candidate separately; audit precedence with legacy | invariants, no activation, config diff |
| U04 | Initial SL/TP | services/risk_engine/planner.py | EXISTS_CODE | broker-aware ATR/structure and costs with single planning source | lot min and net RR tests |
| U05 | Execution/modify | services/execution_gateway/, bridge/ | EXISTS_CODE / UNVERIFIED | inspect exact MT5 modify capability; add durable guarded single writer | broker response/unknown/restart tests |
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
- Test definitions were ported with the code; exact V4 worktree rerun results, MetaEditor compilation and live Demo post-change capture are pending. Rollback: revert these two focused commits; no runtime/config defaults were activated beyond the 2-second future-tick tolerance.
- No EA compile, publisher start, service restart, order or deployment was performed by these source commits.

### U01 implementation delta — isolated market publisher (source only)

- Reused `POST /api/market/publish/mt5` and `scripts/mt5_market_publisher.py` from existing commit `329ebc9`; separate publisher token and exact Demo identity are required. Its strict data-only schema cannot carry positions or commands and it does not call BridgeRelay register/poll/enqueue/ack. The route remains disabled by default and uses an isolated account cache namespace.
- `scripts/check_mt5_market_runtime.py` checks health and OpenAPI only; it performs no POST and does not need a bridge token. Publisher/freshness/cache/time validation tests were added in the same source commit. Current VM100 port 18081 still runs `feature/u02-100pt-confirmation` at `06642a0`, `feed_mode=mt5_demo_publisher_stale`, `fresh=false`; PC tunnel 18181 responds but no publisher process is running.
- Source-only at this point: do not use the older poll-based publisher because it can drain bridge commands when the EA bridge is writable. No bridge flags were changed, no order sent, and no VM restart/deploy was performed. Rollback: set the separate publisher enable flag false or revert the focused source commits.

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
