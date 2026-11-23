# VS Code / Codex / Cline — Ai-Video-Editor Implementation Instructions

> Planning prompt; not an assertion that any tool or feature is installed. Read `docs/video/AI_VIDEO_EDITOR_MASTER_PLAN.md` and existing project docs before touching code.

## Mission
Add `Ai-Video-Editor` as a reusable creative-production module to **No7 AI Dev Team** without replacing or breaking the existing software-development team, FastAPI, dashboard, project registry, authentication, RBAC, audit logging, tests, or future worker contracts.

## Non-negotiable rules
1. Inspect repository reality first. The README documents a foundation, not a finished orchestration stack. Report missing runtime capabilities explicitly.
2. Inventory existing module structures, docs, ADRs, Python/Node versions, migrations, tests, API paths, CI policies and deployments. Avoid duplicate services/specs.
3. Start with **V0 discovery and architecture/design docs**. Do not install packages, download reference videos, access online APIs, run GPU jobs, or write production data until environment and permissions are checked.
4. Preserve `Raw Footage/`, `References/`, `Exports/` under configurable `NO7_VIDEO_ROOT`. Legacy `Refferences` is a migration alias only.
5. Build independent, bounded PRs in the order documented in the plan. Reuse current RBAC, audit and project scoping; do not add a separate user system.
6. Never represent synthetic animation/test data as a real running AI worker. Bind virtual office state to persisted job status.
7. Use only reference content that is owned or authorized. yt-dlp is for compliant imports; do not bypass DRM, copy a video's signature shots/dialogue, reuse music without rights, or use fonts without license.
8. All source media immutable; path traversal, SSRF, shell invocation, untrusted ffmpeg input, media quota and cloud-cost threats must be handled.
9. Require human approval for paid model usage, public publishing, sensitive voice/likeness use, deletion, large external downloads and production changes.
10. Persist creative reasoning/feedback as structured Style DNA with source provenance, uncertainties, rights metadata and versioning. Do not silently train on third-party footage.
11. Thai-language captions/fonts and audio/video QC are release gates. Tests must use rights-cleared small local fixtures.
12. Before every commit: validate intended diff, run relevant lint/typecheck/tests, record exact commands and results. Never claim passing tests without evidence.
13. Final answer in Thai summarizing: phase, files changed, tests with actual results, remaining blockers, PR/commit IDs and next phase.

## Toolchain check list
- ffmpeg/ffprobe
- remotion (check license requirements)
- hyperframes (verify official distribution and installed API)
- whisper/faster-whisper
- yt-dlp
- pyscenedetect
- librosa
- opencv/pyav
- pillow/fonttools
- playwright/chromium

For every tool record: purpose, source URL, version pinned, license, host requirements, installation command, offline sample test, failure behavior.

## Deliverable milestones
- V0 discovery report, acceptance tests, ADR and planned file tree
- V1 immutable assets + scoped storage API
- V2 tool adapters and reproducible local fixture
- V3 authorized reference analysis + Style DNA JSON contract
- V4 12 logical creative worker role definitions + script/shot/storyboard output
- V5 editable canonical multitrack timeline and backend adapters
- V6 real status-based virtual studio
- V7 technical/legal/Thai typography QC
- V8 multi-platform approved export packages
- V9 memory/version/history and user feedback
- V10 comprehensive E2E, security and restore tests

## First command to execute
"Audit this repository read-only against docs/video/AI_VIDEO_EDITOR_MASTER_PLAN.md. Identify existing compatible components, missing prerequisites, security and license risks. Produce V0 implementation backlog and proposed ADRs. Do not modify runtime code or install tools in this initial step."
