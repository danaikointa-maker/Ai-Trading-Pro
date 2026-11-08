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
