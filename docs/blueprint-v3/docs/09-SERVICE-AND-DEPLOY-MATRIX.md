# Service Deployment Matrix and software plan

| Node | Source / runtime | Deploy | Prerequisites | Must NOT do |
|---|---|---|---|---|
| DEV PC | `C:\workspace\TradeAi` | Git, VS Code, Python venv, Node LTS, test, SSH, release packaging | verify real OS/versions | live broker secrets or root auto-approve |
| Proxmox | host `192.168.1.254` | VM, bridge/vLAN, backup, alerts, QEMU agent | verify storage, SMART and backup | business services / Docker |
| Ubuntu VM100 | `/opt/no7-ai-trading-pro` | FastAPI, Vue build/static, Nginx proxy/TLS, quant/risk, PostgreSQL target, optional Redis, low-priority AI workers | secure SSH, clock sync, Python deps, disk, backup | local MT5 Python terminal adapter or broker secrets in Git |
| Windows VM200 | `C:\app\app\No7-Ai-Trading-Pro` | Connext Demo terminal, MetaEditor, `bridge/No7BridgeEA.mq5`, optional diagnostic `MetaTrader5` Python, Windows defender, Guest Agent, broker reconciliation | patched supported OS, real IP, TLS trust, Windows account | quant/model training, central DB or exposing order listener |

## Actual source mapping (as of observed repo layout)
- Ubuntu: `services/api_gateway`, `services/market_data`, `services/strategy_engine`, `services/ai_forecast`, `services/risk_engine`, `services/backtest_engine`, `services/execution_gateway` (logical coordinator), `services/notification`, `services/bridge` (server-side relay), `packages/*`, `apps/web-dashboard` (compiled static assets), `integrations/no7_local_ai`.
- Windows: `bridge/No7BridgeEA.mq5` compiled with MetaEditor; optional `integrations/mt5/python_bridge` once audited and implemented; no full FastAPI server required on VM200.
- DEV: full repo including `tests/`, docs, infra scripts.
- `integrations/brokers/mt5_live.py`: inspect runtime assumptions; do NOT run direct Linux MT5 access. Route through verified Windows-side bridge.

## Rollout phases
1. Bootstrap Ubuntu and Windows SSH/Guest Agents; harden and validate TLS. Do not expose ports to Internet.
2. Baseline tests: `python -m pytest tests -q` and `cd apps/web-dashboard; npm ci; npm run build` on DEV.
3. Ubuntu Python venv + dependencies, install web build and app, bind FastAPI `127.0.0.1:8000`; reverse proxy trusted LAN/VPN HTTPS.
4. Compile/test existing MQL5 EA; connect DEMO terminal, configure allowlist and WebRequest endpoints; verify symbol specs and data feed. Existing README marks EA as unverified on real terminal.
5. Stage read-only tick/candle, health and reconciliation before enabling demo order intent; Test broker receipt idempotency.
6. Migrate SQLite -> PostgreSQL only after dual-run parity, backup, rollback and RLS tests. Redis optional initially; do not start many workers without valid leader fencing.
7. Activate research workers only after stable data feed and resource baselines.

## Capacity & paths
- VM100 assumed 16GB/2 vCPU, VM200 8GB/2 vCPU; check actual `qm config` and RAM headroom. CPU-only training can starve inference; schedule/limit training and LLM.
- Keep source and data separate; DB/images/model snapshots on backed-up managed storage; avoid placing large runtime data inside Git checkout or VM boot image without backup policy.
- VM200 runtime path explicitly `C:\app\app\No7-Ai-Trading-Pro`, DEV source explicitly `C:\workspace\TradeAi`.
