# Ai-Video-Editor — Planning Hub

**Status: Proposal / not implemented** · **Platform:** No7 AI Dev Team · **Primary workspace:** VS Code.

This module expands the existing multi-agent software-development workspace to include an **AI Creative Production Studio** for short films and social media videos. The video department uses existing shared identity, project isolation, approvals, event-driven office dashboard and future orchestration rather than building a second platform.

## Read in order
1. [Master Plan](AI_VIDEO_EDITOR_MASTER_PLAN.md) — complete product scope, folder contract, reference intelligence, agents, tools, API, security, editing engine, integration, milestones and acceptance.
2. [VS Code Agent Prompt](VSCODE_AI_IMPLEMENTATION_PROMPT.md) — safe instructions for Codex/Cline/Copilot to inspect the repo, implement per phase and report verified work.
3. [Existing Platform Blueprint](../01_MASTER_BLUEPRINT.md) — current architectural intent and shared service boundaries.
4. [Existing Platform Phase Plan](../02_PHASE_PLAN.md) — platform dependencies and prior phase gates.

## Folder contract
```text
Ai-Video-Editor/
  Raw Footage/
  References/
  Exports/
  Projects/
  Templates/
```
Canonical spelling: **References**, with an optional checked migration from `Refferences`. Root is configured through `NO7_VIDEO_ROOT`; the content directories hold runtime media and must not be committed to Git.

## Priority decision
Start with foundation audit and a **rights-cleared 10–20 second sample video** demonstrating ingest → analysis → original Style DNA → script/storyboard → edit/preview → Thai caption QC → export and archive. Do not promise automatic viral performance or unsupported real-time agent activity.

## Decision gates
- V0 approval: existing code compatibility, license and tool availability
- Security approval: downloading/URL import, external AI providers, subprocess execution and storage permissions
- Creative approval: concept, copyright-sensitive assets and final publication
- Quality approval: repeatable render, audio/video QC, Thai font/subtitle tests, provenance manifest

All features in these documents are proposed. Working implementations and test counts must be reported from the repository's actual CI/run artifacts.
