# 01 — Unified Architecture and Integration Contract

## 1. Physical and logical topology
- Development PC: `C:\workspace\TradeAi`, Git clone + VS Code + tests + Release tooling. SSH to VM100/VM200; Proxmox management limited.
- Dell OptiPlex 7040, 32GiB, Proxmox `192.168.1.254` management node only.
- VM100 Ubuntu 16GiB/2vCPU: app runtime at `/opt/no7-ai-trading-pro`. FastAPI serves Vue static SPA and JSON/WS API; Python analysis, risk and inference; SQLite initially; optional PostgreSQL later. Trading leader process single-worker initially. Background heavy jobs throttle and pause on load.
- VM200 Windows 8GiB/2vCPU: `C:\app\app\No7-Ai-Trading-Pro` selective checkout; MT5/MetaEditor, outbound EA bridge, optional Python diagnostic probe. Broker credentials remain in terminal Windows account.
- VM IPs must be discovered from actual guests (`hostname -I`, `ipconfig`), use DHCP reservations or static addresses after verifying router/subnet, DNS names `no7-ai.internal`, `no7-mt5.internal` where feasible.
- Prefer separate Proxmox bridge/VLAN for VM-to-VM trading and VPN for management. Use LAN+host firewalls until VLAN available. Never expose Proxmox UI/SSH, MT5, DB or Redis publicly.

## 2. Shared components without duplicating runtime
- Git/source + build artifacts: GitHub TradeAi is canonical, build from tagged commit.
- Core config: `config/app.yaml`, `config/brokers.yaml`, `config/risk.yaml`, `.env` secrets; add `config/deploy/` only for non-secret host overrides. Path from `NO7_ROOT`.
- Python types: Pydantic `packages/shared_schemas`, schema version; use REST JSON + WS event contract. Clients reject unknown critical schema versions.
- Data: UTC timestamps + monotonic sequence where available; `source` enum simulate/replay/broker, broker_id, account_id, symbol_original, symbol_canonical, tick_size, decimals, freshness.
- Logs: JSON {ts_utc, service, host, environment, trace_id, correlation_id, event_id, schema_version, status}; redact keys, personal/financial data.
- Event delivery: durable inbox/outbox + idempotency for order paths; Redis optional for queues/caches, NOT sole order ledger. DB remains authority.

## 3. Event and order lifecycle
1. MT5 terminal returns actual symbol specs, ticks, M1 candles, positions and connection status.
2. Bridge EA makes outbound authenticated HTTPS requests to Ubuntu `/api/bridge/register` and `/api/bridge/poll`; its URL must be allow-listed in MT5. Check source contract before modifying endpoint shape.
3. Ubuntu normalizes immutable snapshots, validates data and freshness; quarantines invalid prices, offsets, missing ticks, clock skew, spread outliers.
4. Single Trading Core owner computes indicators, confirmed/candidate zones, regime, validated forecast and explanations; proposes BUY/SELL/WAIT.
5. Deterministic TradePlanner + RiskEngine decide Allow/Deny. Default WAIT/PAPER. Demo execution needs explicit manual enable and token scoped to demo account.
6. Durable approved instruction has UUID, short expiry, exact account/symbol/side/lot/price bounds/SL/TP, risk decision hash, idempotency key, schema version and execution mode; never trust LLM output as instruction.
7. EA polls, verifies account and constraints locally, sends at most once, collects broker ticket/retcode, reports receipt; ambiguous result => reconcile, do not resend.
8. Windows resends *receipts* as needed but never repeats order, Ubuntu stores audit and updates UI/notifications; discrepancies trip kill switch.
9. Closed positions enter review queue, can produce proposed experiments only, never immediately alter live model or risk settings.

## 4. Existing repository mapping
- Existing UI: `apps/web-dashboard` Vue 3 + ECharts/Lightweight Charts; do not replace with Laravel.
- Existing API: `services/api_gateway` FastAPI + JWT/WebSocket; preserve existing REST paths in `docs/API.md`.
- Existing analysis: `services/market_data`, `services/strategy_engine`, `services/ai_forecast`, `services/risk_engine`, `services/backtest_engine`.
- Existing order path: `services/execution_gateway`, `services/bridge`, `integrations/brokers`, `bridge/No7BridgeEA.mq5`.
- Existing models/data: `storage/` (not in Git); `packages/persistence` currently SQLite. Plan PG migration separately.
- Existing Ollama integration: `integrations/no7_local_ai`; extend only for read-only copilot and loss review.

## 5. Mandatory integration tests
- MT5 demo bootstrap and symbol spec; EA compile and URL allowlist; same-account wrong broker/account block.
- One command one execution even under timeout, reconnect, duplicate poll, server restart and stale snapshots.
- Risk veto across UI/API/bridge; manual terminal position changes trigger reconciliation.
- On Ubuntu core or VM200 outage: no new orders; native broker-side SL/TP persist; on restart reconcile before trading.
- UI shows SIMULATED/REPLAY/BROKER badge and model APPROVED/UNVALIDATED truthfully.

## 6. Future optional migrations (NOT setup prerequisites)
- PostgreSQL: transactional trade ledger, audit, multiuser, migrations and shadow read comparison; do not change SQLite until data migration verified.
- Redis: queue/leases when multiple workers needed; prove fencing to avoid split brain.
- MLflow Registry: optional tracking on same Ubuntu later; not needed for first demo pipeline.
- Second machine GPU: train heavyweight models off-server and import signed artifacts when budget allows.
