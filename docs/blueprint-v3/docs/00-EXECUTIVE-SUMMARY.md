# Executive Summary — Unified v3

## System promise
A robust, auditable **AI-assisted trading research and DEMO execution platform**, not a system guaranteeing profit. The assistant analyses markets, evaluates strategies, documents wins/losses, and recommends changes, subject to risk veto and evidence-based release gates.

## One architecture, three roles
1. Dev PC `C:\workspace\TradeAi`: edit/review source, develop/tests, Git/CI, SSH deploy. No broker secrets in repository.
2. Ubuntu VM100 `/opt/no7-ai-trading-pro`: Vue+FastAPI product, research services, quant, models, database, queue, user data/journal/reporting, AI agent supervisor.
3. Windows VM200 `C:\app\app\No7-Ai-Trading-Pro`: MT5 Connext Demo, compiled EA and/or scoped Python read-only connector, exclusive execution guard and broker reconciliation.
Proxmox host `192.168.1.254` provides virtualization and storage only. VM addresses unconfirmed until observed.

## Core engineering priorities
- P0: verified backup/restore, fail-closed broker gateway, independent risk checks, order idempotency and reconciliation, data quality/staleness, multi-user isolation.
- P1: realistic backtest, traceable trade journal, scheduled agent research, champion/challenger, drift, privacy-preserving shared learning, polished UI.
- P2: scalable broker workers, HA/multi-host, deeper analytics, opt-in community reporting.

## Reality check
Existing README may describe features as implemented but GitHub code presence is not operational acceptance. Audit actual commits, run tests and demo MT5 end-to-end; do not assume live market readiness. A single 7040 cannot provide true HA; keep heavy LLM/training low priority. 500–1000 MT5 points is not universally equal to a fixed price or cash return.

## Golden path
DEV SOURCE -> tested release artifact -> Ubuntu API + research -> secure authenticated outbound polling by Windows MT5 -> broker receipt -> immutable events -> journal -> supervised research -> experimental model -> independently reviewed release.
