# No7 AI Trading Pro — Professional Master Blueprint v3

**Baseline date:** 2026-11-08 | **Mode:** DEMO-first, fail-closed | **Status:** design/install pack, NOT deployed or verified on VMs.

## Source of truth
- Existing repository: https://github.com/danaikointa-maker/TradeAi, branch `main`; do not scaffold a replacement.
- **Dev PC source:** `C:\workspace\TradeAi` (Git workspace and VS Code).
- **Windows VM 200 runtime:** `C:\app\app\No7-Ai-Trading-Pro` (MT5 bridge/EA release, not full app).
- **Ubuntu VM 100 runtime:** `/opt/no7-ai-trading-pro` (FastAPI, Vue build, services, DB, AI workers).
- **Proxmox host:** `192.168.1.254`, hypervisor only. IPs for VMs MUST be discovered and entered in the uncommitted inventory.

## First actions (no changes on servers)
1. Read `AGENTS.md` and `docs/00-EXECUTIVE-SUMMARY.md` through `docs/12-RELEASE-AND-ACCEPTANCE.md`.
2. Snapshot/commit source changes, work on `infra/unified-v3` feature branch. Before copying, merge with any existing AGENTS.md; do not overwrite app files.
3. Run read-only audits; capture OS, IP, VM state, storage, backup, MT5 account type, Python/Node versions.
4. Check that TradeAi unit tests and Vue build work without installing destructive dependencies.
5. Complete ordered checklist in `docs/02-INSTALL-CHECKLIST.md`, log evidence in `docs/12-RELEASE-AND-ACCEPTANCE.md`.

## Repository components already observed on GitHub
- FastAPI `services/api_gateway`, Vue 3 `apps/web-dashboard`, ML `services/ai_forecast`, Strategy, Risk, Backtesting, Execution, market simulation/replay.
- `services/bridge/` server-side relay, `bridge/No7BridgeEA.mq5` MQL5 EA source, `integrations/brokers/` paper and MT5 adapters.
- SQLite initial persistence, `config/*.yaml`, `tests/`, `docs/RUNBOOK.md`.
- **Read repo limitations:** MT5 actual integration, MQL5 compile/live verification, OOS model quality, broker-specific spec and real tick data are not automatically complete.

## Contents
- `AGENTS.md`: unified AI coding / safety rules
- `docs/00-EXECUTIVE-SUMMARY.md`: overview and decisions
- `docs/01-ARCHITECTURE.md`: nodes, boundaries, direction of communications
- `docs/02-INSTALL-CHECKLIST.md`: ordered checkboxes with evidence gates
- `docs/03-AI-LEARNING.md`: agents, training / backtest controls
- `docs/04-UX-SPEC.md`: professional terminal/dashboard
- `docs/05-SECURITY-OPERATIONS.md`: risk, incident, backup
- `docs/06-DATA-CONTRACTS.md`: API / events / order state machine
- `docs/07-MULTIUSER-PRIVACY.md`: identity, RBAC, aggregate learning, consent
- `docs/08-TRADE-JOURNAL-REPORTS.md`: screenshots, private stats, share output
- `docs/09-SERVICE-AND-DEPLOY-MATRIX.md`: what runs where
- `docs/10-OBSERVABILITY-SRE.md`: metrics / runbooks / restore
- `docs/11-TESTING-AND-AI-VALIDATION.md`: scientific and technical evaluation
- `docs/12-RELEASE-AND-ACCEPTANCE.md`: evidence, approval, rollback
- `config/hosts.example.yaml`, `config/ssh_config.example`, `config/env.*.example`
- `scripts/` read-only inspection and preflight tools
- `templates/` report templates and agent work orders

## Important decisions
- Modular monolith, not uncontrolled microservice fragmentation on a 32GB RAM/CPU-only host.
- Independent safety controls plus Windows-side execution guard; **one executor per account**.
- Store UTC timestamps, render user timezone; symbol point size and money P/L separately.
- PostgreSQL target for multi-user, **migrate from SQLite only after backup and parity tests**.
- Agent research is separate from trade execution; LLM cannot place trades or auto-promote models.
- Shared learning is **opt-in and privacy-reviewed**, not raw centralization of all users' trades.
- Existing Seagate 3TB generated `Hardware Error`, `Medium Error`, ext4 abort: do not use for backup.
- Never expose default demo credentials or listen on `0.0.0.0` with unsafe auth.
