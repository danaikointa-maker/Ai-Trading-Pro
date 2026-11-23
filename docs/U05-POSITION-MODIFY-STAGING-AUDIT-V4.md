# U05 — Position Modify Staging Parity Audit

Audit date: 2026-11-23  
Scope: read-only source, SQLite schema/counts, and staging health inspection. No
staging files, database rows, processes, accounts, or broker state were changed.

## Findings

| Check | Evidence | Result |
|---|---|---|
| VM100 staging checkout | `/home/danai/no7-ai-trading-pro-v4-staging`, branch `feature/u02-100pt-confirmation`, HEAD `06642a0`, one commit behind its origin; working tree has an untracked `.env.save` that was not opened | Existing stage is separate and dirty; do not replace it wholesale |
| Position intent implementation | `packages/persistence/position_events.py` defines reservation, transition, reconciliation, and confirmed-readback helpers; `tests/test_position_modify_intents.py` includes reopen, concurrent writer, account isolation, unknown state, stale reservation, restart, and exact readback cases | Useful behavior exists in staging and is absent from the V4 application source |
| Stage SQLite location | `storage/db/no7-v4-staging.sqlite3` | Identified without reading row payloads |
| Read-only DB check | Opened with SQLite `mode=ro`; `PRAGMA quick_check` returned `ok`; `position_modify_intents` has composite primary key `(broker_id, account_fingerprint, ticket, idempotency_key)` and partial unique index `idx_position_modify_one_unresolved`; aggregate row count `0`, no state groups | Schema is present and valid; no intent rows existed at audit time |
| V4 parity | `git grep` on `origin/plan/unified-development-v4` found no application-code reference to `position_modify_intents` (only earlier audit documentation) | V4 gateway cannot fence or reconcile the stage ledger today |
| Staging service/feed | GET `127.0.0.1:18081/api/system/health` returned `status=ok`, `feed_mode=mt5_demo_publisher_stale`, `fresh=false`, quote age about `164,222s`; queried systemd unit reports `inactive`, while the HTTP endpoint still responds | Listener ownership was not established; no restart or process change attempted |

The database query returned only schema, integrity, row count, and state counts;
no ticket, account fingerprint, payload, credential, or position data was read.

## Decision and next work

U05 remains **PARTIAL / BLOCKED**. The empty table does not prove broker state is
empty and does not remove the need for parity: future or uncertain modifications
could become unrecoverable if V4 cannot reserve and reconcile them. Reuse the
existing `PositionEventLog` and one `ExecutionGateway` modification path; port
the durable intent behavior with migration and restart/concurrency/unknown-state
tests before any staging replacement. A separate, explicitly approved Demo
acceptance is still required for broker receipts. The stale feed also prevents
using this staging session for execution acceptance.

## Safety and rollback

- Read-only SSH and SQLite `mode=ro` were used. No environment or saved files
  were read; `.env.save` was left untouched.
- No DB migration, service restart, staging checkout change, order, modify
  request, or deployment was performed.
- This audit changes documentation only. Revert the documentation commit to
  roll it back.

## NOT TESTED

- V4 intent persistence implementation and its automated tests.
- Recovery of any non-empty or ambiguous intent against broker positions.
- Demo broker modification, timeout/readback, VM restart, power-loss recovery,
  listener ownership, backup/restore, and fresh MT5 publisher data.
