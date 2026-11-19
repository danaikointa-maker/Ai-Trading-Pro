# No7 AI Trading Pro — UNIFIED MASTER PLAN V4
Status: PROPOSED DOCUMENTATION BRANCH ONLY; NO RUNTIME DEPLOYMENT; NO LIVE AUTHORIZATION.
Updated: 2026-11-19. Owner-approved acceptance and testing are required before replacing active defaults.

## 0. Purpose and canonical policy
This document is the SINGLE canonical feature-scope and implementation-plan reference for the next development iteration. Existing code and configuration are authoritative for AS-IS behavior, not statements of desired V4 behavior. Security constraints in `docs/blueprint-v3/AGENTS.md` and tested invariants OVERRIDE a feature request; this document cannot relax them. `docs/UNIFIED-TASK-REGISTER-V4.md` tracks execution state; `docs/UNIFIED-CONFLICTS-V4.md` tracks discrepancies. Earlier development prompts and `docs/POSITION-PROTECTION-INTEGRATED-V1.1.md` are historical inputs and MUST NOT be executed as independent backlogs. No prompt may override tests, verified broker behavior or account-specific risk gates.

Use one repository `danaikointa-maker/Ai-Trading-Pro`; one authoritative trading core and execution leader. DEV PC `C:\workspace\Ai-Trading-Pro` for source, VM100 `/opt/no7-ai-trading-pro` for FastAPI/Vue/quant/Risk, VM200 `C:\app\app\No7-Ai-Trading-Pro` for Windows MT5 Demo/EA; actual host connectivity must be verified. No Laravel rewrite, duplicate databases, duplicate RiskEngine, duplicate PositionManager, parallel live MT5 gateway or alternate order route.

## 1. Mandatory document precedence
1. Non-negotiable safety, current verified state and measured broker constraints: `docs/blueprint-v3/AGENTS.md`, `docs/SAFETY-HANDOFF.th.md`, `docs/LIMITATIONS.md` and tests. Highest priority.
2. THIS `docs/UNIFIED-MASTER-PLAN-V4.md`: target product scope, ownership and execution order.
3. `docs/UNIFIED-TASK-REGISTER-V4.md` and `docs/UNIFIED-CONFLICTS-V4.md`: current plan status and decisions; never treat unchecked tasks as implemented.
4. `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/MATH.md`, `docs/RUNBOOK.md`, `docs/DEVELOPMENT.md`: AS-IS technical contracts, verified operational instructions; update together with corresponding implementation changes.
5. `docs/blueprint-v3/MASTER-BLUEPRINT.md`, `docs/POSITION-PROTECTION-INTEGRATED-V1.1.md`, prior conversation prompts: reference/legacy designs, not independent marching orders.
When conflicts remain, preserve tested current behavior, flag BLOCKED and request decision; never silently pick the newest paragraph. AGENTS remains binding until approved migration.

## 2. Unified product workstreams
W0 Audit, safety baseline, broker/VM connectivity and backups; first gate.
W1 Market data and accurate bid/ask tick/symbol specs; freshness/provenance, correct XAUUSD mapping.
W2 Signals & 100 MT5-point confirmation with M1 closed candle + M5 trend, 300s expiry, 30-point chase cap (proposed), single deterministic state machine and cross-agent dedup.
W3 RiskEngine and initial trade plan: account equity risk 0.5%, aggregate <=1%, proposed weekly 4%, DD 8%, net RR >=1.5, one XAUUSD position, 5 trades/day. Candidate profile only; legacy still 5%,10%,1.3. Broker-aware SL structure+1.5x ATR(14) M5 and TP=2R when valid; lot calculated from potential loss incl costs; no trade if broker min lot exceeds risk. Exact thresholds not proven optimal; compare via real tick backtests.
W4 ExecutionGateway: one authorized intent/idempotency path, broker order and SL/TP validation, fill reconciliation; Windows bridge outbound to VM100; Demo only with explicit permission. Any uncertainty => fail closed for new entries.
W5 Position protection BE/trailing/partials: EXTEND `services/risk_engine/manager.py`; candidate policies feed ONE gateway modifier. New candidate policy BE at +1.0 initial R, cost-aware estimated BE; trailing after broker-confirmed BE at +1.5 initial R, 1.0x ATR distance, 0.2x ATR step, max 6/min/position (subject broker), never worsen SL nor remove TP, reconcile after restart. Four UI management modes Manual/Semi/Full/Hybrid are distinct from entry mode and cannot bypass safety. Candidate profile defaults modification AUTO OFF pending Demo validation. Legacy partial 40/30/30 retained as legacy preset; new proposed single 2R TP with partial OFF. Initial R at fill immutable.
W6 Trading Calculator & Learning Center: ONE shared calculation core with risk/planner; 16 tools, read-only/manual what-if, data sources LIVE_MT5/RISK_PROFILE/AI_SIGNAL/MANUAL, provenance and timezone, lot/PnL/BE/ATR/FX in account currency. Calculator UI never invokes trade/modify endpoint.
W7 Professional Vue Dashboard & notifications: current market feed freshness, signal progress, proposed vs confirmed SL, short-range chart markers, unchanged viewport and zoom, bilingual beginner explanations. Notifications idempotent and must not initiate order retries.
W8 Backtesting, demo acceptance, release management and rollback; A/B tests 100-point confirmation, BE/trailing vs no protection, actual tick spreads, drawdown/net PnL, outages, rate limits, account separation. Automated tests do NOT equal live or broker acceptance.
W9 AI Trader Team is a separate read-only research/explanation integration; AI has no execution authority.

## 3. State and order invariants
Entry: SIGNAL_DETECTED -> ALERTED -> WAIT_100_POINTS -> M1_M5_CONFIRMED -> PRETRADE_RISK_APPROVED -> INTENT_RESERVED -> ORDER_SUBMITTED -> BROKER_RECONCILED -> OPEN_PROTECTED. EXPIRED/INVALIDATED/REJECTED/UNKNOWN are explicit and never silently retry.
Protection: INITIAL_PROTECTED -> BE_ELIGIBLE -> BE_PENDING -> BE_BROKER_CONFIRMED -> TRAIL_ELIGIBLE -> TRAIL_ACTIVE. PAUSED/ERROR/UNKNOWN/CLOSED are explicit. Never infer broker confirmation from sending or ACK alone.
Only one accepted SL candidate per position per evaluation; choose strict monotonic improvement, validate newest broker status, lock per position, durable intent and independent confirmation.
Stops remain on broker when app offline; unsafe modify blocked. Kill switch blocks entries but does not automatically liquidate on stale/unconfirmed data. Distinguish flatten policy review before changing existing `flatten_on_breach`.

## 4. Profiles, migration and settings priority
Two explicit versions: `legacy_v1` reflecting `config/risk.yaml`, and `conservative_v4_candidate` for NEW desired defaults. DO NOT edit `config/risk.yaml` in documentation-only stage, auto-migrate existing settings, or activate candidate in live/demo execution. Audit and seek owner approval to change operational values. Do not mistake full-auto enabled config flags for broker authorization.
Hard broker/account/legal restrictions > vetted risk ceilings > strategy > symbol > per-position preferences; overrides only tighten by default and must be authorized/versioned. Config values must have source, effective timestamp, schema and rollback.

## 5. Code ownership (reuse, do not duplicate)
`services/market_data/`: real data and spec.
`services/strategy_engine/`: generate and confirm signals, one state owner.
`services/risk_engine/engine.py`, `planner.py`, `manager.py`: risk veto, initial sizing, existing protection policy.
`services/execution_gateway/`: sole entry and modification gateway, locks and reconciliation.
`services/bridge/`, `bridge/No7BridgeEA.mq5`, `integrations/brokers/`: MT5 broker transport/spec/confirm.
`services/api_gateway/`: auth, read-only preview, authorized actions; schema and audit.
`apps/web-dashboard/`: Vue chart, Protection view, Calculator/learn.
`packages/persistence/`: reuse SQLite model, migration separately.
`tests/`: deterministic regression and fault simulations.

## 6. Unified development workflow
Step 0: read safety docs, inspect git status/branch, compare current code/config/tests/API; record exact paths and a gap table (EXISTS / PARTIAL / MISSING / UNVERIFIED).
Step 1: load Task Register; claim one task with owner, baseline commit, acceptance test and dependencies. If DONE with evidence, NEVER reimplement. Check overlapping functions first.
Step 2: create focused branch; implement smallest compatible change behind OFF-by-default flags, preserve working services.
Step 3: tests (unit -> integration -> replay/fault -> authorized Demo), update docs README/API/MATH/RUNBOOK/LIMITATIONS and Task Register in same PR.
Step 4: PR with exact changed paths, behavior delta, test command/output, not-tested caveats, config migration, rollback; no direct merge or deployment.
Step 5: move to next task only when prior acceptance is evidenced. Unresolved decisions remain BLOCKED and are not replaced by AI guesses.
No destructive changes, credentials, account toggles, Algo Trading activation, production deployment or live orders without explicit separate operator approval.

## 7. Priority sequence
P0 safety/current behavior and broker bridge gap audit;
P1 candidate risk profile and deterministic calculation tests (no activation);
P2 confirmation 100-point signal state and duplicate guards;
P3 broker-aware SL/TP, execution protection and safe modify/reconciliation;
P4 BE/trailing modes and proof of no double modify;
P5 Calculator and unified dashboard UI;
P6 Paper then explicit Demo validation and performance comparison;
P7 candidate profile migration only by approved review.

## 8. Acceptance checklist
- No duplicate module/service/database or conflicting execution leader.
- 100 points is `100 * symbol.point` and never conflated with $100; side-aware Bid/Ask.
- All new entries pass one RiskEngine; broker-proven SL/TP; manual and AI cannot bypass.
- R is immutable from original fill/SL; BE cost and THB are estimated correctly and labeled.
- At most one modify command per position per cycle; no stop widening; exact broker SL reconciliation; loss-of-ack recovery.
- No live trading; simulated/reconstructed data prominently labeled.
- UI stable and calculator read-only.
- A/B backtest with actual tick when available, failure test evidence; no unsupported profitability claim.
- All legacy docs remain as history with redirect; each runtime change updates applicable current technical documentation.
