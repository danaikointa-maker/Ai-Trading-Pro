# No7 AI Trading Pro — UNIFIED MASTER PLAN V4
Status: PROPOSED DOCUMENTATION BRANCH ONLY; NO RUNTIME DEPLOYMENT; NO LIVE AUTHORIZATION.
Updated: 2026-11-22. Owner-approved acceptance and testing are required before replacing active defaults.

## 0. Purpose and canonical policy
This document is the SINGLE canonical feature-scope and implementation-plan reference for the next development iteration. Existing code and configuration are authoritative for AS-IS behavior, not statements of desired V4 behavior. Security constraints in `docs/blueprint-v3/AGENTS.md` and tested invariants OVERRIDE a feature request; this document cannot relax them. `docs/UNIFIED-TASK-REGISTER-V4.md` tracks execution state; `docs/UNIFIED-CONFLICTS-V4.md` tracks discrepancies. Earlier development prompts and `docs/POSITION-PROTECTION-INTEGRATED-V1.1.md` are historical inputs and MUST NOT be executed as independent backlogs. No prompt may override tests, verified broker behavior or account-specific risk gates.

Use one repository `danaikointa-maker/Ai-Trading-Pro`; one authoritative trading core and execution leader. DEV PC `C:\workspace\Ai-Trading-Pro` owns source work and is the current Windows MT5 Demo/EA host. The Windows AI Trading Pro runtime owns the selected broker session, trading StrategyEngine, RiskEngine, ExecutionGateway, position manager and final order reconciliation. VM100 is the separate AI Development/QA/Creative Office API/control plane, with project/task/event/video metadata and permitted advisory services; it has no broker credentials or trading command authority. The Windows trader connects outbound to VM100 over authenticated HTTPS/WebSocket and may publish only specifically allowed, freshness/provenance-tagged data. VM200 is not an active host unless reauthorized. This is the requested target split; audit and migration evidence are still required before moving runtime components. No Laravel rewrite, shared database, duplicate RiskEngine/PositionManager, second execution leader or alternate order route.

### Parallel Windows + VM100 development and staging contract
The implementation/handoff details live in `vm100/README.md`; this is an operational companion to this plan, not a second feature queue. Keep one GitHub repository and use separate local checkouts/branches/PRs for simultaneous work. Share source through Git review and runtime data through versioned REST/WebSocket contracts; never sync working directories or share SQLite files over the network. Windows owns source editing, local automated validation, the installed MT5 Demo terminal and its data-only publisher. VM100 owns isolated API/UI staging, its own SQLite/state, analytics/inference/training jobs and service logs. Shared contracts and ownership boundaries are reviewed in PRs before either runtime consumes them. Avoid simultaneous edits to the same files; task IDs remain governed solely by the Unified Task Register.

Cloudflare hostname target: `agent.youridea168.com`. The intended published route is HTTPS through Cloudflare Tunnel to a loopback-only VM100 staging origin (currently expected to be `http://127.0.0.1:18081`, subject to on-host verification). It must not route to the simulated/development port 8000, expose a direct host port, or expose an MT5 command/order bridge. Apply Cloudflare Access plus application authentication and scoped service credentials as appropriate. Tunnel installation, active tunnel, DNS record, Access policy, hostname certificate, local origin and WebSocket behavior have NOT been independently verified; do not call the domain ready or change the active route until the handoff preflight and security gates pass. The hostname is a target, not evidence of live DNS/Tunnel configuration.

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
W4 ExecutionGateway: one authorized intent/idempotency path on the Windows Trader runtime, broker order and SL/TP validation, fill reconciliation; Windows-to-VM100 connection is outbound and advisory/data-scoped only, with no remote order command route; Demo only with explicit permission. Any uncertainty => fail closed for new entries.
W5 Position protection BE/trailing/partials: EXTEND `services/risk_engine/manager.py`; candidate policies feed ONE gateway modifier. New candidate policy BE at +1.0 initial R, cost-aware estimated BE; trailing after broker-confirmed BE at +1.5 initial R, 1.0x ATR distance, 0.2x ATR step, max 6/min/position (subject broker), never worsen SL nor remove TP, reconcile after restart. Four UI management modes Manual/Semi/Full/Hybrid are distinct from entry mode and cannot bypass safety. Candidate profile defaults modification AUTO OFF pending Demo validation. Legacy partial 40/30/30 retained as legacy preset; new proposed single 2R TP with partial OFF. Initial R at fill immutable.
W6 Trading Calculator & Learning Center: ONE shared calculation core with risk/planner; 16 tools, read-only/manual what-if, data sources LIVE_MT5/RISK_PROFILE/AI_SIGNAL/MANUAL, provenance and timezone, lot/PnL/BE/ATR/FX in account currency. Calculator UI never invokes trade/modify endpoint.
W7 Professional Vue Dashboard & notifications: current market feed freshness, signal progress, proposed vs confirmed SL, short-range chart markers, unchanged viewport and zoom, bilingual beginner explanations. Notifications idempotent and must not initiate order retries.
W8 Backtesting, demo acceptance, release management and rollback; A/B tests 100-point confirmation, BE/trailing vs no protection, actual tick spreads, drawdown/net PnL, outages, rate limits, account separation. Automated tests do NOT equal live or broker acceptance.
W9 Trading Officer Team is the trading UI/analysis role layer inside the Windows AI Trading Pro workstation. In Manual and Semi-Auto it advises and notifies; the user owns the final trade decision (Semi-Auto requires explicit confirmation). In Auto mode it may initiate only allowlisted, preconfigured rule-based entries through the existing StrategyEngine → confirmation/freshness checks → RiskEngine → ExecutionGateway → Windows MT5 adapter/EA path. Officer personas, LLMs, TradingView packets and webhooks never send broker commands or bypass that chain. Auto defaults OFF, is enabled explicitly and audited per authorized account, and remains unavailable for Live until a separate validated authorization. Do not create another signal/risk/execution engine.
W10 TradingView Intelligence is an isolated, read-only evidence source. Reuse the existing API gateway, shared schemas, market/strategy pipeline, RiskEngine, ExecutionGateway and dashboard. Do not add another signal, risk, market-data or MT5 execution engine. TradingView evidence never overwrites MT5 prices/specifications and cannot authorize an order. Its score, risk map, LLM output and webhook payload are advisory only. Full Auto remains OFF by default and any execution candidate must pass the existing confirmation, freshness, RiskEngine and ExecutionGateway checks using a newly verified MT5 quote and broker specification.

### W9 entry modes and execution boundary
- **Manual:** officers analyze, explain, notify and draft the plan; only the user submits the trade through the existing UI/gateway.
- **Semi-Auto:** the system can propose a rule-matched trade with entry/SL/TP/size/reason, but a user must explicitly confirm that individual entry.
- **Auto:** may submit rule-matched entries without per-order confirmation only while the user has explicitly enabled Auto for that account and the existing safety gates pass. Rule/profile edits, broker/account changes and increases to risk remain separately authorized actions; Auto cannot enable itself.
- Strategy rules are versioned/allowlisted and deterministic at execution time. LLM/Officer outputs may explain a candidate but cannot create or alter executable rules, approve a RiskEngine veto, retry an uncertain order, or issue MT5 calls.
- Require current verified MT5 quote/specs, account identity, allowed symbol/session, idempotent intent, configured risk limits, valid SL/TP/volume/margin, broker `order_check`, and post-fill reconciliation. Any stale/disconnected/ambiguous/failing state blocks new entries and requires reconciliation. Preserve account isolation and audit who enabled Auto, which rule/version acted, and the full decision/fill evidence.
- Auto is OFF by default; start with Paper, then separately authorized Connext Demo. Live stays disabled absent its own authorization and acceptance. The Windows MT5 host must remain online and connected for this execution model; VM100 is not an alternate order route.

### W10 TradingView Intelligence — planned integration
- Adapter boundary: receive the third-party `ai-agent-lens/v1` packet through the existing FastAPI application; validate into a versioned shared `ExternalAnalysisEvidence` contract and keep the source identity, original symbol, mapped No7 symbol, timeframe, closed-bar UTC time, ingest time, event/hash and quality/freshness result. Do not treat packet fields as instructions.
- Existing analytics remain authoritative: compare TradingView multi-timeframe, structure and feature scores with `AnalysisService` / `StrategyEngine`; never replace or blend scores into No7's canonical score until a separately reviewed experiment proves the method. No7's RiskEngine alone creates/approves the executable plan.
- Ingress security: strict schema and size limits, scoped rotating credential, TLS/network controls, rate limiting, replay/deduplication, audit, query/credential redaction and bounded retention. Do not deploy the sample receiver as a production endpoint. Fail closed on malformed, stale, future, duplicate or unmapped packets.
- Modes/UI: Manual and Semi-Auto may display attributed advisory evidence. Auto remains disabled by default; TradingView or LLM output cannot toggle it or call execution. Display provider, symbol mapping, timeframe, close time, freshness, score source and disagreement without implying a No7-approved signal.
- Validation gates: Pine source review and compiler/Bar Replay tests for closed bars, HTF lookahead and delayed pivots; packet contract/security/failure tests; shadow-only comparison; point-in-time backtest with realistic spread/fees/slippage and no look-ahead; performance/load measurement; only then separately authorized Paper and Demo acceptance. No Live authorization is included.
- License: repository declares MIT. If source or substantial code is copied, preserve its copyright and license notice and record the reviewed upstream revision. Prefer schema mapping and independent implementation over copying Pine code.

### W10 delivery plan — five sequential phases (U14–U18 are the only task queue)

| Phase | Task ID | Scope and exit evidence | Current state / next gate |
|---|---|---|---|
| 1. Contract and source audit | U14 | Freeze the shared packet/evidence contract; audit overlap, license, Pine closed-bar/HTF/pivot behavior; pass contract, normalization and upstream sample-corpus tests. | Local contract tests and pinned upstream sample fixture PASS at `f1aa6ce185f943f1e825f638c10b1201ef0e1e0a`. GitHub identifies the upstream repo as public/MIT/Pine v6; retain independent implementation. Pine compilation and Bar Replay remain NOT TESTED. |
| 2. Secure ingress and persistence | U15 | Keep adapter OFF by default; enforce body/schema/credential/symbol-map/rate/retention controls; verify redaction, credential rotation, TLS/proxy limits and deployed storage behavior. | Local ingress, persistence, auth, bounds, rate-limit and credential-rotation regression PASS. TLS/proxy log redaction, actual secret-manager rotation, multi-worker rate-limit sharing and staging threat-model review remain NOT TESTED. |
| 3. Shadow comparison and research validation | U16 | Compare only exact symbol/timeframe/closed-bar matches; maintain external score separation; add deterministic point-in-time replay, no-lookahead, realistic spread/fees/slippage and discrepancy metrics. | Exact match now scans same-symbol/bar candidates and canonicalizes timeframe; stale, mismatched-timeframe, malformed-row and out-of-order tests PASS. Historical Lens replay, statistical report and cost-aware backtest remain NOT TESTED. |
| 4. Dashboard visualization and access review | U17 | Show source, mapping, timeframe, explicit UTC close time, freshness and separate scores; validate role access, responsive layout, stale/error states and no chart/order side effects. | Vue build PASS; close time now labels UTC. Browser screenshot, role matrix and responsive acceptance remain NOT TESTED. |
| 5. Release and rollback gate | U18 | Re-run the complete regression; record Pine/alert reconciliation, performance/load and rollback evidence; Paper first. Demo only after separate explicit authorization and only with Auto/Live OFF. | Local 73-test regression PASS, dashboard build PASS. Rollback steps are documented, but drill is NOT TESTED. External TradingView/Paper/approved-Demo receipts remain NOT TESTED; do not stage/deploy or enable decision influence before these gates. |

Phases advance in order; a phase with a missing exit receipt stays BLOCKED and downstream work is limited to independent local checks. The Task Register records detailed evidence. This table is the execution view of U14–U18, not a second backlog or authorization to trade/deploy.

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
P8 TradingView Intelligence: U14 audit/contract, U15 secure adapter, U16 shadow comparison and validation, U17 visualization, U18 Paper/Demo acceptance. This workstream is additive and must not delay or weaken existing W1–W5 safety gates.

## 8. Acceptance checklist
- No duplicate module/service/database or conflicting execution leader.
- 100 points is `100 * symbol.point` and never conflated with $100; side-aware Bid/Ask.
- All new entries pass one RiskEngine; broker-proven SL/TP; manual and AI cannot bypass.
- R is immutable from original fill/SL; BE cost and THB are estimated correctly and labeled.
- At most one modify command per position per cycle; no stop widening; exact broker SL reconciliation; loss-of-ack recovery.
- No live trading; simulated/reconstructed data prominently labeled.
- UI stable and calculator read-only.
- A/B backtest with actual tick when available, failure test evidence; no unsupported profitability claim.
- TradingView packets are source-scoped, closed-bar, validated and never authoritative for execution price, risk approval or order authorization; webhook/LLM paths cannot bypass the existing gate.
- TradingView repaint/lookahead behavior, packet quality, security, realistic backtest and performance have evidence before enabling any decision influence; default integration is shadow/advisory and Auto stays OFF.
- All legacy docs remain as history with redirect; each runtime change updates applicable current technical documentation.
