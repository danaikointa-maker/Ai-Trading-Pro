# U00 Project Audit — Unified Master Plan V4

Audit date: 2026-11-20 (Asia/Bangkok)  
Repository: `danaikointa-maker/Ai-Trading-Pro`  
Planning baseline: `plan/unified-development-v4` at `559a2ded5dc1530cfcb61072e2432220742f6d0d`  
Audit/implementation worktree: `feature/u05-readonly-mt5-positions`; PR #36 is open as Draft against the planning branch.

## Scope and evidence rules

Read the V4 binding instructions, plan, task register, conflict register and VS Code execution prompt, then inspected the owning source, configuration, tests and current-state documentation. “Exists” means source is present; it does not certify broker behavior. Runtime behavior is called verified only where a current receipt was observed. Do not change active legacy risk defaults from this audit.

The original `C:\workspace\Ai-Trading-Pro` worktree already contained user modifications on `integration/unified-tradeai`; it was left untouched. The V4 implementation is isolated in the worktree and branch named above.

## U-ID gap matrix

| U-ID | Finding | Evidence and current gap |
|---|---|---|
| U00 | **DONE — audit recorded** | This matrix plus current branch/host checks. U00 is an audit deliverable, not a deployment-readiness claim. |
| U01 Market data | **PARTIAL / BLOCKED on time normalization** | Existing [`MarketDataService`](../services/market_data/service.py), [`MT5Broker`](../integrations/brokers/mt5_live.py), and snapshot tests exist. Actual local terminal read-only capture confirmed Connext-Demo / `XAUUSD.s`; MT5 tick epoch was about 7,200 seconds ahead of the PC clock. Current `data_quality()` uses `max(0, now - tick.t)`, so a future timestamp is reported as zero staleness. Freshness must fail closed until broker/server time mapping is explicit and covered by tests. |
| U02 Signal confirmation | **MISSING per V4** | Closed-candle components exist in strategy rules, but no single 100-point WAIT state with expiry/chase/dedup was found; `services/strategy_engine/confirmation.py` and its acceptance tests are absent. |
| U03 Risk profile | **LEGACY EXISTS; V4 candidate MISSING** | [`config/risk.yaml`](../config/risk.yaml) contains the current risk, BE/trailing and partial defaults. Conflicts register correctly preserves them; no separate inactive/versioned V4 candidate or migration was found. |
| U04 Initial SL/TP | **PARTIAL** | [`TradePlanner`](../services/risk_engine/planner.py) and backend calculator exist. Broker-specific tick/stop/freeze, cost-adjusted Net RR and candidate-profile behavior remain to be verified or extended. |
| U05 Execution/modify | **BLOCKED; read-only Demo PR not deployed; live Demo order path unavailable** | Existing [`ExecutionGateway`](../services/execution_gateway/gateway.py) is the sole V4 order path. PR #36 adds read-only positions, not orders. VM100 is running a different, dirty `integration/unified-tradeai` checkout; its `.env` selects simulation, disables the bridge and keeps it read-only. The running API returned 404 for GET probes of the source-defined Demo execution/order routes, while the source files on disk contain those routes. No order/modify call was sent. Align/review the backend source, keep MT5 time freshness fail-closed, and separately approve a Demo-only activation before broker execution acceptance. |
| U06 Position protection | **LEGACY EXISTS; V4 protection refactor MISSING** | [`PositionManager`](../services/risk_engine/manager.py) already generates partial, BE and trailing actions. BE and trailing can generate separate modifications for one position in the same evaluation; no focused protection matrix proves one non-worsening modification per position, race behavior or restart reconciliation. Do not create another manager. |
| U07 Operating modes | **MISSING per V4** | Existing API/UI have manual and legacy auto gates, but not the four V4 protection modes with scoped RBAC, versioned overrides, audit and concurrency tests. |
| U08 Calculators | **PARTIAL** | Backend [`points_calculator`](../services/risk_engine/planner.py), calculator routes and Vue component exist. V4 scope to expand the shared authoritative calculator is not complete; no duplicate frontend math should be added. |
| U09 Dashboard | **EXISTS / PARTIAL** | Existing Vue Dashboard/Trades, PositionsTable and chart exist. PR #36 adds a selector and manual read-only Demo refresh, keeps that snapshot separate from runtime/simulator data and removes close controls in linked read-only mode. Build and UI smoke passed; actual browser screenshot/layout and full API-to-browser session were not tested. |
| U10 Alerts | **EXISTS / PARTIAL** | Notification service and current event paths exist. Idempotent protection-specific signal/alert integration and no-duplicate acceptance are still outstanding. |
| U11 Demo acceptance | **BLOCKED for execution acceptance** | A read-only Demo snapshot was verified; this does not accept order/modify, partial fill, outage recovery or power-loss behavior. Those require their own approved, captured Demo receipts. Live remains prohibited. |
| U12 AI Trader Team | **PLANNED** | No integrated V4 shared read-only research/observability access with explicit non-execution test was verified. |
| U13 Documentation sync | **ONGOING BY DESIGN** | V4 README/API/RUNBOOK/LIMITATIONS/Task Register updates are included with PR #36. Continue updating the relevant docs in every implementation PR; this is not a separate feature to rebuild. |

## Configuration and system boundaries

- [`config/app.yaml`](../config/app.yaml): simulated feed default; full auto disabled by default; bridge read-only default enabled. These are current config facts, not broker acceptance.
- [`config/brokers.yaml`](../config/brokers.yaml): broker profiles and symbol specifications exist; exact Connext `XAUUSD.s` runtime spec must be captured from the broker before using strategy/risk calculations.
- [`config/risk.yaml`](../config/risk.yaml): legacy weekly loss 5%, drawdown 10%, minimum RR 1.30, one open position, legacy partial/BE/trailing values. Preserve until a separate candidate/migration passes V4 review.
- Existing FastAPI/Vue/MQL5/SQLite, RiskEngine, PositionManager and ExecutionGateway are the authoritative modules. No second engine, API backend or database is needed.

## Current host and branch receipts

- Planning branch: `plan/unified-development-v4`, baseline `559a2ded5dc1530cfcb61072e2432220742f6d0d`; it is documentation-only relative to `origin/main`.
- Working branch: `feature/u05-readonly-mt5-positions`; PR #36 is open, draft, mergeable, and targets the planning branch. CI `gate` run 68 completed successfully. It has not been merged or deployed.
- **Earlier VM100 check corrected:** a fresh read-only SSH check on 2026-11-20 found the active project at `/home/danai/no7-ai-trading-pro-dev` (branch `integration/unified-tradeai`) with tracked and untracked modifications. A Python/Uvicorn process (PID 51028) is bound to `127.0.0.1:8000`; no systemd unit was found. No remote files or services were changed.
- Safe `.env` values on VM100 are `NO7_FEED_MODE=simulate`, `NO7_BRIDGE_ENABLED=false`, `NO7_BRIDGE_READ_ONLY=true`, `NO7_ALLOW_FULL_AUTO=false`; database path is `storage/db/no7.sqlite3`. No credentials or tokens were read.
- On this PC, PID 20800 is Vite from the original user worktree on `127.0.0.1:18000`; PID 12692 is SSH forwarding `127.0.0.1:18080` to VM100 port 8000. Read-only unauthenticated GET probes to `/api/broker-accounts/probe/demo-execution`, `/orders`, and `/signal` returned 404 from the running API; `/api/broker-accounts` and `/api/risk/settings` returned 401 (auth required). The VM checkout source contains Demo execution/order routes, so the loaded API route set is not aligned with the source now on disk. No authenticated mutation was attempted.
- This PC's MT5 terminal is `C:\workspace\Ai-Trading-Pro\bridge\MetaTrader 5\terminal64.exe`. Read-only Connext-Demo `****1427` capture found `XAUUSD.s` with 0 open positions. A second capture found the latest tick and M1 bar timestamps ~7,200 seconds ahead of PC UTC; freshness remains uncertified. No orders or modifications were sent.
- The U05/U09 implementation in PR #36 is not deployed to either active checkout. The root development checkout and VM100 branch contain user changes and were left untouched.

## Automated verification recorded

On the PR worktree, the exact focused+regression command covering MT5 read-only, account/API authorization, Positions UI, bridge/recovery and account-ownership tests completed **320 passed, 1 Starlette/httpx deprecation warning**:

```powershell
python -m pytest tests/test_mt5_readonly.py tests/test_mt5_windows_pc_readonly.py tests/test_accounts.py tests/test_api.py tests/test_positions_ui.py tests/test_bridge_readonly.py tests/test_execution_recovery.py tests/test_runtime_position_ownership.py tests/test_mt5_reconnect_safety.py tests/test_position_snapshot_atomic.py tests/test_account_ownership.py tests/test_history_account_ownership.py tests/test_bridge.py -q
```

`npm.cmd run build`, selected Ruff safety checks, `py_compile`, and `git diff --check` passed. This is not the full repository test suite. Real MT5 read-only worker receipt passed on Demo; UI end-to-end against a running app, actual broker modifications, and all execution/power-loss tests remain untested.

## Dependency-ordered next work

1. **U01** correct/explicitly map broker tick time and server timezone; reject future timestamps rather than treating them as zero-age; capture Connext symbol metadata and add tests for future, stale and DST/offset cases.
2. **U02** add the single 100-point WAIT/expiry/dedup confirmation only after U01 freshness is trustworthy.
3. **U03 → U04** add the inactive versioned risk candidate and extend the existing planner with broker constraints/costs.
4. **U05 → U06** finish guarded single-writer modify/reconcile tests, then refactor the existing PositionManager to one safe BE/trailing candidate per position.
5. **U07 → U10** add modes, shared calculator scope, dashboard acceptance and idempotent protection alerts, reusing current services/components.
6. **U11** perform only separately approved Demo execution acceptance after automated gates; no Live.
7. **U12** integrate the trader team read-only after core contracts are stable. Update docs with each PR under U13.

No merge, deployment, Live trading, broker account switching, or remote host mutation was performed.
