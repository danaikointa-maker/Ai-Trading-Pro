# TRADEAI UNIFIED PLATFORM — AGENT CONTRACT V2

## Source of truth
Use https://github.com/danaikointa-maker/TradeAi as the ONLY main application repository. Read its README.md, docs/ARCHITECTURE.md, docs/RUNBOOK.md, docs/LIMITATIONS.md, config/app.yaml, config/brokers.yaml, config/risk.yaml, and this file before changing code. Preserve existing Python FastAPI, Vue 3, MQL5 bridge, broker adapters, and tests. Do NOT scaffold Laravel or reimplement existing modules without an approved migration.

## Host roles
- Developer Windows PC: write/test/review/commit/deploy. Never store live trading keys in git or agent prompts.
- Proxmox 192.168.1.254: VM, networking, backup only. No app installation. Never modify storage/partition or root networking without manual approval and verified backup.
- Ubuntu VM100 (IP unknown until audit): one authoritative Trading Core, API/WebSocket/UI, simulated/replay/MT5 market normalizer, inference, strategies, risk veto, persistence, telemetry, controlled low-priority training and local LLM explainer.
- Windows VM200 (IP unknown until audit): Connext MT5 Demo terminal, MetaEditor/MQL5 bridge EA, tick/position snapshots, locally validated demo execution, order acknowledgments and reconciliation. Bridge calls OUTBOUND to Ubuntu, not Windows listening for execution requests.

## Non-negotiable rules
- Separate DEMO / PAPER / LIVE environments. Default PAPER/DEMO, no LIVE trading. LLM cannot directly place, approve, bypass, retry, or modify orders. Any activation of demo execution requires a separate manual authorization after test gates.
- Do not change broker account trading toggles, enable AutoTrading, set unknown network permissions, or make high-risk infrastructure changes without explicit approval.
- Do not invent IPs or network success; fill verified values in inventory, not hard-coded repo defaults.
- Never treat simulated or replay feed as real-time broker data. Strict provenance per candle/tick, freshness, timezone UTC, session id, broker symbol mapping, real point/tick/contract specifications.
- Commands are single-use with durable idempotency and broker reconciliation. Any ambiguity => stop new orders and surface error. Disconnect/stale/error => fail closed.
- Avoid multiple writers/decision leaders unless lease and fencing are proven; begin with ONE core worker. External Redis/PG are staged migrations, not automatic changes.
- All model upgrades are proposal only until walk-forward tests, costs, OOS validation, forward demo and explicit promotion/rollback. Evaluate on grouped trades, not a single loss. Do not promise profitability.
- External 3TB Seagate disk had read/write I/O and EXT4 journal errors; DO NOT use for backup or attempt write repair. Require healthy backup + tested restore before disk migration or LVM expansion.
- No default demo passwords exposed over LAN. JWT, bridge token, passwords, secrets, SSH private keys are outside git; per-service least privilege and TLS.
- Before editing: inventory existing implementation -> characterize tests and dependencies -> create branch -> smallest compatible changes -> tests -> risk/safety review -> demo rollout -> monitor -> rollback plan -> update docs/checklist.

## Code ownership paths
- `apps/web-dashboard/`: Vue 3, charts, responsive UI; maintain existing UX behavior and APIs.
- `services/api_gateway/`: FastAPI REST/WebSocket and auth; add OpenAPI schemas, rate limiting and telemetry.
- `services/market_data/`: feed adapters, UTC timestamps, source and quality validation.
- `services/strategy_engine/`, `services/ai_forecast/`, `services/risk_engine/`: trading analytics, model-based uncertainty and veto.
- `services/execution_gateway/`, `services/bridge/`, `bridge/No7BridgeEA.mq5`, `integrations/brokers/`: order lifecycle and MT5 bridge; high-safety changes require specialized tests.
- `packages/persistence/`: existing SQLite; PostgreSQL migration only with schema/data/rollback plan.
- `integrations/no7_local_ai/`: local explanations, read-only context, never execution privileges.
- `tests/`: run before each deployment; add broker disconnect/reconnect, stale data, duplicates, fill ambiguity and ledger reconciliation tests.

## Completion criteria
Every delivered phase includes actual command outputs, installed versions, open ports, tests, security impact, rollback and a clear NOT TESTED flag for unverified parts. Never claim installation/deployment unless verified on actual host.


## Master v3 precedence (2026-11-08)
This pack supersedes *paths and role assumptions* in earlier blueprints. **Source on DEV PC: `C:\workspace\TradeAi`**. **Windows VM200 deployed runtime: `C:\app\app\No7-Ai-Trading-Pro`**. Ubuntu VM100 `/opt/no7-ai-trading-pro`. Proxmox host `192.168.1.254`. Other VM IPs are unknown until verified.
Before changing files inspect existing `TradeAi` code, history, and tests; merge AGENTS rules, do not overwrite them blindly. Follow `docs/06-DATA-CONTRACTS.md` through `docs/12-RELEASE-AND-ACCEPTANCE.md`. No live orders or automatic promotion. Dedicated Windows execution guard, one account one active executor, mandatory broker reconciliation. Preserve current FastAPI/Vue stack; add PostgreSQL later by planned migration. Do not use failed Seagate 3TB for backup.
