# U10 — Alert Idempotency Audit

Date: 2026-11-23
Plan: Unified Master Plan V4 / Unified Task Register V4
Branch: `feature/u10-alert-idempotency-v4`

## Gap and change

The repository already reuses one `Notifier`; entry signal alerts have an in-process
cooldown, readiness alerts are transition-based and persisted, and position reads
and SL modifications use existing ownership and intent controls. However,
`TradingRuntime._apply_action` sent a management alert on every manager cycle with
`dedupe_seconds=0`, so a repeated unknown or rejected acknowledgement could flood
the configured alert channel.

Management notifications now use a stable digest over the verified broker/account
identity, ticket, action kind, requested SL/volume, reason, outcome and available
position identity. The notifier suppresses a repeat of that same event for 300
seconds. A different account/action remains a separate event. If account identity
cannot be verified, dedupe is disabled so one account cannot suppress another
account's alert. Gateway command behavior is unchanged.

## Evidence

| Check | Result |
|---|---|
| Same account/action repeat alert is deduplicated; other account stays independent | PASS — `tests/test_notify_channels.py`, `tests/test_runtime_position_ownership.py` |
| Existing unknown position-modify intent does not resend | PASS — `tests/test_position_modify_intents.py::test_gateway_does_not_retry_unknown_modify_intent` |
| Readiness and smart-entry notification regression | PASS — focused suite, 143 passed total |
| Selected Ruff F/E9, `compileall`, `git diff --check` | PASS |
| Full repository pytest on Windows | INCONCLUSIVE for repository-wide acceptance: 1,558 passed, 37 skipped, 3 failed and 18 Redis tests errored in 399 seconds. The Redis test server found on this host rejects RESP3 `HELLO`; the 3 UI failures were due to missing worktree `node_modules`/dashboard `dist` and passed after `npm ci`, Vite build, and an isolated rerun. Hosted CI remains the complete acceptance gate. |
| Dedupe persistence across process restart | NOT TESTED; current event cache is in-memory and bounded by 300 seconds |
| Broker Demo/Live notification and execution receipts | NOT TESTED; no broker action was sent |

U10 remains PARTIAL. Alert deduplication is not execution idempotency. In particular,
the existing full/partial-close gateway path has not been certified against replay
after an ambiguous acknowledgement; it remains a separate execution-gateway gap.

## Safety and rollback

This change only reduces duplicate management notifications and does not authorize,
retry, suppress, or alter an order/position command. No MT5, Paper, Demo or Live
command was issued. Roll back by reverting the U10 commit; no schema migration is
required.
