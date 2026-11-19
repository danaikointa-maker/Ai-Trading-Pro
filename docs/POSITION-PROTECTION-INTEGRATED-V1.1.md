# No7 AI Trading Pro — Integrated Position Protection V1.1
Status: DESIGN / NOT DEPLOYED. This file is a proposed implementation contract; it is not a claim of completed runtime code or demo acceptance.

## Source of truth and scope
Read `docs/blueprint-v3/AGENTS.md`, `README.md`, `docs/LIMITATIONS.md`, `docs/ARCHITECTURE.md`, `docs/RUNBOOK.md`, `config/risk.yaml`, `services/risk_engine/manager.py` and existing tests before touching runtime code. Preserve Vue 3, FastAPI, existing RiskEngine/PositionManager, broker adapters, MT5 bridge, persistence, and existing read-only execution gates.

Integrate four existing planned features:
1. Conservative account Risk Management and independent risk veto
2. Signal confirmation of 100 broker points, closed M1 candle and M5 trend before auto entry
3. Dynamic initial SL/TP from ATR + structure and broker-aware sizing
4. Position Protection: break-even, trailing, partials, safety, calculations, and the beginner Learning Center

## Repository findings and design conflicts
Existing `services/risk_engine/manager.py` emits `PositionAction` objects for BE and trailing and can emit both modifications in one evaluation. `config/risk.yaml` currently enables BE at 250 points, lock 30 points, trailing at 500 points, ATR 1.0, 50-point step, 40/30/30 partials, and `kill_switch.flatten_on_breach: true`. Existing risk limits include 0.5%/trade, 2% daily, 5% weekly, 10% max DD, 1 open trade, 1 per symbol, min RR 1.3. These are CURRENT config values, not automatically replaced. The prior proposed defaults (weekly 4%, DD 8%, min net RR 1.5, 1R BE, 1.5R trailing, no partial) constitute a NEW VERSIONED PROFILE, to be migrated and activated only by operator approval after tests.

## Architectural ownership
- `services/risk_engine/manager.py`: reuse the existing PositionManager as rule/intent producer; refactor into deterministic candidate calculation without duplicating a second live modifier. Preserve legacy behavior under a versioned configuration/feature flag.
- `services/risk_engine/`: risk veto and shared position-protection policy. Use original initial risk-at-fill to compute R; never recompute R from moved SL.
- `services/execution_gateway/`: SINGLE authoritative, durable modification command path, one active modifier per account+position, idempotency, persisted intents, no blind retry, ack plus broker SL/TP snapshot reconciliation.
- `integrations/brokers/` + `bridge/No7BridgeEA.mq5`: broker feature detection, position identification, stop/freeze checks, modify and confirmation; Windows VM200 initiates outbound communication to VM100 per AGENTS.
- `services/api_gateway/`: authenticated preview/read endpoints, controlled apply/pause endpoints, API schemas, audit, version conflicts.
- `apps/web-dashboard/`: Position Protection view and Calculator integration, preserve chart viewport/zoom, short-range markers, show proposed versus broker-confirmed stops.
- `packages/persistence/`: minimum nonduplicative state/event schema, per-position mode and active config version. SQLite currently; no premature PG switch.
- `tests/`: unit, integration, replay, Demo verification evidence.

## Unified lifecycle and priority
The shared pipeline:
signal -> 100-point directional confirmation -> closed M1 + M5 filter -> independent risk check -> initial stop/TP and volume planning -> idempotent order -> broker-fill reconcile -> position protection state machine -> modify intent -> broker confirmed modify -> audit/notify.
Protection must NEVER open a new position or bypass RiskEngine. BE/trailing live only for existing identified positions.

On each eligible tick:
1. Validate symbol metadata, fresh bid/ask, account, position identity and broker stop/freeze levels.
2. Calculate all valid BE, trailing, and manual candidates. Manual overrides still obey broker and hard risk rules.
3. Apply monotonic SL rule: BUY stop may only increase, SELL stop may only decrease; never remove TP or widen stops. Ignore zero/unknown current SL unless independently verified and safely recovered.
4. Select ONE safest valid SL candidate per position per processing cycle. Price-safe normalization to broker tick size.
5. Re-fetch live position and price just before modify, check risk and version, reserve per-position lock, persist unique intent and send at most one command.
6. Distinguish accepted request from broker-confirmed SL; reconcile exact position identifier, ticket, volume, SL and TP.
7. On timeout/unknown outcome, mark UNKNOWN and reconcile before any further command. Never blindly retry.
8. On stale feed/disconnect/power loss, preserve broker-held SL/TP, block unsafe modifications, alert, and reconcile after restart.

## Versioned proposed conservative profile (NOT automatically activated)
- PAPER default; DEMO_AUTO requires explicit account identity authorization. LIVE never auto-enabled.
- Per trade equity risk 0.5%, aggregate open risk 1%, daily loss 2%, weekly loss 4% (proposed vs existing 5%), peak equity DD 8% (proposed vs existing 10%), max consecutive losses 3, 1 XAUUSD position, maximum 5 new trades per day, min net RR 1.5 (proposed vs existing 1.3).
- Initial SL is structurally justified with ATR(14) M5 reference 1.5×ATR and 0.2×ATR swing buffer; compute lot using broker-currency estimated stop P/L and costs; TP target 2R only when opposing zones allow it. Fail closed for invalid minimum lot, stale FX or symbol metadata.
- Signal confirmation: threshold 100 MT5 points, side-aware Bid for BUY / Ask for SELL, closed M1 confirmation + M5 trend, expiry 300s, prohibit chase >30 points; only then DEMO AUTO may execute, subject to independent authorization.
- Proposed BE: threshold +1.0 initial R, offset based on reliable estimated opening/closing costs including commission/swap/slippage; optional additional 0.05 price units per oz is an experiment ONLY and must not be called guaranteed breakeven.
- Proposed trailing: threshold +1.5 initial R, only after broker-confirmed BE if policy says so; ATR(14) M5 closed bars, distance 1.0×ATR, step 0.2×ATR, maximum 6 modifications/min/position subject to broker stricter limits.
- BE and trailing AUTO MODIFY must remain OFF by default until connector and Demo tests pass; MANUAL preview and PAPER simulation may be enabled. Existing `config/risk.yaml` behavior stays unchanged until explicit reviewed migration.
- Single TP at 2R, partial close OFF in the proposed profile; retain legacy 40/30/30 under legacy profile, do not silently delete.
- Propose default `flatten_on_breach: false` in NEW PROFILE only, with separate emergency liquidation policy; legacy runtime must not silently change.

## BE cost formula and correct unit handling
Compute initial R from original ENTRY/FILL and originally approved SL in account currency, saved immutably. Use correct BUY/SELL closing side. Solve for stop that offsets actual paid costs + estimated closing costs (where reliable), using broker profit calculation, actual contract and currency conversion. THB is display conversion only when account currency differs. Estimate is never guaranteed due to gaps, spread, future swap and slippage. Partial close volume changes invalidate naive per-lot assumptions; use accurate realized P/L and remaining exposure. Broker min stop/freeze distance may prevent exact BE; never force invalid modification.

## Modes and authority
MANUAL: preview/apply BE, start/stop trailing; validation before apply.
SEMI_AUTO: notify proposal and require explicit approval, then re-evaluate price and broker state.
FULL_AUTO: only preauthorized DEMO, autonomous conservative modifications with all guards.
HYBRID: automatic protected position management plus manual per-position pause/override, versioned and audited; global emergency pause must not remove broker protection.
Separate order-entry mode and position-protection mode; do not conflate them. The calculator is READ-ONLY/SIMULATION and cannot invoke order/modify endpoints.

## Dashboard and Learning Center integration
Use existing Vue routes/design. Add Position Protection Overview, ticket table, settings hierarchy (global/symbol/strategy/position), broker-versus-proposed SL marker, last confirmation/rejection timestamp, audit and health. Embed a Position Protection calculator as a tab/shared engine in Trading Calculator & Learning Center (existing plan of 16 calculator tools); no second arithmetic library or duplicate route. Explain R, BE, ATR, Bid/Ask, gross/net projected P/L in Thai; show source, unit, freshness, simulation badge. Keep manual what-if inputs isolated from live config.
Effective setting precedence: hard account/broker safety constraints > explicitly approved risk profile limits > strategy profile > symbol profile > per-position user selection. Overrides may only make risk stricter by default. Reject conflict via version check instead of last-write-wins.

## Necessary API semantics (adapt to existing conventions)
GET risk/protection settings with effective source/version.
GET protection positions/health/events.
POST BE/trailing preview (side-effect-free).
POST apply / start / stop / pause / resume with RBAC, CSRF where relevant, idempotency key, expected position version and account scope. No direct browser -> MT5 calls. Ensure operator can distinguish 'submitted', 'accepted', 'broker confirmed', 'unknown', 'rejected'.
State transitions: UNPROTECTED -> INITIAL_PROTECTED -> BE_ELIGIBLE -> BE_PENDING -> BE_CONFIRMED -> TRAILING_ELIGIBLE -> TRAILING_ACTIVE, plus PAUSED / UNKNOWN / CLOSED / ERROR. Never assert BE_CONFIRMED based solely on sending a command.

## Verification gates
- Unit: BUY/SELL, price tick/point distinction, exact rounding, initial R invariant, BE costs, swap, THB, partial closes, ATR, step and 6/min limit, no stop widening, TP retention, manual vs auto conflict.
- Integration: MT5 bridge command/ack/reconcile, hedging ticket vs netting position identifier, broker stop/freeze, unauthorized mutation, stale tick, duplicate messages, lost ack, restart, same account multi-instance fence, unknown fill state, close before modify.
- Backtest/replay: must distinguish synthetic/reconstructed candles from REAL ticks; compare BE hit rates, TP hit rates, net PnL/DD, order-modification burden vs no protection.
- Demo: explicit operator authorization, verified demo identity, compile MQL5 EA, run prolonged forward checks, capture logs/order receipts and independent broker SL snapshots.
- Release: change on branch/PR, documentation and test receipts, no live activation, staged config migration/rollback, no unsupported claims of deployment.

## Acceptance
Every modified stop must be (1) based on fresh broker-identified position, (2) a strict improvement or safe no-op, (3) broker-valid and risk-authorized, (4) at most one command at a time per position, (5) recorded with durable idempotency and (6) confirmed by refreshed broker state. Never weaken original protection. Any unknown state fails closed for new modifications while preserving broker protection.

## Implementation sequence
P0 read/audit existing code and tests, produce gap matrix
P1 extract deterministic candidate policy into existing PositionManager
P2 harden broker modify and reconciliation under one execution leader
P3 implement modes, RBAC, persistence and safe APIs
P4 integrate Calculator/learning UI and stable chart markers
P5 test replay/fault injection and explicitly authorized Demo
P6 review proposed conservative profile migration and activation; never automatic
