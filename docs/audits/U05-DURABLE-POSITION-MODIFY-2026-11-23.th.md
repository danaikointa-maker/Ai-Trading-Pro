# U05 Audit — Durable Position Modification

วันที่: 2026-11-23  
Planning source: Unified Master Plan V4 / Unified Task Register V4  
Candidate branch: `feature/u05-durable-modify-ledger`
Scope: preserve the already deployed durable position-modify behavior in V4; no staging or broker mutation.

## Stage inventory (read-only)

Inspected VM100 staging repository `/home/danai/no7-ai-trading-pro-v4-staging`:

- Branch/commit: `feature/u02-100pt-confirmation` / `06642a0`.
- SQLite file: `storage/db/no7-v4-staging.sqlite3`, opened read-only.
- At the time of the read-only audit, `position_modify_intents` had account fingerprint, ticket, idempotency key, request hash/payload, state, and timestamps.
- The staging partial unique index `idx_position_modify_one_unresolved` permitted one unresolved intent per broker/account/ticket; `PRAGMA quick_check` returned `ok`, and the inspected table had 0 rows. The V4 candidate now scopes new intents by position lifetime and migrates legacy rows to a conservative global fence for that account/ticket.
- No staging service, database, or broker state was changed. A filename `.env.save` appeared in staging status; its contents were not read.

## Gap and implementation

Before this candidate, V4's `ExecutionGateway.modify` called the adapter and wrote an event, but did not reserve a durable intent or reconcile it after an ambiguous response. That meant the gateway could not fence a retry after a process interruption even though the staging database already held the ledger.

The V4 candidate reuses the existing SQLite and `PositionEventLog` ownership boundaries. It adds an additive intent schema/migration, keeps transitions in append-only `position_events`, enforces one unresolved intent per account/ticket/position lifetime, and integrates reserve/send/readback/reconciliation into the existing gateway. Paper adapter epochs distinguish ticket reuse across simulator restarts; legacy unresolved rows without lifetime evidence remain fenced under a sentinel until manual reconciliation. Preflight rejects non-Demo accounts, read-only bridge sessions, unhealthy sessions, stale quotes, missing broker constraints, invalid stops, and account identity changes. A broker acknowledgement alone does not confirm the stop; confirmation requires matching broker readback. Ambiguous outcomes remain fenced until reconciliation. No second execution engine or database was added.

An existing event-order regression test lacked the complete Demo snapshot now required by the modify preflight. Its fixture was completed so it exercises the event-before-I/O contract with broker readback, without loosening production checks. The candidate keeps the existing immutable position-event trail and adds the durable intent projection; ambiguous outcomes stay fenced.

## Verification

| Check | Result | Evidence |
|---|---|---|
| Durable intent focused tests | PASS | `pytest -q tests/test_position_modify_intents.py` — 35 passed |
| Execution/account/position regression | PASS | `pytest tests/test_position_modify_intents.py tests/test_account_ownership.py tests/test_execution_recovery.py tests/test_bridge_readonly.py tests/test_atomic_execution_claim.py tests/test_smart_entry_continuation.py tests/test_signal_execution.py -q` — 156 passed, 1 pre-existing Starlette/httpx deprecation warning |
| Selected Ruff and whitespace checks | PASS | Ruff `--select F,E9` on changed Python files and `git diff --check` |
| Hosted CI | PENDING | Run after the review corrections are pushed |
| Staging parity after candidate rollout | NOT TESTED | Candidate was not deployed or restarted on VM100 |
| Backup/restore or rollback drill | NOT TESTED | No stage data was modified |
| Connext-Demo broker modify and readback receipt | NOT TESTED | No broker command was sent |
| Live modification | NOT TESTED / DISABLED | No Live command or activation |

## Safety and rollback

The schema addition does not drop or rewrite the existing staging ledger. A rollback must restore the prior application artifact while preserving the SQLite database and `position_modify_intents` rows; do not drop the table. Before any staging replacement, verify a restorable database backup and retain the current `06642a0` artifact. No staging replacement/restart or broker test is included in this change.

## U05 status and remaining gates

U05 remains **PARTIAL / BLOCKED**. Local candidate implementation and automated regressions pass, but two acceptance work items remain:

1. An isolated VM100 staging parity/restart/concurrency/reconciliation check, with a verified backup and rollback path, without touching port 8000.
2. An authorized Connext-Demo position-modify response plus broker readback/reconciliation receipt. This depends on U01 providing a fresh, verified Demo quote and requires explicit Demo acceptance; Live remains disabled.

## PR review corrections

- Reconciliation follows the ordered confirmed SL transition chain from the
  stored position baseline in both `reconcile()` and the read-only position
  snapshot path, skipping reservations abandoned before broker I/O. Tests cover
  two confirmed stop improvements both with and without an abandoned reservation.
- Repeating the current SL while requesting a different TP now fails closed;
  explicit TP values must be finite, positive, and aligned to broker tick size.
- Non-abandoned unresolved intents continue to stop attribution across ambiguous
  broker state.
- Intent idempotency and unresolved fencing now include a position-lifetime
  fingerprint. Paper adapters carry a fresh epoch so a reused ticket after a
  simulator restart is a distinct position; tests cover old `confirmed` and
  `unknown` intents. The additive SQLite migration assigns existing rows a
  `legacy-unscoped` sentinel, keeping legacy unresolved intents conservatively
  fenced instead of guessing their lifetime.
- Paper quote freshness uses the adapter's injected virtual clock; real broker
  adapters continue to use wall-clock freshness. The checks retain stale and
  future quote rejection in both modes.
- The hosted run exposed a dev-test dependency drift: the same `fakeredis 2.40.0`
  passed with `redis 8.1.0` but failed during test setup with `redis 8.2.0`.
  Development requirements now constrain Redis to the compatible `<8.2` range;
  production requirements remain unchanged.
- Focused intent tests pass **35**; the seven-file execution/account/bridge
  regression passes **156 tests**, with one pre-existing Starlette/httpx
  deprecation warning.
