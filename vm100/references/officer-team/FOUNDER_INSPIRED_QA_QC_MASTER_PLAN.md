# No7 AI Officer Team V4 — Founder-Inspired Organization + Independent QA/QC Master Plan

**Status:** PROPOSED; design documentation only, no implementation claimed. **Target:** existing No7 AI Dev Team repository. **Date:** 2026-11-22.

## 0. Principles and source ideas

This plan selectively adapts organizational concepts rather than cloning third-party source code.

| Reference | Inspiration | Adaptation boundary |
|---|---|---|
| [Founder-OS](https://github.com/officiallyutso/Founder-OS) | layered memory, specialist agents, approval-gated actions, proactive goal tracking | reuse principles, not unreviewed self-modifying code or risky automation |
| [cofounder](https://github.com/ajsai47/cofounder) | teams organized into departments and shared knowledge | logical roles activated on demand; no 29-agent always-on cost |
| [AgentFounder](https://github.com/usaos/AgentFounder) | problem/idea → product → deliver workflow | convert to auditable project task lifecycle and quality gates |
| [ai-cofounder](https://github.com/artemiimillier/ai-cofounder) | local-first routines, explicit permissions and schedules | project scoped routines; no unconditional cross-project execution |
| [bulletproof](https://github.com/artemiimillier/bulletproof) | disciplined multi-stage engineering review | evidence-backed, phase-specific checks; avoid forcing every task into all stages |

Existing repository reality: README describes platform foundation (FastAPI, project/tenant registry, RBAC/OIDC, audit, dashboard, metrics) but **worker/orchestrator, login/session and deployed environment are not yet complete**. This V4 plan must integrate without creating a second identity service, queue, project registry, memory silo or conflicting roadmap. Existing `docs/01_MASTER_BLUEPRINT.md` and `docs/02_PHASE_PLAN.md` remain the platform baseline; this document is a specialist extension to be reconciled into ADRs during discovery.

## 1. Product goals

Build a reusable enterprise-like AI workforce for software engineering, QA, operations and optional video production, used through VS Code and the shared Web Dashboard. One task can be planned, delegated, built, independently tested, reviewed and handed off with verifiable evidence. Track project context, boundaries, costs and audit history. A Virtual Office is a visual projection of backend events, never the backend itself.

Success requires **quality of outcome**, not headcount or animation. Use on-demand specialists, scoped permissions, separate implementation and approval roles, deterministic automated tests and human release authority.

## 2. Department design

### Executive / Program Office
- **Chief Orchestrator / AI CEO:** intake and route user goals, oversee prioritization, budgets and cross-project resource allocation; never bypass approval.
- **CTO / Solution Architect:** technical direction, cross-module change impact, ADRs and design reviews.
- **Project Manager:** backlog, milestones, dependencies, blocked-work escalation, completion evidence and project reporting.
- **Business Analyst / Product Owner AI:** specs, requirements, acceptance criteria, user journeys and questions.

### Engineering Office
- Frontend/UI, Backend/API, Database, Integration, Performance, Debug/Root-Cause specialists.
- Worktrees isolate concurrent mutations; assign **one writer per file scope**; changes integrate by bounded PRs with branch protection.
- Never give one agent unrestricted access across unrelated projects.

### Independent QA/QC Office (**mandatory for production tasks**)
- **QA Lead / Test Strategist:** risk matrix, quality plan, DoD, coverage strategy.
- **Test Designer:** acceptance tests, negative cases, boundary values, equivalence classes, property/metamorphic scenarios.
- **Unit/Integration QA:** test runners, fixtures, contract tests, data consistency.
- **E2E/UI QA:** Playwright browser tests, cross-viewport, accessibility, localization, screenshot-diff with reviewed baselines.
- **API/Database QA:** OpenAPI schema validation, RBAC isolation, concurrency, migration/rollback, transaction and idempotency tests.
- **Performance/Load QA:** p50/p95/p99, throughput, resource and leak checks with defined environment/budgets.
- **Security QA:** SAST, dependency/license/secret scanning, authz/SSRF/path traversal checks and controlled DAST in authorized environment.
- **Regression QA:** every verified bug gets a regression test tied to issue/commit and a reproducible fixture.
- **Release QC Auditor:** independent sign-off, evidence review, unresolved-risk register and final gate recommendation (human approves releases).

### DevOps / Reliability
- CI/CD, observability, deployment, incident response, backup/restore, rollback, SLO runbooks.
- Deployment production, destructive DB migrations, secrets changes and public access always gated.

### Knowledge / Research
- Repository-aware analysis, project memory, verified fix patterns, skill/version registry, evidence/provenance, current reference research.
- Promote project memories to global only after permissions, redaction, compatibility and review. No automatic training on private data.

### Creative / Media Production
- Ai-Video-Editor creative director, reference analysis, script/storyboard, editor, audio/subtitles and media QC.
- Incorporate `docs/video/AI_VIDEO_EDITOR_MASTER_PLAN.md` if/when that pending PR is merged; do not assume it is currently on main. When absent, treat creative-video-specific docs as optional future integration.

## 3. Execution lifecycle (canonical)

```text
INTAKE → DISCOVERY → REQUIREMENTS → PLAN → APPROVAL_IF_NEEDED
  → IMPLEMENT (isolated worktree)
  → STATIC_CHECK → UNIT/INTEGRATION → E2E/CONTRACT
  → SECURITY/PERFORMANCE (risk-based)
  → INDEPENDENT_QA_REVIEW
  → [BUG TRIAGE → ROOT CAUSE → FIX → REGRESSION RETEST] (bounded)
  → QC_RELEASE_GATE → HUMAN_APPROVAL (production)
  → PR / RELEASE ARTIFACT → DOCUMENTATION → LEARNING REVIEW
```

Alternate transitions: `blocked`, `waiting_approval`, `cancelled`, `failed`, `retry_exhausted`, `unobservable`. Store lifecycle state in backend; Virtual Office maps to animation. Limit fix loop by max attempts + elapsed time + cost; never let repeated test failures drain unlimited credits.

Per task record: tenant_id, project_id, task_id, issue_id, run_id, agent_id, scope, file ownership, parent/child dependencies, risk_tier, tool/model budget, acceptance criteria, test plan, execution evidence, approvals and immutable audit timestamps.

## 4. QA/QC policy & gates

**Definition of Ready**: scope and acceptance criteria; identified dependencies; source-state baseline; test strategy and authorized environment; threat/risk tier.

**Definition of Done**: changes reproducible from exact commit; unit/integration tests passed, applicable E2E/API/security tests passed; no known blocking regression; migration rollback and compatibility reviewed where applicable; security/license checks recorded; docs updated; test outputs/artifacts attached; review approval recorded. If a check was skipped, report **SKIPPED** with reason, never PASS.

Required quality gates:
- G0 requirements: clear expected behaviors + negative cases
- G1 code/style: formatter, lint, typecheck and build
- G2 functional: unit, integration, API contract, DB migration test where relevant
- G3 E2E: actual user flow, permissions, browser/mobile regressions
- G4 security: static/security/secret/dependency/license and project isolation
- G5 reliability: concurrency, restart/replay, timeout, retry, backup/restore where relevant
- G6 QC: independent reviewer examines evidence and unresolved issues
- G7 release: explicit authorized human approval and rollback plan

Risk tiers:
- **Low** read-only docs/config analysis: lightweight doc review and tests only when relevant.
- **Medium** application changes: G1–G3, G4 scoped, G6.
- **High** auth/roles/billing/trading/external actions/production/DB destructive: all applicable gates plus explicit user approval, controlled staging verification, rollback drill where feasible.

Measurement: escaped defect rate (post-release), reopened bug rate, regression recurrence, failed builds, change failure rate, MTTR, test flakiness, time/cost per verified task, user acceptance. **Avoid vanity scores like made-up agent accuracy percentages.**

## 5. Bug lifecycle and triage taxonomy

`NEW → REPRODUCED → TRIAGED → ASSIGNED → FIX_IN_PROGRESS → READY_FOR_RETEST → VERIFIED → CLOSED`.
Alternates: `NOT_REPRODUCIBLE` (evidence needed), `DUPLICATE`, `DEFERRED` (owner-approved), `REOPENED`.

Ticket fields: bug_id, project_id, severity (critical/high/medium/low), priority, environment, baseline commit, reproducible steps, expected vs actual, logs/screenshot/video (redacted), suspected cause, owning agent, fix commit, regression test path, test report, review and closure evidence.

Severity examples: critical = financial/safety/security/data loss; high = core functionality unusable; medium = partial functional loss; low = cosmetic. Priority considers business impact and risk, not severity only.

**Debug loop:** reproduce → minimize failing case → root cause hypothesis → targeted patch in owned scope → regression test → rerun impacted suite + smoke/regression → independent QA verify. Max 3 corrective attempts by default then escalate; no random endless rewrites.

**No self-attestation:** the coder cannot alone close its own defect. QA has read-only-by-default access and independently runs relevant tests. A human approves release for high-risk changes.

## 6. Testing matrix per project archetype

| Type | Minimum special tests |
| --- | --- |
| Laravel/PHP service platform | PHPUnit/Pest as present, API/auth/role, MySQL migration and transaction, browser E2E, setup preflight, multi-tenant isolation |
| CodeIgniter/VVA/IoT | hardware API mocks + approved lab runs, UDP/barrier/ANPR timeouts, idempotent events, offline/recovery, safe barrier command authorization |
| Android/PDA/PWA | barcode/camera permissions, online/offline queues, sync conflict, device compatibility, responsive/accessibility |
| Python/React platform | pytest, Vitest, TypeScript checks, Playwright, migration and OIDC fail-closed scenarios, load/observability |
| Ai-Trading-Pro / MT5 | historical replay with timestamp provenance, feed parity, risk engine hard caps, slippage, spread, stale quote, broker rejection, duplicate orders, kill switch, demo-only execution until owner approval; no profitability guarantee |
| Ai-Video-Editor | rights-cleared fixtures, immutable raw media, tool/codec smoke, reference originality, render reproducibility, Thai font/diacritics, subtitle/audio sync, black frames/clipping, format-safe areas, license manifest |

Capability must be detected rather than assumed. Hardware tests or live broker routes never auto-run without explicit authorization.

## 7. Test platform design

- QA Test Registry: test IDs, suite, project, risk, owner, required tools, tags, expected evidence and historical result.
- Ephemeral Test Environment Manager: isolated database, namespaced services, test fixtures/seeds, cleanup and leak detection.
- Test Runner Adapters: pytest, Vitest/Jest, Playwright, PHPUnit/Pest, static scanners, custom hardware simulators and media QC.
- Failure Classifier: test code vs environment vs product regression vs flaky; rerun flaky tests under controlled count and mark FLAKY, not PASS.
- Artifact Store: JUnit XML, coverage, Playwright traces, screenshots (redacted), resource profiles, migration logs, video QC report; link to exact run/commit.
- Quality Report API: `summary`, `failed`, `blocked`, `skipped`, `flaky`, `passed`; release decision is rule-based, explainable and audited.
- Bug Knowledge Base: verified root cause + fix + reproducible regression; user feedback and compatibility caveats, project scoped.
- Coverage strategy targets changed-code branches, critical flows and risk-adjusted coverage, not a universal 100%.

## 8. Virtual Officer Office UX

Rooms: executive planning table, architecture whiteboard, engineering desks, **QA Testing Lab**, security station, incident room, release approval room, optional video studio. Agents sit/type/analyze only when backed by actual task events. **A failed test triggers a red QA board and a bug ticket**, a fix retest moves inspector to QA, a passed release gate makes QC ready for approval (not automatic deployment). The live board shares the exact state with Kanban and Audit.

Inspector: active job and related PR, owner, tools/models, resource use, test counts by status, last verified evidence and whether a run is blocked/unobservable. Screens default to clearly labeled Demo Mode if synthetic; reduced-motion fallback; never confuse animation FPS with task progress.

## 9. API/data contracts (proposed, no implementation claims)

Reuse existing auth, RBAC, tenant/project ownership, event schema and dashboard. Domain additions (new tables require migration/ADR review): `departments`, `agent_roles`, `task_workflows`, `qa_test_cases`, `qa_test_runs`, `qa_artifacts`, `bug_reports`, `bug_regressions`, `quality_gates`, `release_signoffs`, `learning_candidates`. Do not duplicate platform `tasks`, `runs`, `events`, `audit_logs`.

Proposed routes:
- `GET /api/v1/projects/{project_id}/qa/overview`
- `GET/POST /api/v1/projects/{project_id}/qa/test-plans`
- `POST /api/v1/projects/{project_id}/qa/test-runs`
- `GET /api/v1/projects/{project_id}/qa/test-runs/{run_id}`
- `GET/POST /api/v1/projects/{project_id}/qa/bugs`
- `POST /api/v1/projects/{project_id}/qa/bugs/{bug_id}/verify`
- `GET /api/v1/projects/{project_id}/qa/release-gates/{release_id}`
- `POST /api/v1/projects/{project_id}/qa/release-gates/{release_id}/request-approval`

All write requests: project-specific RBAC, idempotency, audit, per-run resource limits, cross-project isolation and authorization; no user-controlled arbitrary shell commands or unrestricted test endpoints.

## 10. Founder concepts worth adopting / rejecting

**Adopt:** reusable department templates, goal-oriented planning, layered approved memory, explicit permissions, approvals, cost budgets, proactive reminders for blocked tasks, source-linked decision journals, measurable feedback.

**Reject / defer:** indiscriminate 29+ live LLM agents, agents rewriting their own tools without approval, cross-project secrets in shared memory, autonomous production releases, automatic financial/payment actions, fabricated task progress, agent self-grading as sole proof.

**Control plane:** one shared orchestrator with policies, job scheduling, authorizations and evidence ledger. Every department is a plug-in role package, not a copy of all infrastructure.

## 11. Build roadmap aligned to existing platform phases

- **O0** Read-only repo audit: compare existing code/docs to this plan, review source licenses and security, ADR backlog; no code edits.
- **O1** Department & role registry (data contracts only), ownership and capability mapping.
- **O2** QA test registry + execution adapters and artifacts, initially existing CI test suites.
- **O3** Bug tracking, reproducible reporting, regression generation and bounded fix/retest loop.
- **O4** Risk-weighted QC release gates and human signoffs, independent reviewers.
- **O5** QA dashboard + animated QA lab from persisted events, demo clearly labeled.
- **O6** Layered memory/provenance and reviewed reusable solutions; no global private-data leakage.
- **O7** Multi-project framework detection (Laravel, CI, PDA, trading, video) and typed acceptance packs.
- **O8** Worktree ownership, merge queue, staging envs, resource/cost policies and notifications.
- **O9** Resilience and observability: flaky handling, cancelled/timeout/crash, recovery and replay.
- **O10** Security audit, E2E pilot on one demo project, rollback and operator handbook.

**Phase dependencies:** existing Phase 3 orchestration and Phase 4 events are prerequisites for actual autonomous lifecycle and real-time office; until then support evidence-backed CI-only QA dashboard. Existing Phase 2 auth/project scoping must remain fail-closed.

## 12. Evidence-first acceptance

Pilot with one rights-cleared sample software repository:
1. Intake feature request with acceptance criteria and baseline commit.
2. Route through architect and developer working on scoped worktree.
3. Trigger independent QA suites; intentionally inject one reversible bug.
4. Store failing test and bug record with reproduction details.
5. Fix in bounded loop, produce regression test and rerun all impacted checks.
6. Verify only authorized human can approve merge/release.
7. Demonstrate that a simulated/unknown worker cannot claim live progress.
8. Demonstrate cross-project access denied, no secrets in logs, failure leaves repo recoverable.
9. Show metrics/evidence on Dashboard and a matching animated QC Lab.
10. Generate a final Thai project report linking commit, CI/test outputs, QA decision and unresolved risks.

**Never claim implementation, production readiness, current test counts or successful CI without actual observed evidence.**

## 13. Commands for VS Code AI coding lead

"Start O0: inspect the repository and compare the Founder-inspired Officer Team + QA/QC plan against existing API, dashboard, policies, CI, docs and pending video plan. Produce a gap matrix, risk-ranked tasks, dependencies, ADR proposals, and exact validation commands. Do not change main, install tools, deploy, or run external actions yet. Build incremental PRs with deterministic test evidence and independent QA checks."

## References / attribution
- https://github.com/officiallyutso/Founder-OS
- https://github.com/ajsai47/cofounder
- https://github.com/usaos/AgentFounder
- https://github.com/artemiimillier/ai-cofounder
- https://github.com/artemiimillier/bulletproof

This is a feature/design analysis; check third-party licenses before reusing code, assets or proprietary workflows.
