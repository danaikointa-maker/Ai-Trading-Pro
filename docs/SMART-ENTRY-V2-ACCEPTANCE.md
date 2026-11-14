# Smart Entry V2 — Operational Acceptance / MT5 Demo Checklist

Status: **NOT APPROVED FOR REAL MONEY**. This checklist cannot be signed by an
automated test on synthetic prices. Each item needs time-stamped broker evidence.

## Implemented software checkpoints

1. Original signal/zone/risk evidence is committed before a pending order claim
   becomes visible to the broker adapter. If evidence insertion fails, the order
   is not sent. Account identity and idempotency remain independent vetoes.
2. A new append-only `position_events` table records `requested` management
   actions before broker I/O and their subsequently observed outcome. It does
   **not** upgrade an accepted but unverified close into a verified broker fill.
3. Open-position and closed-trade review show original plan, decision-time M5
   candles where available, SR zone boundaries, flips, Fibonacci and structure.
   Display switches affect presentation only. Historical **post-entry** candles
   are not reconstructed unless separately recorded; recorded real exit prices
   are shown as horizontal evidence lines.
4. Up to three `entry_proposals` are read-only scenarios with per-plan sizing,
   combined risk/lot caps and conservative position slots. They cannot be
   submitted via the order endpoint. The existing `Signal + RiskGate` path is
   unchanged; the default configuration may allow only one position slot.
5. Readiness notification transitions are persisted in the local workspace DB
   for recent restarts, without granting execution permissions.
6. Historical backtest reports now include structured spread/slippage/commission
   assumptions. The separate offline release gate rejects synthetic history,
   insufficient folds, unverified bar paths, cost regressions and missing Demo
   reconciliation evidence; it **never** switches the trading mode.
7. Broker-position polling appends account-scoped observations for unknown,
   changed, disappeared and restored positions, without claiming verified
   closure or attributing a change to a human. Repeated identical observations
   are deduplicated across restarts and competing reconciler processes. A
   broker-missing position retains its last local baseline pending verified
   history instead of being silently removed. The normal position-management
   refresh performs this check **inside the same SQLite transaction** as its
   mirror update; failing to save the observation rejects the refresh, leaving
   the preceding mirror untouched. The separate direct mirror-replacement API
   *inside the codebase* remains available to trusted reconciliation workflows;
   this does not introduce a new end-user permission to rewrite history.

## Reproducible backtest evidence (operator run)

1. Import authentic historical **M1** candles through the existing importer,
   with source provenance. Prefer matching tick/deal history covering the same
   window. Verify the dataset fingerprint; preserve the immutable snapshot.
2. Create three backtest reports with the **same** `snapshot_id` and rules:

   | Scenario | Example spread | Example slippage | Objective |
   |---|---:|---:|---|
   | Baseline | Actual broker spread | 2 pts | Normal historical costs |
   | Stress A | ≥ baseline ×2 | ≥ 4 pts | Cost deterioration |
   | Stress B | ≥ baseline ×3 | ≥ 10 pts | Extreme costs/disconnect gap |

   The actual broker's contract spec, point and commission take precedence over
   these illustrative numbers. Do not select stress inputs after seeing P&L.
3. Confirm all reports have `dataset.sha256`, `dataset.reproducible=true`,
   `diagnostics.cost_assumptions`, tick-path evidence and four walk-forward
   folds. Inspect sample size and rejected signals; a high headline win rate
   on a small sample is not an acceptance result.
4. Save JSON reports from `GET /api/backtests/{report_id}`. Run:

   ```bash
   python scripts/smart_entry_release_gate.py \
     --baseline baseline.json \
     --stress stress-a.json --stress stress-b.json \
     --demo mt5-demo-evidence.json
   ```

   Exit status 2 means blocked. Even exit 0 means *ready for independent
   operator review*, never permission to turn on LIVE.

## Real MT5 Demo observation (cannot be simulated away)

- [ ] Broker/account/login/server and symbol specs verified, Demo account only.
- [ ] 14+ forward-market days and 30+ closed Demo trades with traceable deal IDs.
- [ ] Entry/SL/TP and pre-order snapshots checked against the actual terminal.
- [ ] Partial fills, commission/swap, close fragments and netting/hedging reviewed.
- [ ] Disconnect **before** and **after** broker acknowledgement; never auto-resend
      a pending/unknown order under a new idempotency key.
- [ ] Restart with an unresolved order and with open positions; accounts remain
      owned by the same workspace; no phantom position or duplicate entry.
- [ ] Manual MT5 changes to SL/TP, manual close and partial close are detected
      and recorded without rewriting the original plan.
- [ ] Stale bars, news lockout, bad spread, missing FX conversion or contract
      info, kill switch and full-auto lock **all block** new orders.
- [ ] Confirm alerts (BLOCKED/WAIT/EXPIRED) do not grant order permission and
      do not spam after process restart.
- [ ] Independently review backups, rollback and recovery on Windows VM / PVE.
- [ ] Explicit authorized human approves any LIVE change; this PR does not.

`docs/examples/no7-mt5-demo-evidence.example.json` starts with all checks false.
Only replace values after attaching real broker screenshots/logs, deal-ledger
exports and timestamps. A local JSON file is *self-reported evidence*, not
cryptographic proof of an MT5 terminal's behavior.

## Remaining blockers

- No connected MT5 Demo terminal or real tick/deal history is available in this
  repository execution environment. Therefore Demo acceptance, forward returns,
  30-trade coverage, slippage and profitability **cannot** be claimed here.
- An optional three-timeframe Stochastic veto is deliberately *not* permitted
  to change live order decisions until out-of-sample A/B testing on the same
  real snapshots is available. Today it remains observational.
- Full broker-side partial-fill attribution and post-entry candlestick capture
  depend on terminal history and order/deal ID semantics; the current ledger
  displays matching position IDs but does not infer strategy ownership.
- A difference in broker `positions()` does not identify whether the MT5 user,
  another EA, the broker or a netting operation caused it; the observation is
  evidence of a discrepancy only, not evidence of its cause or a completed fill.

The system must stay on PAPER/DEMO and the PR remain Draft until these gates
are satisfied on the target installation.
