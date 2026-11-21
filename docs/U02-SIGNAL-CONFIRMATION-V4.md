# U02 — 100-point signal confirmation (candidate)

## Scope and current state

U02 is **PARTIAL / NOT ACCEPTED**. The new gate is wired into the existing
`TradingRuntime._decide_symbol` path and executes only when
`strategy_cfg.signal_confirmation_v4.enabled` is exactly `true`. The checked-in
candidate profile is stored separately at
`config/candidates/signal_confirmation_v4.yaml` and is not loaded by runtime
settings. Therefore the current runtime remains unchanged and the feature is
off by default.

The gate does not call the execution gateway or authorize an order. A candidate
must still pass the existing Risk Engine gate and the existing order approval
path. It uses the declared broker `point`, broker health, data-quality status,
the latest closed M1 candle, and the existing M5 trend reading.

## Candidate interpretation

Because the V4 task register does not specify the exact measurement anchor, this
candidate measures favorable movement from the first quote observed when a
signal setup starts. A closed M1 close must move at least 100 broker points in
the signal direction, the M5 trend must agree, and the execution-side quote may
not be more than 30 broker points from that confirming close. Candidate expiry
is 300 seconds; a closed M1 candle older than 75 seconds blocks confirmation.
These parameters and semantics require product/Demo acceptance before runtime
enablement. The 1e-9 arithmetic tolerance only handles float representation at
the exact boundary; it is not a market-price tolerance.

## Persistence and safety

The existing SQLite `kv` store holds one candidate per workspace, broker and
symbol. `BEGIN IMMEDIATE` serializes competing workers, candidate IDs are stable
across restarts, and expired/rejected candidates cannot silently release again.
The gate creates no order rows. No schema migration is needed. Existing
`ExecutionGateway`, Risk Engine and broker adapter remain the only order path.

## Evidence

- Unit tests: `tests/test_signal_confirmation_v4.py` covers BUY/SELL thresholds,
  M5 alignment, chase, stale evidence, expiry, restart, concurrent writers,
  invalidation and absence of order rows.
- Runtime integration uses the current signal cycle; no live broker snapshot or
  runtime opt-in test has been performed.
- Paper replay and Demo acceptance: **NOT TESTED**.
- Live trading: **NOT ENABLED / NOT TESTED**.

## Acceptance blockers / rollback

U01 still requires a post-change EA snapshot and DST/offset validation. Before
accepting U02, verify the point semantics and confirmation anchor against the
broker's actual symbol metadata, then run Paper replay and an explicitly
approved Demo test. Rollback is to leave the candidate profile unloaded and
`signal_confirmation_v4` absent/disabled; no database migration or broker-side
state needs reversal.
