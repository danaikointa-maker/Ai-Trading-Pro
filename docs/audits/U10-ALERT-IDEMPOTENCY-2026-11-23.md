# U10 — Alert Idempotency Audit

Date: 2026-11-23
Plan: Unified Master Plan V4 / Unified Task Register V4
Original branch: `feature/u10-alert-idempotency-v4`

Durable-dedupe follow-up: V4 continuation branch

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
seconds, including after a process restart. The fingerprint is stored in the
existing `alerts` table through an additive migration and claimed under SQLite's
writer lock. For configured external channels, the claim and outbox delivery rows
are committed atomically; a restart before the first send therefore leaves durable
work to drain. A different account/action remains a separate event. If account
identity cannot be verified, dedupe is disabled so one account cannot suppress
another account's alert. Gateway command behavior is unchanged; alert dedupe is
not command idempotency.

## Evidence

| Check | Result |
|---|---|
| Same account/action repeat alert is deduplicated; other account stays independent | PASS — `tests/test_notify_channels.py`, `tests/test_runtime_position_ownership.py` |
| New Notifier after restart deduplicates a keyed event | PASS — `tests/test_notify_channels.py::test_keyed_alert_dedupe_survives_notifier_restart` |
| Concurrent Notifier instances atomically claim one keyed event | PASS — `tests/test_notify_channels.py::test_keyed_alert_claim_is_atomic_across_notifier_instances` |
| Restart before first provider send recovers the durable outbox row | PASS — `tests/test_notify_channels.py::test_keyed_alert_outbox_survives_restart_before_first_send` |
| Additive migration retains alert/outbox rows | PASS — `tests/test_notify_channels.py::test_alert_dedupe_column_migrates_existing_rows_without_replacing_them` |
| Existing unknown position-modify intent does not resend | PASS — `tests/test_position_modify_intents.py::test_gateway_does_not_retry_unknown_modify_intent` |
| Notification/outbox, delivery, ownership, modify, readiness, AI explain and API regression | PASS — 270 passed, 1 deselected, 1 existing Starlette/httpx deprecation warning |
| Chart viewport suite | PASS — 7 passed |
| Selected Ruff F/E9/I, `compileall`, `git diff --check` | PASS |
| Hosted CI #150 from the preceding U10 slice: repository Gate, real-Redis proof/self-check, dashboard build and bundle-size check | PASS; this continuation's hosted Gate is pending its PR |
| Full repository pytest on Windows | INCONCLUSIVE for repository-wide acceptance: 1,558 passed, 37 skipped, 3 failed and 18 Redis tests errored in 399 seconds. The Redis test server found on this host rejects RESP3 `HELLO`; the 3 UI failures were due to missing worktree `node_modules`/dashboard `dist` and passed after `npm ci`, Vite build, and an isolated rerun. Hosted CI #150 supplied the complete gate and passed. |
| Broker Demo/Live notification and execution receipts | NOT TESTED; no broker action was sent |

U10 notification-dedupe acceptance is complete. Outbound notification remains
at-least-once: if the provider accepts a request but the process loses its response,
the durable outbox can retry it. Alert deduplication is not execution idempotency.
Full/partial-close gateway replay after an ambiguous acknowledgement remains a
separate U05 execution-gateway gap.

## Safety and rollback

This change only deduplicates keyed management notifications and does not authorize,
retry, suppress, or alter an order/position command. The additive SQLite migration
retains existing alert rows; rollback the application artifact without dropping
`alerts.dedupe_fingerprint`. No MT5, Paper, Demo or Live command was issued.
