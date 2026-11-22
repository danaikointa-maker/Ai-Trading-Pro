# Ai-Video-Editor — Full Module Master Plan (Proposed)

> Status: **PLANNED / NOT IMPLEMENTED**. This document does not imply any tool is installed, an agent is running, or video has been rendered. Owner review required before merge or deployment.
>
> Parent platform: **No7 AI Dev Team**. This is a creative-production module, not a replacement for the software-development team. Preserve the existing tenant/project registry, authentication, RBAC, audit, dashboard and future orchestration services.

## 1. Vision and outcomes

Create a reusable AI-assisted video-production studio for short films, documentaries, ads and TikTok/YouTube Shorts/Facebook/Instagram deliverables. Support three workflows: **Auto (approval-gated)**, **Co-Editor**, and **Manual + AI Assist**. A project flows through ingest → reference interpretation → original concept → script/storyboard/shot list → asset production → multitrack edit → subtitle/audio/color QC → preview/approval → platform exports → archived knowledge.

**Non-goals:** guaranteed virality, impersonating real people without authorization, bypassing DRM, downloading copyrighted videos without appropriate permissions, automatically using unlicensed music/fonts, falsely implying the video AI generated original footage when it only assembled assets.

## 2. Existing platform integration (reuse first)

- **API:** extend existing `apps/api` FastAPI routers/services; retain existing tenant/project scoped authn, RBAC, audit and rate limits. No second auth service.
- **Dashboard:** add Video Studio sections to existing `apps/dashboard`; share UI/design tokens and existing project navigation.
- **Orchestrator:** new `video_production` task category and agent role definitions, through the platform's planned scheduler; do not claim it exists yet.
- **Events:** reuse the versioned `project_id/task_id/run_id/agent_id/event_id` event envelope, add typed video payloads, use backend truth for animation.
- **Storage:** immutable originals and temporary derived proxies; immutable versioned exports; tenant/project-scoped object store or approved NAS; do not store huge media in Git.
- **Policies:** share approval center, secrets protection, per-project budget/cost ledger, audit events, retention settings and global Skills promotion process.
- **Existing gap:** current repository README reports no real orchestrator/worker runtime or working login and no VM100 Compose validation. Build dependently; never wire animations to fictitious live agent states.

## 3. Directory contract

Filesystem module root configurable via `NO7_VIDEO_ROOT` (not hardcoded to C: or a specific VM path). Support user's three named folders with exact spelling:

```text
Ai-Video-Editor/
├── Raw Footage/
│   ├── Videos/  Images/  Audio/  Voice/  Uploads/
├── References/
│   ├── Downloads/  Video-Analysis/  Style-DNA/
│   ├── Style-Templates/  Typography/  Color-Palettes/
│   ├── Transitions/  Sound-Styles/  Storytelling/
├── Exports/
│   ├── Masters/  TikTok/  Shorts/  YouTube/
│   ├── Facebook/  Instagram/  Project-Packages/
├── Projects/<project-id>/
│   ├── Scripts/  Storyboard/  Shotlist/  Timeline/
│   ├── Subtitles/  Audio-Mix/  Previews/
│   ├── Approvals/  Production-Reports/
├── Templates/  Agents/  Skills/  Config/  Cache/  Logs/
```

Canonical name is **References**; optionally recognize legacy typo `Refferences` and migrate only through an explicit, backed-up action. Never silently rename existing user folders. `Raw Footage` files must remain immutable; edit derived copies.

## 4. Tooling and install strategy

| Tool | Responsibility | Validation |
| --- | --- | --- |
| FFmpeg + FFprobe | probe/transcode, proxy, waveform/audio, final mux | run `ffmpeg -version`, `ffprobe -version`, sample decode/encode |
| Remotion | React timeline/motion compositions and server-side render | license review, pinned package version, smoke render |
| HyperFrames | agent-authored HTML/CSS motion video renderer | verify official package/CLI + license, sandboxed sample render |
| Whisper / faster-whisper | speech-to-text and transcript segment timestamps | Thai language fixture, CPU smoke and alignment checks |
| yt-dlp | authorized reference downloads only | pin version, URL allowlist, no credential leaks or DRM bypass |
| PySceneDetect | shot boundary segmentation | fixture with known cut points |
| librosa | beat/tempo/music analysis | known beat fixture; no claim of perfect musical timing |
| OpenCV / PyAV | frames, visual feature extraction, analysis | color, decode and metadata fixture |
| Pillow / FontTools | image/font inspection and Thai glyph coverage | grapheme and rendering snapshots |
| Playwright + Chromium | visual preview/screenshot/browser test | deterministic media test |

Optional later: OCR only if necessary after visual analysis; TTS/voiceover services with consent and provenance, generative video/image adapter with cost/rights approval, GPU rendering remote adapter. **Do not install tools or make purchases until environment/compatibility/license check is approved.** Record exact installed versions in a machine-readable tool manifest.

## 5. Creative AI officer team

Creative Director (task router and final creative review), Reference Analyst (source/provenance/shot/audio/style), Trend Researcher (fresh platform recommendations with source/date), Scriptwriter, Storyboard Artist, Cinematography/Continuity, Video Editor, Motion Designer, Colorist, Audio Director, Subtitle/Localization QA, Publishing/QC. Roles are logical configurations, not necessarily 12 simultaneous LLM processes.

Each assignment has `task_id`, scoped media permissions, budget, time limit, artifacts, handoff criteria and reviewer. The director must distinguish tool-computed signals from LLM judgments and request human approval for costly models, external publication, rights-sensitive assets, voice/likeness cloning, destructive edits and final release.

## 6. Reference Intelligence / Style DNA pipeline

1. **Intake:** video upload or authorized URL; record title/URL/creator/source/time/access and media usage rights. yt-dlp only when permitted and compliant with service terms; no bypassing DRM/paywalls.
2. **Probe:** metadata/duration/aspect/fps/codecs, audio channels, frame timestamps and file hash.
3. **Segment:** PySceneDetect cuts and selected keyframes, shot lengths, measured pacing, scene-to-scene comparisons.
4. **Transcribe & listen:** Whisper/faster-whisper segments, voice/SFX/music intervals; librosa beats, loudness (FFmpeg loudnorm/ebur128 measurement).
5. **Visual characterization:** palette, contrast, shot framing/motion, graphic placement, typography *attributes* and Thai subtitle readability; mark uncertainty in font identification.
6. **Narrative analysis:** opener/hook, story arcs, shifts in emotion, payoff/CTA and audience fit; separate observable evidence from subjective suggestions.
7. **Abstraction:** generate an **original** Style DNA object, with rules for composition, typography, colors, pacing ranges, cuts, captions, audio direction and originality constraints. Do not clone distinctive shots, exact dialogue, arrangement, logos or copyrighted music.
8. **Template approval:** render 10–20s original preview from owned/licensed assets, compare style traits (not pixel-match), accept/revise, version and publish to project or reviewed global template library.

Persist structured findings with source IDs, confidence, rights/retention metadata, user feedback and style-template version. **Source footage is never promoted to cross-project global memory by default.**

Suggested Style DNA fields: `style_id`, `version`, `source_refs[]`, `rights_status`, `purpose`, `aspect_ratio`, `palette`, `typography`, `subtitle_rules`, `shot_duration_range`, `transitions`, `audio_direction`, `story_beats`, `originality_review`, `created_at`.

## 7. Production workflow and editable artifacts

- Brief intake: goal, audience, platforms, language, duration, style preferences, allowed footage/voice/music, budget.
- AI produces **2–3 distinctly original proposals** with creative rationale, hooks, weak points and improvement opportunities.
- Approved concept becomes `script.json`, `storyboard.json`, `shotlist.json` and character/voice/scene continuity bible for film work.
- Plan media gaps: existing footage, user to record, properly licensed stock, or separately approved AI generated assets.
- Create engine-independent **canonical timeline JSON**: tracks, media references, in/out timecodes, subtitle spans, titles/FX, audio mix, transitions, timing and style template version. Adapters output Remotion/HyperFrames compositions or FFmpeg render instructions.
- Preview at proxy/low-res → timecode comments → targeted revisions (do not silently modify unrelated shots) → draft render → QC → approved master → social variants.
- Export packages: MP4, source timeline, script, storyboard, SRT/VTT, thumbnail options, attribution/license manifest, version and checksum. Do not assume formats/bitrates or platform limits never change.

## 8. Dashboard and Virtual Production Studio

Add views: **Production Campus, Reference Lab, Creative Planning, Video Editor/Timeline, Style Library, Export & Analytics**. Existing global campus routes to a video-production office. Work zones: reference analysis, writers' room, storyboard wall, edit bay, sound booth, render farm, QC.

Map persisted event states to visuals: `queued` walk to assignment board; `analyzing` reference desk; `writing` writer station; `editing` editing bay; `rendering` render room with real progress; `reviewing` QC; `blocked` warning; `completed` completion icon; `offline` faded. Animation must not be equated to actual computation; indicate demo/history vs live distinctly. Offer static/reduced-motion accessibility fallback.

Worker inspector: task/run ID, real source, current step, time, tools, log excerpts (redacted), error, render percent when supported, artifact links, token/API cost when measured, and owner approval actions.

## 9. APIs and domain contracts (proposed, not implemented)

- `POST /api/v1/projects/{project_id}/video/assets` — bounded/resumable upload initiation and validation.
- `GET /api/v1/projects/{project_id}/video/assets` — paged tenant-scoped inventory.
- `POST /api/v1/projects/{project_id}/video/references/analyze` — job from authorized asset/ref.
- `GET /api/v1/projects/{project_id}/video/references/{reference_id}` — evidence/report.
- `GET/POST /api/v1/projects/{project_id}/video/styles` — versioned template library.
- `GET/POST /api/v1/projects/{project_id}/video/productions` — production plan and status.
- `POST /api/v1/projects/{project_id}/video/productions/{id}/render` — idempotent render job, policy-gated.
- `GET /api/v1/projects/{project_id}/video/productions/{id}/exports` — approved artifacts.
- Reuse project event stream for progress snapshots, job state/retries, alerts and replay.

Models (proposed): `video_assets`, `asset_rights`, `reference_sources`, `reference_analyses`, `style_templates`, `style_template_versions`, `productions`, `scripts`, `storyboards`, `timelines`, `render_jobs`, `render_outputs`, `review_comments`, `creative_preferences`, `creative_feedback`, `usage_costs`. Enforce tenant/project foreign keys and auth at every endpoint and artifact URL. Use versioned migrations; do not change current schema without review.

## 10. Security, rights, quality and reliability

- Uploaded media untrusted: MIME/signature probes, size/duration/quota limits, path traversal defense, malware scanning where available, isolated transcode processes, no arbitrary filesystem paths or shell injection.
- URL import SSRF defense: explicit allowed hosts, DNS/IP recheck per redirect, forbid localhost/private/metadata endpoints, timeouts, filesize/rate limits, no raw cookies/tokens in logs; download only with rights.
- Signed and expiring media URLs, per-tenant encryption/ACL, retention & deletion controls; exclude raw assets, transcripts with private speech, license credentials from git and global memory.
- Workers bounded CPU/RAM/time, concurrency, GPU/Cloud API budgets, queue retry/backoff, cancellation, dead-letter queue, crash recovery and artifact integrity verification.
- QC: Thai font/vowel/tonemark shaping, line breaks and caption safe zone; speech/subtitle timestamp checks; loudness/peak and clipping; black/frozen frames; aspect/crop checks; final file playback/hash and rights manifest.
- Export user approval required for publishing. Generated speech should use authorized voice sources; no cloning an identifiable voice without permission.

## 11. Deployment

- **Windows + VS Code:** creative dashboard and preview, editing/render worker, toolchain and local media cache.
- **VM100 Ubuntu (CPU-oriented):** API, project registry, task queue, metadata/reference intelligence, lightweight ASR and memory. Do not promise fast large video-gen on a CPU-only box.
- **Storage:** configurable `NO7_VIDEO_ROOT` and shared/or object storage with backup, cache expiration and clean artifact manifests.
- **Optional GPU/Cloud worker:** use job capability labels; fail safely if unavailable; approval for paid generation.
- Begin with a **single test project and sample rights-cleared video**, not the entire production library.

## 12. Acceptance / definition of done

A successful E2E test uploads a sample video, verifies immutability/hash, imports a rights-cleared reference, extracts a reproducible shot/audio report, creates an **original** Style DNA, generates an approved script + storyboard and a reproducible editable timeline, renders a short preview, corrects a timecoded comment, validates Thai title and subtitle placement, renders a master + vertical variant, performs media/rights QC, and archives the artifacts/history. Event states must reflect actual jobs, including failed/retried/cancelled cases. Cross-project access denied; unapproved URLs/costs/publications blocked. CI and logs must show exact verification evidence.

## 13. Delivery sequence

Phase V0: Repo baseline, compatibility, rights/license matrix, ADR and architecture approval.
Phase V1: Media store, uploads, metadata, immutable asset database and queue contracts.
Phase V2: Tool installer + version/health diagnostics, fixtures and render sandbox.
Phase V3: Reference intelligence (scene/audio/text/palette/pacing) + original Style DNA.
Phase V4: Creative officer roles, briefs/proposals/scripts/storyboards/continuity.
Phase V5: Canonical multitrack timeline, Remotion/HyperFrames/FFmpeg adapters, preview and revision.
Phase V6: Dashboard + Virtual Production Office state mapping using **real** events.
Phase V7: Audio, subtitle, Thai typography and technical/rights QC.
Phase V8: Platform export presets, approved master and editable project package.
Phase V9: Preference memory, analysis history, style versioning, feedback and cross-project review.
Phase V10: Security, E2E, performance/load, backup/restore, UAT, user manual and release review.

For each phase: DISCOVER → PLAN → IMPLEMENT on isolated branch → TEST → REVIEW → REPORT → request approval when sensitive. **Never merge or deploy by default.**

## 14. Suggested first PRs for VS Code team

1. `video/docs-domain-contracts`: proposed ADRs, data schema and rights model only.
2. `video/asset-intake-mvp`: upload/probe/immutable storage with tests and RBAC.
3. `video/toolchain-smoke`: version-pinned media tools + fixture renders, no external downloads.
4. `video/reference-style-dna`: deterministic analyses + original-style preview.
5. `video/production-mvp`: single short demo project with script, timeline, render and QC.

Document owner-approved deviations in ADRs; avoid duplicating existing platform services.
