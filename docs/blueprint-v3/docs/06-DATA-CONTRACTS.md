# Contract-first integration & order state

## Common API conventions
- Version prefix `/api/v1` for **new endpoints**; retain existing `/api/*` via compatibility adapters, never break dashboard abruptly.
- OpenAPI with generated Pydantic schemas/types, strict validation and contract tests; JSON fields snake_case, UTF-8; IDs UUIDv7/UUID4 and stable correlation IDs; documented semantic versions.
- Timestamp: ISO8601 UTC, exchange timestamp + receive timestamp + latency; client-display timezone independently.
- Money Decimal / exact currency, quantity Decimal, points numeric with **broker-provided symbol info**; do not conflate net P/L with price points.
- Every record includes `tenant_id`, `account_id` when applicable, `symbol`, `broker`, `event_id`, `correlation_id`, `schema_version`, `ingest_ts`.

## Messages / transport
- Windows -> Ubuntu: authenticated HTTPS outbound (private network/VPN), with per-account scoped short-rotation credentials/mTLS; batching, backpressure, dedup, acknowledgements; tolerate short outages with bounded local spool.
- Ubuntu -> Windows: Windows makes outbound authenticated poll/long poll for **approved DEMO order intents**, never open unauthenticated order listener on Windows. Separate market data and command credentials.
- Candidate endpoints (adapt existing bridge instead of rebuilding): `/api/v1/bridge/heartbeat`, `/api/v1/market/batch`, `/api/v1/execution/approved`, `/api/v1/execution/receipts`, `/api/v1/execution/reconcile`.
- Retry backoff with jitter; stale/expired commands discarded; persist state and idempotency keys. `HTTP 200` never equals broker fill.

## Order state machine
`CREATED -> RISK_REJECTED | APPROVED -> CLAIMED -> SENT -> ACKNOWLEDGED -> PARTIALLY_FILLED | FILLED | REJECTED | UNKNOWN -> RECONCILED`.
- Maintain append-only order event ledger and a current projection; dedupe by `(account_id, intent_id)`, unique broker ticket/deal as available.
- UNKNOWN **blocks new orders** on that account until reconciliation with MT5 orders, deals, positions and appropriate broker history.
- No blind resend after network timeout. Exactly-once broker execution cannot be promised; achieve at-most-once intent dispatch where feasible and reconcile externally.
- Windows side Execution Guard independently rechecks account type demo, order age, symbol, trading sessions, volume/step, margin, SL/TP, max spread/slippage, duplicate, kill switch.
- Kill switch = prevent new risk, not blindly close positions; risk-reducing close requires explicit documented exception path.
- One active executor/terminal owner per account with lease fencing and restart recovery; no concurrent EA + Python order send for same account without arbitration.

## Market data quality
- Dedup ticks, monotonic time checks, late events, stale feeds, missing bars, symbol suffix/digits, quote status, outlier flags, session metadata; health-status `LIVE`, `SIMULATED`, `REPLAY`, `STALE`, `DISCONNECTED` visible in UI.
- Record dataset manifest + checksum + broker provenance + corporate actions for stocks where applicable; never blend paper/simulated/real records silently.
