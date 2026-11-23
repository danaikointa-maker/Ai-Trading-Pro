# VM100 Parallel Development and Staging Handoff V1

Updated: 2026-11-22
Status: HANDOFF PLAN ONLY — no VM, Cloudflare, DNS, firewall, or trading runtime was changed.

## 1. Goal and boundaries

Run Windows development and VM100 analysis/staging at the same time while keeping one No7 AI Trading Pro repository, one API/schema contract, strict per-environment data isolation, and one authoritative execution path. This document is an operational companion to `docs/UNIFIED-MASTER-PLAN-V4.md`; work priority and completion evidence remain in `docs/UNIFIED-TASK-REGISTER-V4.md`.

Target hostname requested for VM100: `agent.youridea168.com`. It is a desired endpoint, not confirmation that its DNS record, Cloudflare Tunnel route, Access policy, certificate, or origin is configured and working.

Non-negotiable boundaries:

- No public or Cloudflare route to simulated/development port `8000`.
- Do not replace or restart the existing VM100 staging service on `18081` until its state and U05 durable position-modify parity are audited and protected.
- Never share SQLite/database files between Windows and VM100 over a network. Each environment has its own database and secrets.
- Windows-to-VM100 market publication is data-only and read-only. It must not carry broker passwords, private keys, order instructions, or position-modification commands.
- TradingView, LLM and agent inputs remain advisory. They cannot bypass the existing No7 confirmation, Risk Engine, authorization and Execution Gateway.
- Auto and Live trading remain disabled. This handoff does not authorize Demo execution, deployment, DNS edits, or Cloudflare route changes.

## 2. Split of responsibilities

| Area | Windows development PC | VM100 |
|---|---|---|
| Source | Author code, work on assigned branch/task, run local static checks and automated tests | Pull reviewed branches/commits for isolated staging; do not make untracked production edits |
| MT5 | Current user-designated Windows MT5 terminal; Demo identity and quote/spec source; optional data-only market publisher | No MT5 terminal dependency for analysis when disconnected; accepts only the authenticated market-data contract if publisher is configured |
| API/UI | Local development UI/API for implementation and simulator; use isolated local config | Staging API/UI and analytical/inference/training services, each with separate config, DB and logs |
| Trading state | Local simulator state and local test data only | VM100 staging state only; never copy account data into another account/tenant |
| Access | SSH for administration; outbound HTTPS/WebSocket client to the VM100 hostname when available | SSH admin access; loopback-bound application origin behind Cloudflare Tunnel after readiness gates |

### Source synchronization and parallel work

1. Keep one GitHub repository: `danaikointa-maker/Ai-Trading-Pro`.
2. Use a separate clone/worktree and feature branch on each machine. Do not edit the same checkout concurrently or copy project directories with OneDrive/SMB/SCP as a source-control substitute.
3. Assign each task ID to one owner in the Unified Task Register. Split tasks by file/module; shared API/schema changes require a reviewed PR before both environments consume them.
4. Windows publishes changes as a branch/PR. VM100 staging consumes a pinned reviewed commit; staging is not a second canonical branch or a source of unreviewed production code.
5. Keep `.env`, broker credentials, publisher tokens, SSH private keys, SQLite files, caches and logs out of Git and out of handoff messages. Provision each environment's secrets separately using its approved local secret mechanism.
6. A successful local test/build is not evidence of VM100 runtime readiness. Record commit SHA, exact commands/results, environment and outstanding NOT TESTED items in the task register.

## 3. Runtime profiles and ports

| Profile | Intended use | Port/binding | State |
|---|---|---|---|
| Windows local development | Developer API/UI and simulator | Port depends on the chosen local profile; prior local usage included `18000`. Keep loopback-bound. | Not a VM100 service; must use a separate DB and `.env` |
| VM100 development/simulated | Existing service observed on port `8000` | Do not expose publicly or repurpose during this handoff | Prior SSH audit identified it as simulated/development; do not touch |
| VM100 staging | Isolated API/UI target | Prior observed `127.0.0.1:18081`; verify current process and origin before use | Prior commit `06642a0`, branch `feature/u02-100pt-confirmation`; market feed stale and durable modify-intent parity with V4 unresolved |
| Public application URL | User-facing staging hostname | `https://agent.youridea168.com` through Cloudflare Tunnel, ultimately to a verified loopback-only staging origin | Not verified/configured by this task |

Do not assume the historical port/commit still runs. Before connecting or restarting anything, inspect the active listener, process owner, checkout path, branch/commit, health endpoint and database path through read-only commands. Back up relevant service configuration and DB before any separately authorized migration.

## 4. Connection contract

### Windows client to VM100

- Browser/API client: `https://agent.youridea168.com` after hostname, Access, TLS and app authentication have all been validated.
- Use the same-origin REST and WebSocket routes defined in `docs/API.md`; the VM100 API is authoritative for its own staging state.
- The Windows MT5 publisher may send only the approved quote/rate/spec snapshot to its dedicated market-data endpoint, with a dedicated rotatable service token. Validate account identity locally and publish Demo data only. Never place the token in Vue code, URLs, screenshots, terminal history or logs.
- On stale/missing publisher data, show stale/unavailable status and withhold the snapshot. Do not substitute a stale tick or simulator balance while labeling it a connected broker account.

### VM100 without Windows online

VM100 may perform offline research, model training and historical analysis using permitted stored/public datasets and its own isolated research store. It must label data source and age, and must not imply that a quote is live. It cannot obtain current private MT5 account balance, positions, orders or fresh broker ticks while the Windows MT5 publisher is offline. No order/modify command can be queued for later execution by an unavailable PC bridge.

### Account/data isolation

Every request and persisted row involving account state must retain tenant, user, broker-account identity and source provenance. Do not aggregate simulator and broker balances/history. Selecting or deleting an account must not leak rows from another account or the simulator. VM100 analysis can consume only the explicitly mapped, authorized data scope; publisher data is not authorization to trade.

## 5. Cloudflare Tunnel target and security gates

Cloudflare Tunnel normally publishes a hostname by routing it to a local service URL; therefore the intended design is hostname → Tunnel → loopback-only VM100 staging origin. The service URL, active tunnel, DNS, Access application/policy and local port must be verified on VM100/Cloudflare before use. Official references: [Tunnel setup](https://developers.cloudflare.com/tunnel/get-started/), [Tunnel routing concepts](https://developers.cloudflare.com/tunnel/concepts/routing/), [published application routing](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/), [locally managed tunnel configuration](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/configuration-file/).

Target configuration (not yet applied):

```text
Hostname: agent.youridea168.com
Public scheme: HTTPS
Tunnel origin: http://127.0.0.1:<verified-staging-port>
Expected historical staging origin: http://127.0.0.1:18081 (verify; do not assume)
Forbidden origin: port 8000 and any public MT5 command/execution bridge
```

Before any route change, verify all of the following:

1. Identify the existing Cloudflare Tunnel mode/name/connector and whether it is healthy; do not create a competing tunnel blindly.
2. Confirm DNS ownership and current records for `agent.youridea168.com`; do not overwrite unrelated records.
3. Confirm the origin is the reviewed VM100 staging checkout, loopback-bound, has a health/readiness check, and has U05 persistence parity resolved.
4. Configure Cloudflare Access for intended people/service identities, plus the application's own authentication/RBAC. Access is an outer gate, not a replacement for app authorization.
5. Confirm HTTPS redirect/certificate, REST, WebSocket upgrade, body-size and timeout behavior, rate limits, and that proxy/application logs redact credentials and webhook bodies.
6. Ensure no Access bypass or public route exposes admin, debug, metrics, database, broker credential, order, or position-modification endpoints.
7. Test unauthorized/expired identity, app logout, API auth, WebSocket auth, stale feed, reconnect, service restart and rollback before inviting users.

Do not put secrets in Cloudflare hostname/path/query parameters. For machine-to-machine publisher access, use a narrowly scoped service identity/token over HTTPS with rotation and redaction. Keep the MT5 execution bridge private; Cloudflare publication of the web dashboard does not mean a trading command bridge should be published.

## 6. Ordered readiness plan

### Phase A — inventory and preserve current staging

- Read-only inventory of VM100 listeners, service manager, checkout/commit, binding, DB location, tunnel connector and logs (redact secrets).
- Confirm SSH access and backups. Inspect the staging DB schema/status without dumping account or credential contents.
- Resolve U05 durable position-modify intent/reconciliation parity before replacing the staged checkout. Preserve unresolved intent rows and single-writer behavior.

### Phase B — align code and API contract

- Choose the reviewed V4 commit and dependency lock; install into a separate release directory/virtual environment, not over the running checkout.
- Apply schema migrations with a tested backup/restore path; keep staging DB isolated from 8000 and Windows.
- Keep broker execution disabled and use simulator/read-only feed until U01 freshness, U05 parity, auth/RBAC and rollback criteria pass.
- Verify Windows and VM100 API/schema versions and same-origin REST/WebSocket contract; reject incompatible version with a clear readiness error.

### Phase C — private staging validation

- Bind the staging service to loopback; validate health, readiness, auth, tenant/account isolation, database persistence and restart recovery.
- Validate data-only Demo publisher with fresh MT5 ticks/rates/specs, symbol mapping, timestamps, stale rejection and reconnect. Until a fresh quote is received, readiness remains false and market data must be marked stale.
- Run automated and regression suites from the exact pinned commit; record evidence in the Task Register. Do not infer VM acceptance from workstation results.

### Phase D — Cloudflare hostname validation

- Only after Phases A–C and explicit operational change authorization: route `agent.youridea168.com` to the verified loopback staging service using the existing Tunnel, add Access/app-auth policy, then test TLS, WebSocket and failure paths.
- Make no route to port 8000 or any order/EA bridge. Keep a rollback command/config snapshot and verify tunnel route removal returns the hostname to the prior state.

### Phase E — separately authorized Demo acceptance

- Demo trading is outside this handoff and requires a separate explicit request, verified broker account identity, risk limits, command idempotency, execution reconciliation, emergency controls and test receipt. Live remains OFF and unauthorized.

## 7. Current evidence and blockers (as of 2026-11-22)

- Prior VM100 read-only inspection observed a separate simulated/development listener on `8000` and staging on `18081`; this is historical and requires fresh verification before operations.
- Historical staging checkout: `/home/danai/no7-ai-trading-pro-v4-staging`, commit `06642a0`, branch `feature/u02-100pt-confirmation`; feed mode `mt5_demo_publisher_stale`.
- The loopback SSH preflight previously showed `health_api=true`, `publisher_route=true`, `publisher_fresh=false`, `ready=false`. A previously provided publisher message reported tick age `45,990.2s` vs 10s max, correctly withheld as stale.
- Staging has durable `position_modify_intents` reservation/reconciliation helpers. The V4 checkout inspected so far lacks equivalent intent ledger/reconciliation behavior; U05 remains a blocker to whole-checkout staging replacement.
- Cloudflare is reported by the user as installed. The tunnel connector, route, DNS, Access policy, origin port, domain reachability and WebSocket passage have not been independently verified in this handoff.
- No install, service restart, database migration, route/DNS update, account switch, order or trade was performed.

## 8. Acceptance checklist

| Gate | Required evidence | Status |
|---|---|---|
| Source handoff | clean, pinned reviewed commit on VM100; task owner and API version recorded | NOT TESTED |
| U05 safety parity | durable reservation/reconciliation and restart/concurrency tests, actual staging DB preservation | BLOCKED / NOT TESTED |
| U01 data readiness | verified Demo identity; fresh quote/rates/specs; `publisher_fresh=true`; stale/reconnect tests | BLOCKED |
| VM staging | isolated DB, loopback bind, auth/RBAC, health/readiness, restart recovery | NOT TESTED in this handoff |
| Cloudflare | correct hostname/origin, Access+app auth, TLS and WebSocket tests, no port 8000/bridge exposure | NOT TESTED |
| User/account isolation | cross-tenant/account denial and simulator separation regressions | Must pass for relevant release |
| Trading execution | no execution authorized by this document; separately authorized Demo gate only | NOT AUTHORIZED |

## 9. Rollback outline

For any future separately approved staging/route change: retain the prior checkout, service unit/config, tunnel route and database backup; switch the hostname route back to the previous verified origin or disable the new hostname route; stop only the new staging process; restore the previous service/config and database only if migration requires it; verify health, auth and no unexpected listener. Never roll back by deleting the database or unresolved position-modify intents. Never affect the existing port 8000 service as part of this staging rollback.
