# U00 Project Audit — 2026-11-21

**Repository:** `danaikointa-maker/Ai-Trading-Pro`  
**Branch / baseline:** `plan/unified-development-v4` / `559a2de`  
**Audit scope:** source, config, tests, V4 ownership/dependencies, and read-only host status.  
**Outcome:** source audit complete. VM100 runtime and backup readiness are not demonstrated; U01 remains blocked until fresh Demo market data is verified.

## Workspace and host evidence

- The V4 planning worktree is `C:\workspace\Ai-Trading-Pro-unified-v4-plan`, clean at audit start, tracking `origin/plan/unified-development-v4`. The source-development checkout `C:\workspace\Ai-Trading-Pro` is a different branch (`integration/unified-tradeai`) with 69 modified/untracked paths. Those pending edits were not copied into or treated as evidence for this V4 audit.
- Read-only SSH to `danai@192.168.1.10` succeeded on 2026-11-21. It reported `ai-server`, Linux `5.15.0-202-generic`.
- `/opt/no7-ai-trading-pro` was absent, but a second read-only inspection found the actual runtimes under `/home/danai`: port 8000 is `no7-ai-trading-pro-dev` (`integration/unified-tradeai`, `57fc321`, `env=development`, `feed_mode=simulate`); port 18081 is `no7-ai-trading-pro-v4-staging` (`feature/u02-100pt-confirmation`, `06642a0`, `env=staging`, `feed_mode=mt5_demo_publisher_stale`, `fresh=false`, quote age about 46 minutes). Both listeners bind to `127.0.0.1`; the 18081 staging instance is not running the V4 planning branch. They are Python processes, not matching systemd services. The stage checkout was clean. The only matching host timer was `dpkg-db-backup.timer`; this is not proof of an application data backup or tested restore.
- The user's later instruction makes the developer Windows PC the current MT5 host; VM200 is not to be used unless separately reauthorized. The Windows MT5 terminal process was found at `C:\workspace\Ai-Trading-Pro\bridge\MetaTrader 5\terminal64.exe`, and local tunnel port 18181 responds. No Python market-publisher process was found. At the U00 baseline commit `559a2de`, the V4 branch did not contain the isolated publisher; fresh quote data and exact terminal account identity were therefore **NOT TESTED**.
- No bridge command, order, account change, configuration activation, runtime deployment, merge, or live trading was performed.

## Evidence-based gap matrix

| ID | Status | Source and tests found | Gap / acceptance still needed |
|---|---|---|---|
| U00 | DONE — source audit only | This matrix; V4 task register; source/config/test inventory below | Host backup/restore and runtime readiness are not claimed. |
| U01 | BLOCKED | `services/market_data/service.py`, `snapshots.py`, `ticks.py`; `tests/test_market_snapshot.py`, `test_tick_data.py`, `test_mt5_readonly.py`, `test_mt5_reconnect_safety.py` | At baseline `559a2de`, VM100 had isolated port-18081 staging at `06642a0`, stale, and V4 had no checked-in PC publisher. The follow-up below adds audited source and focused test evidence; staging alignment, fresh Demo ticks, rates/spec and end-to-end acceptance remain outstanding. |
| U02 | MISSING | Existing signal state/expiry in `services/strategy_engine/engine.py`; no 100-MT5-point state owner or 99/100-point/expiry suite found | Implement one deterministic confirmation state machine only after U01 provides verified Bid/Ask and point metadata. |
| U03 | PARTIAL | Active legacy settings in `config/risk.yaml`; `services/risk_engine/engine.py` | No separate `conservative_v4_candidate` profile or migration evidence found. Preserve active 0.50% per-trade, 5% weekly, 10% DD, 1.30 net RR and current partial defaults. |
| U04 | PARTIAL | `services/risk_engine/planner.py`; `tests/test_points_math.py`, `test_invariants.py`, `test_spec_safety.py` | Shared planner and broker-spec math exist. V4 candidate rules (closed M5 ATR + swing structure, 2R, net RR≥1.5, actual cost/min-lot constraints) are not evidenced as an isolated profile; no broker acceptance. |
| U05 | PARTIAL / UNVERIFIED | `services/execution_gateway/gateway.py`; `services/bridge/relay.py`, `store.py`; `integrations/brokers/bridge.py`, `mt5_live.py`; `bridge/No7BridgeEA.mq5`; idempotency, bridge, reconnect and ownership tests | Existing gateway and durable bridge claims should be reused. Default EA is read-only; source-level modify handling exists, but broker-confirmed modification, installed EA build, Demo round-trip and single-writer host acceptance are NOT TESTED. |
| U06 | PARTIAL | Existing `PositionManager` in `services/risk_engine/manager.py`; called from `services/api_gateway/state.py`; position events in `packages/persistence/position_events.py` | Existing legacy BE/trailing/partials must be extended, not replaced. BE and trailing are evaluated independently and can emit two modify actions for one ticket in one cycle; gateway records modifications as accepted-but-unverified. No candidate reducer/immutable initial-R/one-modify reconciliation matrix found. |
| U07 | MISSING | Entry modes and general role checks exist in API/UI; no four position-protection mode API/schema/persistence/UI found | Manual/Semi/Full/Hybrid protection modes and versioned per-account overrides remain planned. Keep Full Auto off. |
| U08 | PARTIAL | `services/risk_engine/planner.py::points_calculator`, `/api/market/calculator`, `apps/web-dashboard/src/components/PointsCalculator.vue`; `tests/test_points_math.py` | Existing read-only points→profit calculator uses backend math. The 16-tool learning center, source/provenance labels, account-currency/BE/ATR/FX coverage and MT5 comparison are absent. |
| U09 | PARTIAL | Vue dashboard and `PriceChart.vue`; `tests/test_positions_ui.py` | Current terminal/chart/risk/positions UI exists. Position-protection screen, short-range markers, chart-stability screenshot/browser evidence and role-by-role acceptance are absent. |
| U10 | PARTIAL | `services/notification/notifier.py`, `outbox.py`, `signing.py`; notify/outbox tests | Notification infrastructure and dedupe/outbox are present; delivery of the planned protection lifecycle events and end-to-end no-duplicate alert evidence remains unverified. |
| U11 | BLOCKED | `scripts/check-mt5-demo.ps1`; release-gate and MT5 test files | No fresh Demo session, install/EA identity, power-loss/partial-fill receipt, or operator acceptance evidence in this audit. No LIVE test permitted. |
| U12 | MISSING | No `integrations/no7_local_ai/` implementation found in this branch | Read-only AI Trader Team integration remains planned and must have no execution capability. |
| U13 | PARTIAL | Current architecture/API/MATH/RUNBOOK/LIMITATIONS docs plus V4 planning docs | V4 plan and conflict records exist; technical docs still describe current/legacy behavior and must be synchronized only alongside implementation PRs. |

### High-priority safety observation

`PositionManager.evaluate()` has separate BE and trailing branches that append `modify` actions independently. `TradingRuntime` then iterates those actions and submits each through `ExecutionGateway` without an intervening broker snapshot/reconciliation. Therefore, when both triggers qualify for one position, the source permits two modification requests in the same evaluation cycle. This is an implementation gap for U06, not a broker-side test result. Do not enable new automatic position management until U06 prevents duplicate modifications and verifies the accepted broker SL.

## Baseline validation

Commands executed from the V4 worktree:

```text
python -m pytest tests/test_risk_engine.py tests/test_smart_entry_continuation.py tests/test_execution_recovery.py tests/test_bridge.py tests/test_mt5_readonly.py tests/test_positions_ui.py tests/test_points_math.py tests/test_signal_execution.py -q
137 passed, 1 existing Starlette/httpx deprecation warning, exit 0 (22.80s)

npm ci
added 114 packages; npm audit reported 3 vulnerabilities (2 moderate, 1 high)

npm run build
Vite 5.4.21; 624 modules transformed; build passed (15.74s)
```

Full pytest suite, browser visual acceptance, Windows MT5 session/publisher, fresh broker quote, VM100 backup/restore, VM100 application runtime, staging end-to-end and Demo execution were **NOT TESTED**. The installed Redis server on this PC is 5.0.14.1; `tests/test_redis_real.py` expects Redis 6+ `HELLO`, so it is not a usable local real-Redis acceptance environment without a compatible test binary.

## Security, deployment, and rollback

- Audit used source inspection, deterministic local tests/build, and read-only SSH commands only. No credential values were read or included.
- No application files were changed on VM100; no port/firewall/service was opened or restarted. Existing 8000 development and 18081 staging processes were only inspected. Nothing was deployed or merged.
- This audit adds documentation only. Rollback is `git revert <U00 audit commit>`; no runtime/config rollback is required.
- Before U01 can pass, update the separately isolated 18081 staging checkout to the V4 source without touching 8000, and run the reviewed PC publisher against the existing loopback tunnel. Verify Demo identity and genuinely fresh ticks before proceeding. Keep the user's PC MT5 account and VM100 runtime isolated; do not make LIVE capability available.

## Next task

U01 was next in dependency order at the U00 baseline. Follow-up on 2026-11-21 is recorded below; source is now present in V4, while the isolated staging process is still on an older branch and has stale quotes.

## U01 follow-up — 2026-11-21

- Reused existing market-publisher work in focused commits on `plan/unified-development-v4`; no duplicate market service or execution route was created. Current V4 code requires a separate publisher token, exact Demo identity and a data-only payload; Python MT5 publisher accepts UTC timestamps only and withholds ticks older than the configured 1–15 second limit (default 10 seconds). Bridge EA time normalization separately requires an explicit same-snapshot UTC anchor.
- V4 regression command: `python -m pytest tests/test_market_snapshot.py tests/test_bridge.py tests/test_api.py tests/test_mt5_market_publisher.py tests/test_mt5_market_publisher_script.py tests/test_mt5_runtime_preflight.py -q` — **99 passed**, one existing Starlette/httpx deprecation warning (17.11s). `npm.cmd run build` — **passed**, Vite 5.4.21, 624 modules transformed. `git diff --check` — passed.
- Read-only preflight through existing PC tunnel `127.0.0.1:18181` returned `health_api=true`, `publisher_route=true`, `publisher_fresh=false`, `feed_mode=mt5_demo_publisher_stale`, `ready=false`. VM100 port 18081 is still checkout `feature/u02-100pt-confirmation` at `06642a0`; port 8000 remains `integration/unified-tradeai` at `57fc321`, `env=development`, `feed_mode=simulate`. PC MT5 terminal process and tunnel were present; no PC market-publisher process was found.
- The V4 source/tests are **PARTIAL/PASS**; U01 runtime acceptance remains **BLOCKED**. No staging files/processes, port 8000, bridge setting, broker account, order or position were changed. Next: publish this reviewed branch, align only the isolated port-18081 staging checkout, verify health/stale behavior, then start the V4 read-only publisher against the current Demo session and compare real broker quote/rates/specs. Keep port 8000 untouched.
