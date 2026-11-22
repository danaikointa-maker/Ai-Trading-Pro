# Windows + VM100 Work Allocation — AI Officer, TradingView and Video

Updated: 2026-11-23
Status: planning/handoff only; no VM100 services, GitHub PRs, Cloudflare routes, media tools, or trading settings were changed.

## 1. Source documents checked

- No7 AI Trading Pro GitHub `main`: [README](https://github.com/danaikointa-maker/Ai-Trading-Pro/blob/main/README.md).
- Current Windows checkout: `C:\workspace\Ai-Trading-Pro`, branch `integration/unified-tradeai`.
- Separate V4 planning worktree: `C:\workspace\Ai-Trading-Pro-unified-v4-plan`, branch `feature/tradingview-intelligence-u14-u18`; U14–U18 status below is from this worktree's dated task register and is not a production/deployment certification.
- No7 AI Dev Team GitHub branch [`docs/officer-team-founder-qa-v4-20261122`](https://github.com/danaikointa-maker/no7_ai_dev_team_plan/tree/docs/officer-team-founder-qa-v4-20261122), proposed in [PR #154](https://github.com/danaikointa-maker/no7_ai_dev_team_plan/pull/154) (open, draft, not merged).
- Ai-Video-Editor GitHub branch [`docs/ai-video-editor-master-plan-20261122`](https://github.com/danaikointa-maker/no7_ai_dev_team_plan/tree/docs/ai-video-editor-master-plan-20261122), proposed in [PR #153](https://github.com/danaikointa-maker/no7_ai_dev_team_plan/pull/153) (open, draft, not merged).

The video plan is a document module/branch in `no7_ai_dev_team_plan`, not a separate repository called `Ai-Video-Editor` in the accessible repository inventory. This corrects the earlier search result that had not yet located its draft branch.

## 2. Verified baseline vs proposed work

| Capability | Windows checkout | VM100 / shared infrastructure |
|---|---|---|
| Trading officers | `apps/web-dashboard/src/views/TradingFloor.vue` has a visible Officer Team view: Market Analyst, Strategy Officer, Risk Officer and Execution Officer. It derives statuses from the current Trading Runtime; it is UI/role presentation, not a set of autonomous independent agents. Target behavior: Manual = advisory/user sends; Semi-Auto = advisory plus explicit per-entry user confirmation; Auto = allowlisted deterministic rules may initiate an order only through the existing core execution chain, after explicit per-account Auto enable. | Officers/LLMs/webhooks never call MT5 or override confirmation, RiskEngine or ExecutionGateway. Auto remains OFF by default and Live remains separately unauthorized. No verified deployment of coordinated trading agents or Auto acceptance. |
| Dev Team connection | `docs/NO7-DEV-TEAM-READONLY-INTEGRATION.md` defines a fixture/offline read contract. It says no live request or worker/task state is connected; Keycloak and Vault PKI are not provisioned; tenant/project IDs are missing. The trading officer view cannot access dev repositories, shell, approvals or deployments. | Upstream dev platform README reports registry/RBAC/audit/operator foundation partly implemented, but worker/orchestration and login/session UI are still absent; Compose on target VM and production perimeter are unverified. |
| TradingView AI Agent Lens | U14–U18 code exists only in the separate V4 feature worktree: normalized evidence contract, disabled-by-default shadow ingress/persistence, exact match comparison and read-only panel. Not present in the current `integration/unified-tradeai` checkout by the inspected paths. | No Lens deployment verified on VM100. V4 evidence still marks public TLS/log redaction, secret manager, multi-worker rate limiting, historical replay/backtest/performance, Pine compile/Bar Replay and Paper/Demo gates NOT TESTED/BLOCKED. MT5 remains the quote/spec authority. |
| QA/QC Officer plan | Current Windows tests can run locally; no independent AI QA runtime is established by this branch. | PR #154 proposes independent QA roles, G0–G7, risk-tiered test matrices, test registry/artifacts, bounded bug fix/retest loop and human release approval. Its own PR says documentation-only, pending review; not implemented. |
| Video production | No Ai-Video-Editor production implementation was found in this checkout. The GitHub proposal assigns dashboard/preview/editor/render worker/toolchain/local media cache to Windows + VS Code, subject to machine capability checks. | The video proposal assigns API/project registry/task queue/metadata/reference intelligence/lightweight ASR to VM100; it warns against promising large video generation on CPU-only VM100. Optional GPU/cloud render worker is a separate capability/approval. No such service or tool install was verified. |
| Cloudflare | Windows browser/API client should use HTTPS only after hostname/access/app-auth validation; it does not host broker execution. | Target `agent.youridea168.com` is a planned app entrypoint only. Tunnel route, DNS, Access policy, origin, WebSocket and media/object-storage handling have not been verified. Expose UI/API only after gates; never publish port 8000 or MT5 command bridge. |

## 3. Recommended ownership split

### Windows development PC

1. Own application source authoring, local tests/builds, PR creation and local UI acceptance; use isolated feature branches/worktrees.
2. Own the current MT5 Demo terminal and the outbound data-only market publisher. Send only fresh, verified market snapshots through the scoped contract; never broker passwords or trading commands.
3. Build the browser-side surfaces: Officer Team/QA views, TradingView panel and, when approved, Video Production Studio/timeline/preview. Displays must consume persisted task/events/API state, not invented animation progress.
4. If the Video plan advances, run the first media-tool compatibility, licensing, Thai typography and short sample-render checks on Windows after reviewing tool licenses and checking CPU/GPU/disk capacity. Store user media in a private media store, not Git.
5. QA roles remain read-only and independently verify coder evidence. A coder cannot approve its own high-risk change or release.
6. Trading Officer Team lives in the Windows trader product. In Manual/Semi-Auto it advises and waits for the user; only explicit Auto mode may initiate an allowlisted, versioned rule through the existing StrategyEngine, confirmation, RiskEngine, ExecutionGateway and Windows MT5 adapter/EA. Keep per-account Auto OFF by default, with visible state, audit trail, kill switch and fail-closed behavior.

### VM100 (proposed target; deployment not verified)

1. Own the isolated API/control-plane, authentication/RBAC, project-scoped task/event persistence, analytics/reference metadata, model routing and service observability, only as those components are implemented and approved.
2. Host the TradingView evidence endpoint and read-only shadow comparison only after U14–U18 deployment gates and security review. It cannot overwrite MT5 prices/specs or enqueue execution.
3. Host future Officer Team orchestration/QA registries only after the Dev Team platform's worker/orchestration, login, tenant/project isolation, budgets and audit gates exist. Current registry alone is not a running agent team.
4. For Video, own metadata/project/job coordination and lightweight analysis. Keep raw media and render outputs in private storage with tenant/project ACLs and signed/expiring access; do not place large media in SQLite or Git.
5. Run a render worker on VM100 only after capability discovery demonstrates adequate resources. Otherwise use a separately approved Windows/GPU/cloud worker adapter; no paid generation/provider or public publishing without explicit policy approval.

### Shared contracts and operations

- One GitHub repository/source branch per project, one owner per task, and reviewed PRs for shared schemas. No direct folder sync and no shared SQLite over the network.
- Reuse current FastAPI/auth/RBAC/project registry/audit/events/dashboard and No7 trading core where appropriate; do not create a second task queue, agent runtime, risk engine, broker connector or order service.
- Dev-team task execution, QA agent actions and video rendering are different capabilities. Keep their project IDs, worker identities, budgets, artifacts and permissions isolated.
- VM100 Development/Video Officers have no broker credentials or trading command capability. Trading-related analysis from VM100 is advisory data only; Windows remains the only order execution host in this topology.
- Store event and artifact provenance: project/task/run/agent IDs, source commit, timestamps, test/report IDs, permissions and approval history. Keep secret/media content out of audit text and prompts.
- Cloudflare Tunnel is the protected web entry only. Private worker traffic can use authenticated outbound API connections; do not expose worker control, database, shell, MT5 command bridge, or raw media buckets as public ingress.

## 4. Dependency-ordered phases

These are cross-project handoff phases. TradingView execution scope remains tracked only by V4 U14–U18; Dev Team/QA and Video implementation scope remains tracked by their own approved backlog/PR. Do not copy these phases as a competing task register.

Trading Officer entry modes and the VM100 boundary are defined in [`WINDOWS-TRADING-INTERFACE-CONTRACT.md`](WINDOWS-TRADING-INTERFACE-CONTRACT.md). VM100-side work should follow this local interface contract; Windows-only UI details are maintained separately in the full repository.

| Phase | Windows deliverable | VM100 deliverable | Exit gate |
|---|---|---|---|
| A. Baseline and ownership | Record current branch/commit, dirty tree, local test commands and Windows MT5 host boundaries | Read-only inventory of VM, ports, checkout/commit, DB, Cloudflare connector and backup/restore state | No changes to runtime; agree repository, branch/file ownership and ADRs |
| B. Shared platform contract | UI event consumers, offline contract fixtures, auth client design | Versioned APIs/schemas for project/task/run/event/artifact and tenant-scoped identity | Idempotency, RBAC isolation, audit, budgets and compatibility tests; no agent or media API duplication |
| C. QA and TradingView shadow | Run local contract/security/regression checks; visual review; never merge external scores into No7 signal | Deploy QA registry and Lens shadow routes only after security review; preserve U05 position-modify behavior | QA independence; Lens remains disabled/read-only; exact timestamps/provenance; fresh MT5 quote required for trading decisions |
| D. Officer workflow | Show real persisted task/QA states in dashboard; animation is visualization | Implement approved scheduler/workers/events, bounded retries, approvals, audit and artifact metadata | Phase 3 orchestration and Phase 4 events from Dev Team plan; worker crash/replay/idempotency tests |
| E. Video pilot | Isolated media cache/toolchain, rights-cleared sample, editable timeline and short preview with Thai text/audio checks | Project/media metadata, job coordination, access control, storage integration and lightweight analysis | PR #153 reviewed/merged or explicitly approved; license/rights/tool versions approved; no public publishing or unapproved spend |
| F. Integration acceptance | UI role/accessibility, video preview and dashboard/browser acceptance; Demo publisher only with fresh authorized Demo data | Staging auth/TLS/Cloudflare/WebSocket/load/restore and service recovery evidence | Cloudflare route is explicitly approved and points to loopback UI/API origin; test rollback. No Live trading. |

## 5. Immediate statuses / blockers

- Current Windows branch has a Trading Floor officer display, but the dev-team connector is fixture-only. It does not prove two live coordinated agent teams.
- The actual Founder-inspired QA/QC document is in open draft PR #154, not merged into `main`; it proposes policy/architecture, not installed workers.
- Ai-Video-Editor is in open draft PR #153, not merged; document status is planned/not implemented. No media tool installation or render evidence exists.
- U14–U18 TradingView work is on a separate V4 feature worktree; current Windows checkout and VM100 staging are not shown to have consumed it.
- Last recorded VM100 preflight: staging at `18081` had stale publisher feed (`publisher_fresh=false`, `ready=false`), and U05 durable modify-intent parity was unresolved. Recheck before action; never touch the separate development/simulated service on port `8000`.
- Cloudflare is user-reported installed, but route for `agent.youridea168.com`, DNS, Access policy and origin have not been independently validated.

## 6. Decisions needed before implementation

1. Review and accept/reject PR #154 and PR #153; keep them as drafts until the plans are agreed.
2. Choose the actual Windows/VM100 target contract and decide whether Dev Team's proposed PostgreSQL/Redis/worker architecture is approved for VM100 or needs adaptation to No7's current SQLite/staging setup.
3. Confirm private media storage location, retention/backup, upload size limits, data residency and who may download or publish.
4. Check Windows and VM100 hardware/toolchain, codecs and license compatibility before any AI/video dependencies are installed.
5. Keep integration gates independent: a video render success cannot certify a trading release; QA can report PASS only with exact test/artifact evidence; no Live execution.
