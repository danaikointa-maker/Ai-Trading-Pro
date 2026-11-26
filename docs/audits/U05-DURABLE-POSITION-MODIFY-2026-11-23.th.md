# U05 Audit — Durable Position Modification

วันที่: 2026-11-23  
Planning source: Unified Master Plan V4 / Unified Task Register V4  
Candidate branch: `feature/u05-durable-position-modify`  
Scope: preserve the already deployed durable position-modify behavior in V4; no staging or broker mutation.

## Stage inventory (read-only)

Inspected VM100 staging repository `/home/danai/no7-ai-trading-pro-v4-staging`:

- Branch/commit: `feature/u02-100pt-confirmation` / `06642a0`.
- SQLite file: `storage/db/no7-v4-staging.sqlite3`, opened read-only.
- `position_modify_intents` exists with account fingerprint, ticket, idempotency key, request hash/payload, state, and timestamps.
- The partial unique index `idx_position_modify_one_unresolved` permits only one unresolved intent per broker/account/ticket; the inspected table had 0 rows.
- No staging service, database, or broker state was changed. A filename `.env.save` appeared in staging status; its contents were not read.

## Gap and implementation

Before this change, V4's `ExecutionGateway.modify` called the adapter and wrote an event, but did not reserve a durable intent or reconcile it after an ambiguous response. That meant the gateway could not fence a retry after a process interruption even though the staging database already held the ledger.

The V4 candidate reuses the existing SQLite and `PositionEventLog` ownership boundaries. It adds the ledger as an additive `CREATE TABLE IF NOT EXISTS` schema change, keeps transitions in append-only `position_events`, enforces a unique unresolved intent for each account/ticket, and integrates reserve/send/readback/reconciliation into the existing gateway. Preflight rejects non-Demo accounts, read-only bridge sessions, unhealthy sessions, stale quotes, missing broker constraints, invalid stops, and account identity changes. A broker acknowledgement alone does not confirm the stop; confirmation requires matching broker readback. Ambiguous outcomes remain fenced until reconciliation. No second execution engine or database was added.

An existing account-switch regression test lacked the complete Demo snapshot now required by the modify preflight. Its fixture was completed so it exercises the post-broker-I/O account-switch guard without loosening production checks.

## Verification

| Check | Result | Evidence |
|---|---|---|
| Durable intent focused tests | PASS | `pytest -q tests/test_position_modify_intents.py` — 22 passed |
| Execution/account/position regression | PASS | Combined command covering `test_position_modify_intents.py`, `test_execution_recovery.py`, `test_atomic_execution_claim.py`, `test_account_ownership.py`, `test_runtime_position_ownership.py`, `test_position_snapshot_atomic.py`, and `test_smart_entry_continuation.py` — 234 passed |
| CI lint scope | PASS | `ruff check --select F,E9 .` — all checks passed |
| Whitespace validation | PASS | `git -c core.whitespace=cr-at-eol diff --check` |
| First GitHub CI attempt | FAIL, corrected | 1,556 passed, 7 skipped; `test_management_revision_records_request_before_broker_io` used an incomplete mock. Its fixture now supplies Demo identity, broker position/spec/quote, and confirms the durable state sequence through readback. |
| GitHub CI after fixture correction | PASS | Commit `a119382`: 1,557 passed, 7 skipped; separate real-Redis verification: 20 passed. Ruff safety/syntax scope and dashboard build passed. |
| Windows full-repository suite | ENVIRONMENT-LIMITED | 1,506 passed, 37 skipped; 3 UI failures because this isolated worktree has no built dashboard/`node_modules`, and 18 Redis setup errors because its detected local server rejects `HELLO`. The targeted U05 regression set passed; GitHub CI builds the dashboard and prepares Redis before running the full suite. |
| Staging parity after candidate rollout | NOT TESTED | Candidate was not deployed or restarted on VM100 |
| Backup/restore or rollback drill | NOT TESTED | No stage data was modified |
| Connext-Demo broker modify and readback receipt | NOT TESTED | No broker command was sent |
| Live modification | NOT TESTED / DISABLED | No Live command or activation |

## Safety and rollback

The schema addition does not drop or rewrite the existing staging ledger. A rollback must restore the prior application artifact while preserving the SQLite database and `position_modify_intents` rows; do not drop the table. Before any staging replacement, verify a restorable database backup and retain the current `06642a0` artifact. No staging replacement/restart or broker test is included in this change.

## U05 status and remaining gates

U05 remains **PARTIAL / BLOCKED**. The implementation, 234 focused regressions, and GitHub CI are complete. Two acceptance work items remain:

1. An isolated VM100 staging parity/restart/concurrency/reconciliation check, with a verified backup and rollback path, without touching port 8000.
2. An authorized Connext-Demo position-modify response plus broker readback/reconciliation receipt. This depends on U01 providing a fresh, verified Demo quote and requires explicit Demo acceptance; Live remains disabled.

## 2026-11-26 VM100 staging recheck (read-only)

- SSH inspection reconfirmed staging checkout `/home/danai/no7-ai-trading-pro-v4-staging` at `feature/u02-100pt-confirmation` / `06642a0`. Its working tree still has modifications to `docs/API.md`, `docs/RUNBOOK.md`, `scripts/check_mt5_market_runtime.py`, and `tests/test_mt5_runtime_preflight.py`, plus untracked `.env.save`. Only status names were read; `.env.save` and environment files were not opened or changed.
- Read-only SQLite `mode=ro` inspection of `storage/db/no7-v4-staging.sqlite3`: `PRAGMA quick_check=ok`, `position_modify_intents` has **0 rows**. `request_payload` exists, but `position_lifetime_fingerprint` is absent. The unresolved-intent partial unique index still covers `(broker_id, account_fingerprint, ticket)`; the V4 candidate expects the additional `position_lifetime_fingerprint`. No ticket, account fingerprint, payload, or row values were read.
- VM100 `127.0.0.1:18082` health returned `status=ok`, `feed_mode=simulate`; OpenAPI lists `POST /api/market/publish/mt5`. `ss` shows the listener bound to `127.0.0.1`; its Python process was in a user-session cgroup, so systemd ownership is not established. No POST, DB migration, service restart, or process change was attempted.
- The development PC had no MT5 terminal process and its application ports were closed. This does not provide a fresh Demo quote or broker receipt.

This recheck confirms a schema/index parity gap; it does not prove the database can be safely migrated or that broker positions match the empty intent ledger. U05 remains **PARTIAL / BLOCKED** pending a verified backup/rollback path, reviewed staging migration/restart/reconciliation, and separately authorized Connext-Demo modify/readback after U01 freshness acceptance.
