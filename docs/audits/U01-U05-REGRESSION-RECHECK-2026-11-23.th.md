# U01–U05 Local Regression and Staging Recheck

Date: 2026-11-23
Base: `plan/unified-development-v4` at `004d17950d3ccfb3e97d60d3d79d5449a69416ab`
Scope: source/tests plus read-only VM100 staging health and source inspection. No deployment, runtime configuration, account change, broker command, or trade.

## Results

| Task | Local result | Acceptance still missing |
|---|---|---|
| U01 Market data | PASS: publisher and market-snapshot tests included in the aggregate regression | BLOCKED: staging health is stale and the staging checkout does not expose `/api/market/publish/mt5`; no fresh Demo quote, rate/spec comparison, MetaEditor compile, or stale/reconnect receipt |
| U02 Signal confirmation | PASS: focused confirmation, readiness, signal-execution and continuation tests | PARTIAL: candidate remains off; U01 fresh quote, Paper runtime cycle, and separately authorized Demo acceptance are NOT TESTED |
| U03 Risk profile | PASS: existing inert candidate/profile-isolation tests; task remains DONE | No migration or profile activation was attempted; legacy runtime profile remains active |
| U04 Initial SL/TP | PASS: planner and fake-terminal broker-preflight tests | NOT TESTED against actual broker `order_check`, margin, fill/SL/TP readback, or Demo |
| U05 Execution/modify | PASS: durable intent and execution/account/bridge regression tests | BLOCKED: no staging parity/restart/recovery or backup/restore evidence; no Demo modify/readback receipt |

## Test evidence

The sequential command covered these 18 focused files:

```text
tests/test_mt5_market_publisher_script.py
tests/test_mt5_market_publisher.py
tests/test_market_snapshot.py
tests/test_signal_confirmation_v4.py
tests/test_readiness.py
tests/test_signal_execution.py
tests/test_smart_entry_continuation.py
tests/test_risk_profile_candidate.py
tests/test_invariants.py
tests/test_risk_engine.py
tests/test_mt5_order_preflight.py
tests/test_mt5_account_continuity.py
tests/test_v4_plan_candidate.py
tests/test_execution_recovery.py
tests/test_position_modify_intents.py
tests/test_account_ownership.py
tests/test_bridge_readonly.py
tests/test_atomic_execution_claim.py
```

Result: **350 passed**, one pre-existing Starlette/httpx deprecation warning. The initial run with the machine's system interpreter could not collect because required packages were absent. Dependencies were installed from `requirements-dev.txt` into this isolated worktree's ignored `.venv`; rerun passed.

Ruff `--select E9,F` on the same focused Python files: **PASS**. A broader `I` import-format scan reported 10 pre-existing `I001` findings in untouched tests; no auto-fix was applied because this recheck changes documentation only. `git diff --check`: **PASS**.

## Read-only VM100 observations

- The SSH tunnel to `127.0.0.1:18181` was started only for read-only inspection and closed afterward.
- `GET /api/system/health` returned `status=ok`, `feed_mode=mt5_demo_publisher_stale`.
- `GET /openapi.json` did not list `/api/market/publish/mt5`; `git grep` on staging HEAD likewise found no route implementation.
- Staging HEAD is `06642a06bbf9b8623a75c2a4ae715279abc92e08`, branch `feature/u02-100pt-confirmation`. `git status --short` reports untracked `.env.save`; its contents were not read or modified.
- The isolated worktree has no `.env`; publisher process environment variables are absent. No secret values were queried or printed.

## Safety and next gate

No market snapshot was posted. No staging file, database, checkout, service, or port 8000 was modified. No order or position modification was sent.

Before U01 can pass, prepare the correct U01 API in the isolated staging environment without overwriting the dirty checkout, verify the route and rollback path, then configure the read-only PC publisher and capture a fresh, identity-matched Demo quote with matching broker symbol specification. U05 remains blocked until durable intent parity and restart/reconciliation are verified on staging, followed by separately authorized Demo modify/readback acceptance. U02 and U04 must not advance to broker acceptance while U01 is blocked. Live remains disabled.
