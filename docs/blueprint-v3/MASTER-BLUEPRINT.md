# No7 AI Trading Pro — Master Combined Document

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


---

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


---

# 02 — Installation Readiness / Phase Gates (operator checklist)

Status convention: `[ ]` pending; `[x]` tested pass; `[!]` blocked. A phase is DONE only if evidence exists: commands/results/screenshots, versions, acceptance gates and rollback.

## Phase 00 — Safety and baseline (DO FIRST)
- [ ] Freeze changes in TradeAi, `git status`, branch `infra/unified-v3`, record Git commit SHA and config inventory.
- [ ] Inspect `qm list`, `qm config 100/200`, `pvesm status`, `lsblk`, system logs and guest health. Preserve current VM configs.
- [ ] Confirm External Seagate is OUT OF BACKUP rotation due hardware I/O errors.
- [ ] Obtain healthy external backup, test BOTH VM backups and isolated restore; NO partition/LVM or VM disk migration before pass.
- [ ] Find and record ACTUAL Ubuntu & Windows VM IPs, DNS, gateway, OS versions, time sync.
**Gate G0:** healthy recovery path proven; machine inventory documented. Otherwise proceed only with non-destructive development/audit.

## Phase 01 — Dev PC and repo
- [ ] `git clone https://github.com/danaikointa-maker/TradeAi.git` if not already present; never overwrite existing worktree.
- [ ] Install VS Code, Git, Python compatible with requirements, Node LTS, SSH client; pin supported versions.
- [ ] Run `scripts/check-dev.ps1` and save evidence outside repo secrets.
- [ ] Create Python venv, install requirements in isolation; `python -m pytest tests -q` baseline.
- [ ] `npm ci` and `npm run build` in `apps/web-dashboard` baseline; review warnings.
- [ ] Merge this overlay's `AGENTS.md` with any local rules and document code ownership; no automatic destructive commands.
**Gate G1:** local baseline tests/build pass OR failures logged and assigned; secrets not committed.

## Phase 02 — Secure management network
- [ ] Create least-privileged Windows/Ubuntu users and SSH keys; do not reuse Proxmox root SSH for agents.
- [ ] Pin host keys; verify `ssh no7-ai`, `ssh no7-mt5` from DevPC after replacing placeholder IPs.
- [ ] DevPC management LAN/VPN only; Firewall inbound limits on both VMs.
- [ ] Configure NTP/time sync and UTC event time; check skew.
- [ ] Confirm reliable named endpoints and no IP collisions (DHCP reservation preferred).
**Gate G2:** secure connectivity + key rotation recovery tested. No public DB/MT5/Proxmox access.

## Phase 03 — Ubuntu Core
- [ ] Run read-only `scripts/check-ubuntu.sh`, inspect existing packages and Ubuntu version.
- [ ] Install only missing Python/Git/Node/toolchain; build Vue dist and install Python requirements in venv.
- [ ] Create dedicated service account and persistent `/opt/no7-ai-trading-pro` + storage outside Git; enforce permissions.
- [ ] Generate JWT secret and rotate README default Demo credentials; set `.env` OUTSIDE repo tracking.
- [ ] Run FastAPI SINGLE worker bound to localhost, test `/api/docs` and authenticated health/WS.
- [ ] Add nginx HTTPS reverse proxy and firewall/ACL; confirm 401/403 on unauthenticated endpoints and correct WS upgrade.
- [ ] SQLite initially with database backup, write concurrency limits; defer PostgreSQL until demonstrated need and safe migration.
- [ ] Run existing pytest and smoke; test restart/reboot services.
**Gate G3:** dashboard + API healthy on authenticated TLS; no default credentials; one decision leader.

## Phase 04 — Windows MT5 Demo
- [ ] Run `scripts/check-windows.ps1`, verify supported Windows build and MT5/MetaEditor install.
- [ ] Connect to Connext DEMO, confirm broker account ID/server/type and symbol list; no live account.
- [ ] Compile `bridge/No7BridgeEA.mq5` in MetaEditor; capture compile result; do NOT claim compile until verified.
- [ ] Validate WebRequest trusted URL to Ubuntu HTTPS endpoint and certificate chain; private LAN only.
- [ ] Provision per-demo-account bridge credential; verify server-side account mapping and token revocation.
- [ ] Start read-only quote/position snapshot bridge first with execution DISABLED; validate account name/source/timestamps/spec.
**Gate G4:** live BROKER DATA labeled correctly, no orders placed, MT5 restarts/reconnects cleanly.

## Phase 05 — Unified contracts + fail-closed integration
- [ ] Version and test bridge protocol `/api/bridge/register` + `/api/bridge/poll` in current code.
- [ ] Include correlation/event IDs, UTC, broker/account/symbol, TTL, price point/tick/step, source, data quality.
- [ ] Test disconnect/stale feed, duplicate commands, lost ACK, server/terminal restart, unknown fill and account mismatch.
- [ ] Validate hard broker-side SL/TP, margin/stops/fill constraints using DEMO and manual approval.
- [ ] Confirm market data pipeline -> quant -> risk -> UI behaves without simulator fallback under BROKER mode.
**Gate G5:** NO new order on fault, no duplicates, ledger and broker reconcile.

## Phase 06 — Visual trader desktop
- [ ] Preserve existing Vue dashboard screens, implement consistent dark trading design tokens and layout.
- [ ] Prominent feed mode + broker + market status, stale data/connection, account demo lock, approved-model status.
- [ ] Chart multi-timeframe/confirmed zones and trade plan overlay; no fictional indicators/levels.
- [ ] Responsive mobile and desktop, 1080p and 1440p usability, keyboard/wcag, visual regression.
**Gate G6:** test with demo broker and simulated feed badges; risk veto always clear.

## Phase 07 — AI Agent + research loop
- [ ] Measure VM100 CPU/memory latency before enabling Ollama; trial qwen3:1.7b low-priority one worker.
- [ ] Restrict LLM to READ-only analytics context and explanation tools; no order/approve/admin tools.
- [ ] Store loss review event with fills/costs/snapshot/model/risk context.
- [ ] Generate evidence-based postmortems, risk-control proposals, and reproducible candidate training runs.
- [ ] Walk-forward/out-of-sample/forward DEMO benchmark vs champion incl. drawdown/fees, then manual promotion+rollback.
- [ ] Alert on drift and model confidence degradation; no automatic tune based on single losses.
**Gate G7:** repeatable candidate study and postmortem, no self-modifying trading policy.

## Phase 08 — Reliability / production readiness
- [ ] Add health and error dashboards for VM100 API/DB/WS/Agent, VM200 EA/account/quotes and Proxmox/backup.
- [ ] Implement structured logs, alerts to selected channels, deterministic recovery and incident runbook.
- [ ] Run load/soak, disk-full, restart, network partition, broker outage and recover-with-open-position tests.
- [ ] Verify backup and restore post-change, rollback code and model registry.
- [ ] Review Thai legal/broker/regulatory suitability before any real account. Real execution remains DISABLED until explicit independent authorization.
**Gate G8:** audited DEMO system stable and recoverable; no implied profitability guarantee.

## Hard-stop criteria
Loss of broker connectivity, stale quotes, invalid symbol specs, unknown account, time skew, missing mandatory stop, queue ambiguity, database errors, model unvalidated, SLA latency breach or repeated disk I/O error => disable new order issuance, show red incident, preserve broker-side stops, reconcile before restart.


## Phase 09 — Multi-user, Trade Journal and report sharing (after G5; sandbox-first)
- [ ] Define PostgreSQL migration plan with immutable trade/deal mapping, account/tenant ownership and tested RLS; keep V1 SQLite until parity complete.
- [ ] Implement tenant-scoped API authorization, signed image URLs, per-user portfolio preferences, MT5 account binding and cross-tenant penetration tests.
- [ ] Capture entry/exit evidence and screenshots (automatic when source exists, manual otherwise), costs, broker deal IDs, partial closes and timezones.
- [ ] Reconcile user daily/monthly Win/Loss/P&L with verified MT5 deals; label points separately from account currency and R-multiple.
- [ ] Implement privacy preview; export text/PNG/PDF and optional opted-in messaging to Telegram/LINE/Discord.
**Gate G9:** individual data always isolated, reports reconcile, share preview redaction verified.

## Phase 10 — Privacy-preserving global research (must have consent)
- [ ] Opt-in consent/version/purpose and withdrawal; restrict shared intelligence to minimized aggregates/features, not raw private records.
- [ ] Data provenance, retention limits, re-identification risk review, minimum cohorts; privacy review in applicable jurisdictions.
- [ ] Track shared aggregate quality by symbol/broker/regime, validate improvements independently with controlled holdout.
**Gate G10:** individual accounts/trades are not exposed via API, dashboard, exports, or model artifacts; consent lifecycle tested.

## Phase 11 — Professional Trading UI / Agent Lab
- [ ] Unified trading design system, responsive chart and clearly labeled feed and account state.
- [ ] Agent Center (jobs/status/log/approval); Backtest Lab with datasets/costs/reproducibility and champion/challenger; trade forensic detail and privacy-first report share.
- [ ] A11y, 1080p/1440p/mobile, performance budget, dark/light optional, visual regression and Thai/English typography.
**Gate G11:** screenshot test baseline, operations UX test, risk controls accessible, no simulated data disguised as market.

## Phase 12 — Professional release gates (DEMO only)
- [ ] Audit P0 incident paths, loss of network, wrong account, dual executor, unknown order, power recovery, partial fill, stop management.
- [ ] Backups tested and documented including healthy off-host media; monitoring and on-call notifications; restore recovery exercise.
- [ ] Review CI results, security checklist, signed release artifact, staged deployment, rollback, model provenance and permissions.
- [ ] Sign off evidence template in `docs/12-RELEASE-AND-ACCEPTANCE.md`; do not enable live trading without separate legal/business/security authorization.
**Gate G12:** DEMO accepted with explicit limits, known issues, rollback and owner sign-off.


---

# 03 — Hybrid Self-Hosted AI, Learning and Losing-Trade Improvement

## Roles (all on VM100, separated and throttled)
1. Market Context: existing deterministic features, multi-timeframe trend/BOS/CHoCH/confirmed S/R; never use a single LLM image judgment as trading truth.
2. Forecast: existing LightGBM calibrated probabilities/quantile band; optional XGBoost comparator; no automatic deployment.
3. Strategy Research: test candidate rule changes offline against frozen dataset snapshots, net of fees/spread/slippage/swap.
4. Trade Review: post-close reason codes and adverse/favorable excursion: entry timing, SL placement, setup quality, slippage, spread, time-to-fill, news, market regime, model uncertainty and operational failure.
5. Trading Copilot (Ollama small Qwen3 1.7b then 4b if CPU headroom): Thai-language explanation, hypothesis generation, human-readable postmortem, notifications; strictly read-only tools/data.
6. Risk Supervisor: code/rule-driven safety, cannot be overridden by LLM and must not change limits automatically.
7. Ops Agent: metrics/anomaly summarization, incident drafts and recovery suggestions; manual approval for VM/Network/system changes.

## Training vs serving
- FAST PATH: MT5 -> verified tick -> features -> approved frozen model -> deterministic strategy/risk -> bridge, with bounded latency and only CPU-appropriate operations.
- SLOW PATH: closed trades -> replay bundle -> loss taxonomy -> hypothesis -> train candidate -> walk-forward/OOS and paper shadow -> model registry candidate -> manual review -> promotion -> monitored rollback.
- Model IDs are content hashes. Save dataset snapshot, train window, calibration window, timezone, fee assumptions, broker spec revision, git commit, pipeline version, metrics by regime, seed and full audit.
- Use n>=appropriate sample before inference; stratify by symbol/regime/session; multiple-comparison checks and untouched holdout, not 1–3 losing positions.
- Compare baseline and champion: expectancy, win rate AND payoff ratio, net profit factor, max drawdown, Brier, calibration, coverage, tail risk, trade frequency and confidence intervals; monitor drift.
- Generate proposals, never immediate live change. Promote only after walk-forward, OOS, forward DEMO and manual signoff. Roll back on drift or operational issues.
- No guarantee to win next trade. Correct output may be NO TRADE.

## Loss-review event sample (concept, add schema after code audit)
```json
{"event_type":"trade.closed.v1","event_id":"uuid","ts_utc":"...","account_mode":"demo","broker_id":"connext-demo","symbol":"XAUUSD","trade_ticket":"...","signal_id":"...","model_version":"...","setup":"breakout_retest","regime":"range","entry_price":0,"exit_price":0,"spread_points":0,"slippage_points":0,"net_r":-1,"mae_points":0,"mfe_points":0,"risk_checks":[],"data_source":"broker","quality":"verified"}
```
Loss label must not be simplistic. Distinguish `strategy_error`, `normal_statistical_loss`, `execution_cost`, `data_quality`, `operational_failure`, `manual_override`, and `unknown` based on evidence. Normal stopouts do not prove strategy failure.

## Host resource policy
- VM100 16GiB: OS/page cache 3–4GiB, core/API/ML inference 4–5GiB, DB/Redis optional 2–3GiB, research/LLM MAX ~3GiB (test actual model usage), reserve 2GiB. Do not run 4b model concurrently with heavy ML training.
- VM200 8GiB: prioritize MT5, bridge, antivirus, OS; no LLM/quant trainer.
- Machine CPU likely limited; pin worker counts (start 1 inference/1 training when idle), lower process priority, pause research on core latency, staleness or memory-pressure alarm.
- Choose existing Ollama integration; CPU-only qwen3:1.7b first. LLM remains disabled if agent response time/memory unacceptable. Avoid cloud dependency for safety path.


---

# 04 — Professional Trader Dashboard UX Specification

## Design language
Modern institutional trading terminal: controlled dark palette, high contrast data density, clear typography (Thai/English), responsive 1440p/1080p/tablet/mobile, keyboard navigation, non-color indicators for BUY/SELL, WCAG contrast. Avoid neon overload, animated background, distracting particle FX, or excessive cards. Show data provenance, timestamps, market/session status prominently.

## Desktop layout
Top: symbol/account selector, SIMULATED/REPLAY/BROKER flag, demo/live lock, connection state, latency, London/New York session, UTC/Bangkok clocks, market status.
Left: watchlist symbols/markets and multi-timeframe trend matrix.
Center (largest): price chart with candles, volume, VWAP, EMA, confirmed/candidate S/R, BOS/CHoCH, entry/SL/TP, adjustable risk-reward overlay; synchronized crosshair and broker data freshness.
Right: AI Forecast scenario ranges (P10/P50/P90 with calibration status), strategy checklist, confidence vs heuristic score explicit, risk veto reasons, proposed plan only, human approval.
Bottom: open positions, orders, deals, journal, event logs, bridge health, unresolved incidents, paper/demo P&L and execution receipts.

## Pages (retain existing 10-page Vue routing)
- Terminal: trading center, live chart and risk overview.
- Forecast: time horizons, scenario fan, calibration and OOS model validity.
- Zones: 3+ confirmed levels if supported by evidence; no invented levels.
- Trades: open/closed orders, fills, realized cost, partials, reconciliation.
- Risk: immutable veto reason list, exposure heatmaps, kill switch, broker spec.
- Backtest: frozen dataset, OOS walk-forward, costs and robustness.
- Journal: complete trade lifecycle + AI postmortem and proposed experiments.
- Brokers: broker source, symbol specs, connection status, account mode.
- System: Proxmox/VM health, API/EA heartbeat, queue/DB, backup restore age, disk errors.
- Add Agent Lab route later: candidate models/champion/shadow comparison, review queue, promotions.

## Critical safety UX
Show large persistent DEMO/PAPER/LIVE state, source badge, stale quotes, model unvalidated status, news lockout, risk veto and disconnect status. Never show green 'connected' when quote is stale. Default CTA is 'Review Plan' (not one-click BUY). Trading buttons remain disabled until account identity, kill switch and risk gate pass and operator approval is recorded.

## Implementation guidance
Extend `apps/web-dashboard/src/components` and existing `src/views`, keep API compatibility. Design tokens CSS custom properties, central Store, typed contracts as desired, error/empty/loading states, mobile constraints. Use synthetic preview data with SIMULATED badge and make it impossible to misidentify as real quotes.


---

# 05 — Security / Operations / Disaster Recovery

## Network access
Proxmox 192.168.1.254:8006 and :22 only from trusted management VLAN/VPN/DevPC, MFA for admin UI. Ubuntu SSH 22 from DevPC, HTTPS 443 from allowed clients/WinMT5; API localhost behind nginx TLS. Windows SSH 22 from DevPC VPN/LAN for admin, outbound HTTPS 443 to Ubuntu and broker connection; inbound trading APIs forbidden. PostgreSQL/Redis localhost or private only.

## Security gates
- Rotate README default demo password and JWT secret before binding API to LAN; no plaintext secrets in Git, screenshots or logs.
- Bridge account token distinct from user tokens; short-lived/scope demo, rotation procedure and revocation. TLS certificate trust established in Windows/MT5; no `verify=False`.
- MT5 EA WebRequest URL allowlist; avoid enabling Python auto trading in first read-only stage; enable demo EA autotrading only after signed review and kill-switch verification.
- Windows service runs under dedicated standard user; no local admin account needed for MT5 runtime.
- Developer SSH key with passphrase, individual identities, least-privileged sudo, no root AI automation.
- No automatic retry of uncertain orders. On backend reboot reconcile broker state before new orders.

## Backup
- STOP: existing Seagate 3TB ext4 encountered `Medium Error`, `Hardware Error`, aborted journal, and remount read-only. Not a viable backup target.
- Arrange healthy external drive/NAS/Proxmox Backup Server; back up both VMs, database, model registry, secrets escrow and Git. Test restoring VM to isolated network before SSD/LVM edits. Use a second offsite copy.
- Record RPO/RTO targets and rotate daily/weekly backups; verify last successful RESTORE, not just file existence.

## Monitoring
Alert on broker/bridge disconnect, quotes > freshness limit, no ack, ambiguous order, risk engine disabled, wrong account, JWT failures, DB pressure, CPU>85% sustained, RAM pressure, disk SMART errors, backup overdue and clock skew. Central correlation_id links MT5 command to API, risk decision, DB ledger and UI.

## Safe recovery
1. Halt new execution (fail closed); do not cancel/alter broker-side hard stops blindly.
2. Snapshot logs and affected event IDs. Verify current broker positions and pending orders directly at MT5.
3. Repair connectivity only after identifying root cause; reconcile ledger against broker; require manual resolution for discrepancies.
4. Resume read-only/paper first; turn on demo execution only via explicit approved runbook.


---

# Contract-first integration & order state

## Common API conventions
- Version prefix `/api/v1` for **new endpoints**; retain existing `/api/*` via compatibility adapters, never break dashboard abruptly.
- OpenAPI with generated Pydantic schemas/types, strict validation and contract tests; JSON fields snake_case, UTF-8; IDs UUIDv7/UUID4 and stable correlation IDs; documented semantic versions.
- Timestamp: ISO8601 UTC, exchange timestamp + receive timestamp + latency; client-display timezone independently.
- Money Decimal / exact currency, quantity Decimal, points numeric with **broker-provided symbol info**; do not conflate net P/L with price points.
- Every record includes `tenant_id`, `account_id` when applicable, `symbol`, `broker`, `event_id`, `correlation_id`, `schema_version`, `ingest_ts`.

## Messages / transport
- Windows -> Ubuntu: authenticated HTTPS outbound (private network/VPN), with per-account scoped short-rotation credentials/mTLS; batching, backpressure, dedup, acknowledgements; tolerate short outages with bounded local spool.
- Ubuntu -> Windows: Windows makes outbound authenticated poll/long poll for **approved DEMO order intents**, never open unauthenticated order listener on Windows. Separate market data and command credentials.
- Candidate endpoints (adapt existing bridge instead of rebuilding): `/api/v1/bridge/heartbeat`, `/api/v1/market/batch`, `/api/v1/execution/approved`, `/api/v1/execution/receipts`, `/api/v1/execution/reconcile`.
- Retry backoff with jitter; stale/expired commands discarded; persist state and idempotency keys. `HTTP 200` never equals broker fill.

## Order state machine
`CREATED -> RISK_REJECTED | APPROVED -> CLAIMED -> SENT -> ACKNOWLEDGED -> PARTIALLY_FILLED | FILLED | REJECTED | UNKNOWN -> RECONCILED`.
- Maintain append-only order event ledger and a current projection; dedupe by `(account_id, intent_id)`, unique broker ticket/deal as available.
- UNKNOWN **blocks new orders** on that account until reconciliation with MT5 orders, deals, positions and appropriate broker history.
- No blind resend after network timeout. Exactly-once broker execution cannot be promised; achieve at-most-once intent dispatch where feasible and reconcile externally.
- Windows side Execution Guard independently rechecks account type demo, order age, symbol, trading sessions, volume/step, margin, SL/TP, max spread/slippage, duplicate, kill switch.
- Kill switch = prevent new risk, not blindly close positions; risk-reducing close requires explicit documented exception path.
- One active executor/terminal owner per account with lease fencing and restart recovery; no concurrent EA + Python order send for same account without arbitration.

## Market data quality
- Dedup ticks, monotonic time checks, late events, stale feeds, missing bars, symbol suffix/digits, quote status, outlier flags, session metadata; health-status `LIVE`, `SIMULATED`, `REPLAY`, `STALE`, `DISCONNECTED` visible in UI.
- Record dataset manifest + checksum + broker provenance + corporate actions for stocks where applicable; never blend paper/simulated/real records silently.


---

# Multi-user privacy and shared learning

## Separation model
- PostgreSQL target schema: `users`, `tenants`, `memberships`, `roles`, `broker_accounts`, `strategies`, `trade_intents`, `orders`, `deals`, `trades`, `trade_images`, `reports`, `model_versions`, `agent_jobs`, `consents`, `pooled_features`, `audit_events`.
- Define tenant/account ownership for all data; service-role permissions separate from end users. API authorization on every object; DB Row-Level Security **with tests** (admin/service bypass must be explicitly reviewed); signed expiring access for images.
- Encrypt broker account secrets with managed encryption keys outside Git; audit reads/deletes/exports. Never expose other users' private balances, screenshots, tickets, names, or strategies.

## Shared intelligence — opt-in
- Personal records remain private. Central training only uses consented, minimal feature vectors (market regime, normalized entry/exit setup, R multiple, costs, timestamp buckets) after privacy review, aggregation and thresholding.
- Pseudonymization by deleting names is NOT guaranteed anonymity; maintain linkage only in separately protected consent service where needed for withdrawal.
- Risk of re-identification exists with sparse/highly specific trade data; minimum cohort size, generalization, access limits, retention, audit and privacy testing are required. Consider privacy-preserving aggregate statistics or differential privacy when feasible.
- Dataset/Model provenance logs include allowed use/purpose, dataset version and consent scope; implement withdrawal/retention policy and handle trained models per policy/legal review.

## Multi-account execution
- Distinct MT5 terminal instance and controlled executor for each **actively connected account**, with account-scoped bridge key. A single Windows VM200 with 8GB RAM and 2 vCPU is a small pilot, NOT enough to promise unlimited concurrent traders. Plan capacity tests and scale to additional isolated Windows workers when load justifies it.
- User risk limits must never be shared. Global model can be reused for general signals but decisions incorporate each account's broker contract, margin and risk policy.

## Compliance
- Define legal basis and documented user consent for learning/data retention/sharing; review applicable Thai PDPA and financial platform/broker requirements with specialists before multi-user public deployment or live order routing.


---

# Personal Trade Journal, Screenshot and Share Studio

## Capture per closed trade
- Identity scope: tenant + user + account + portfolio, broker account alias; do not leak true account/ticket in shares.
- IDs: internal trade id, broker order/deal tickets encrypted or protected, open/close timestamps (UTC + user-local display), symbol and deal side.
- Exact price/lot, broker digits/point/tick size, gross P/L, commissions, swap, realized net in account currency, points, R-multiple, MAE/MFE, drawdown, SL/TP, exit reason, strategy/model/risk version and market regime.
- Partial fills/partial closes: aggregate by canonical position lifecycle, avoid counting one position as many wins in daily metrics without explicit method.
- Evidence: before-entry snapshot, at-entry, exit and optional manually uploaded screenshot; source/image checksum, metadata, retention and privacy controls; no assumption broker provides chart images automatically.
- Journal: manual notes, AI hypothesis, test result and whether lesson was validated; mark guesses as such.

## Daily / monthly report
- Per-user calendar + selected portfolio/account strategy, timezone `Asia/Bangkok` default; grouping by **close date**; show trade count, wins, losses, breakeven, net points per symbol, money P/L after cost, win rate, profit factor (handle divide-by-zero), expectancy, avg R, max drawdown and data coverage.
- Import the user-supplied 'Lady Gold October 2026' as **example only**, not verified broker deals. Ensure `cut -100` is parsed as a realized outcome and point/monetary units annotated.
- Each day shows entry rows `SELL +2000 pt`/`BUY -1000 pt`, source broker, local time, screenshot links. Aggregates must reconcile with broker Deals.

## Sharing
- Preview -> redact -> explicit user confirmation -> text/PNG/PDF -> optional Telegram/LINE/Discord webhook/message. Never auto-publish other users' stats, P/L, account identity, private notes or screenshots.
- Report watermark: `DEMO`, `PAPER`, or `LIVE`; date and period, timezone, unit (points vs currency), portfolio alias, metrics definitions and whether verified against broker.
- Provide copy-to-clipboard message and downloadable image/PDF. Record share history and revocation where supported; platform copies may not be retractable.
- Accessibility: mobile legibility, readable Thai/EN, distinct symbols besides red/green, selectable dark/light themes.

## Suggested report text
📍 สรุปสถิติ Lady Gold — ตุลาคม 2026 (ตัวอย่าง ไม่ใช่บัญชีจริง)
📍 05/10/2026: ✅ SELL +2,000 จุด | ⭕ SELL −1,000 จุด | ⭕ BUY −1,000 จุด | ✅ SELL +2,000 จุด
📍 22/10/2026: ✅ SELL +2,000 จุด × 3
หมายเหตุ: เป็น "จุด" (points), ไม่ใช่กำไรเงิน; ต้นทุนและข้อมูลบัญชีจริงต้องตรวจจาก MT5 ก่อนสรุปยอด


---

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


---

# Observability, reliability and recovery

## Service Level Indicators (proposed pilot targets, not guarantees)
- API authenticated health; MT5 terminal heartbeat 2–5 sec; quote freshness and bid/ask age per symbol; broker reconnect detection; outbound bridge lag; order intent queue depth; unknown-order count; reconcile delay; error/dead-letter queue size; DB latency; disk free; RAM/CPU; cron/worker health.
- Starter availability target 99.5% **during defined supported hours**; record downtime from end-to-end probe, not merely process alive.
- RPO target <=15min with verified archiving/backup design, RTO 1–4h if provisioned replacement hardware is ready; a single physical 7040 is not HA.
- Incident severity: P0 unknown order, execution duplicates, wrong account, severe data contamination; P1 stale market, backup failure, DB slow; P2 degraded report/AI explanations.

## Fail-safe rules
- Loss of MT5 bridge or stale quote -> `NO_NEW_ORDERS`, alarm, existing broker-native SL/TP maintained where possible.
- Ambiguous order send -> `UNKNOWN`, block fresh intents until history reconciliation, human escalation if uncertain.
- Model invalid/dataset corrupt -> pause model signal, serve baseline/WAIT as explicitly labeled, never hallucinate price.
- Restart recovery -> durable event replay + reconcile, never assume queued order not sent.
- Auto-restart on CPU overload is not a substitute for root-cause and memory pressure limits; critical Windows broker worker prioritized.

## Backups
- External Seagate 3TB (`sdd1`, WWN `0x5000c5005cfe8624`) yielded `Hardware Error`, `Medium Error`, failed ext4 superblock writes and readonly remount: **quarantine, don't use**. SMART PASSED not sufficient.
- Separate replacement external backup, off-host/offline copy, encrypted DB backup + VM backup; sample restore verification and documented checksum.
- Do not repartition `sda`, `sdb`, `sdc` or move Windows VM until verified backups and recovery procedures.
- Proxmox snapshots are not a substitute for an off-host backup. Protect broker secrets independently from backups and restrict restore access.

## Windows/Ubuntu operations
- Use SSH keys, low privilege accounts and audit; no blanket root automation. NTP clock sync both VMs; trusted certificates; monitor firewall and EDR.
- Config-as-code checked in without secrets; env secret files on hosts only; rotate bridge keys, API tokens and incident-exposed credentials.
- UPS and safe shutdown for host power cuts; check disk smart/self-tests and CPU thermals.


---

# Test and model validation strategy

## Technical tests (enforced CI gates)
- Unit: precision/point math, risk guards, position state, timezone-close-date, partial fills, file access, RBAC, consent withdrawal.
- Contracts: OpenAPI/Pydantic compatibility from existing `/api/*` to new `/api/v1`, bad schema rejects, idempotency, authz and expiry.
- Integration: real Demo broker specs, duplicate event receipt, restart while order UNKNOWN, 1–10 minute disconnect, wrong account, stale quote, weekend/session gaps, negative balance risk, signed screenshot URLs.
- E2E: DEV -> staging Ubuntu -> Windows Demo -> broker response -> journal/report match, clean rollback.
- Load/security: simultaneous users, per-account broker terminal quotas, rate limit, SQL/RLS isolation, secrets, CSRF, WebSocket auth, backup recovery.

## Quant/AI research quality gates
- Dataset exact snapshots/checksums; no simulated-replay mixing; trading sessions, spread/commission/slippage/swap/symbol margin rules.
- No leakage: feature timestamp <= decision cutoff, unavailable future bars excluded, walk-forward purging/embargo when label horizon overlaps, separate OOS holdout, threshold pre-registration.
- Compare champion vs candidate on realistic net expectancy and drawdown with confidence intervals / uncertainty, trade count, calibration, subgroup regimes, time periods, Monte Carlo/stress variations.
- Correct for repeated strategy search/multiple hypothesis testing and nonstationarity; paper/shadow comparison; never optimize solely win rate.
- Model registry: immutable features/data/model/code hashes, owner, purpose, quality gate, expiry, sign-off; rollback champion if drift/regime shift.
- Loss review agent outputs evidence, probable cause, alternative **hypothesis**, and validation plan; never claim next trade win is guaranteed.

## Acceptance gates
- P0: no duplicate live broker order from same intent even across restart, or explicit UNKNOWN halt and reconciliation; risk veto independent; signed authenticated API; no cross-user reads; verified restore.
- P1: chart feed state accurate, journal totals exactly reconcile to broker history, reports units labeled, experiment rerun reproducible, demo broker contract specs respected.
- Evidence must include commands, versions, logs with secrets redacted, pass/fail, issue tracking and rollback procedure.


---

# Release acceptance record / sign-off template

## Change request
- Date / engineer / approved reviewer:
- Git commit / feature branch / release tag:
- Scope and impacted VM(s):
- Backup ID / last successful restore test:
- Before-state observations and baseline test results:
- Security and risk review:

## Quality gate evidence
| Gate | Status (PASS/FAIL/BLOCKED) | Evidence path | Approver |
|---|---|---|---|
| Python unit/contract suite | | | |
| Vue build + accessibility smoke | | | |
| Ubuntu authenticated health / mTLS | | | |
| Windows MT5 Demo symbol/account check | | | |
| Bridge disconnect/reconnect | | | |
| Duplicate order / unknown reconciliation | | | |
| Risk veto / kill switch | | | |
| User isolation + signed image URLs | | | |
| Journal totals to broker deal parity | | | |
| Backup and sample restore | | | |
| Rollback dry-run | | | |

## Rollout / rollback
- Rollout: build immutable artifact, stage, test, operator approval, deploy, smoke, observe. No changes to production VM storage without separate approval.
- Rollback: stop/new-order block, revert release symlink/artifact and schema via tested backup/reverse migration, reconcile MT5, restore validated DB if needed, post-incident audit.
- Release statuses: DEVELOPMENT -> STAGING -> DEMO_ACCEPTED -> LIVE_REVIEW_REQUIRED. **No automatic promotion to live.**
