# No7 AI Trading Pro — Conflict and Document Disposition Register V4
Updated: 2026-11-21. These are comparisons based on repository content plus the dated U00/U01 runtime evidence; not a general production certification.

| Area | Existing source/config | Competing proposed instruction | Disposition |
|---|---|---|---|
| Weekly loss | `config/risk.yaml` 5% | later draft 4% | preserve legacy 5%; 4% in unactivated candidate only |
| Peak drawdown | 10% | draft 8% | versioned candidate 8%; not silently active |
| Min net RR | 1.30 | draft 1.5 | candidate 1.5; verify after costs |
| Max open trades | 1 | earlier prose 2-3 | preserve 1 until evidenced; candidate also 1 XAUUSD |
| BE trigger | 250 MT5 points | +1.0R | candidate +1R; existing logic untouched until tested |
| BE lock | 30 points | actual costs + 0.05 USD/oz | candidate cost-aware; optional extra is unproven |
| Trailing | 500 points, 50-point step | +1.5R, 0.2 ATR step | candidate policy and A/B tests |
| Partials | 40/30/30 enabled | single 2R TP, partial off | separate legacy/new profiles, no silent switch |
| TP | 500/750/1000 points & adaptive zones | 2R | compare profitability and opposing zones, never guarantee |
| BE/Trail enabled | enabled in YAML | safer draft defaults off | distinguish configured rules from authorization and broker deployment; candidate AUTO OFF |
| Kill flatten | true | proposed false | no silent live change; separate loss breach, stale feed and emergency liquidation policies |
| Auto execution | `full_auto.enabled=false` | auto after 100-point confirmation | only after full gate in explicit DEMO, never auto promote |
| Symbol | app XAUUSD | request XAUUSD.m | resolve exact mapping from broker spec; no hardcoding suffix |
| Architecture | FastAPI/Vue3/MQL5, SQLite | prior prompts may suggest new services/database | reuse existing stack; PG only approved migration |
| Position modification | `manager.py` can generate BE and trailing actions | new ProtectionEngine | single candidate reducer and one existing execution gateway, avoid two commands |
| MATH | old docs describe point/lot and legacy partials | newer risk/BE maths | tech math doc reflects active code; new math in plan until implemented |
| Reality | simulation default; demo not fully validated | prompts say auto/open immediately | not considered operational; Demo explicit permission only |
| Windows MT5 host | V4 source snapshot names VM200 | User later specified the development Windows PC as the current MT5 installation/execution host | Treat the development PC as current Windows MT5 host; do not operate VM200 unless separately reauthorized. Verify local terminal identity and outbound PC→VM100 bridge before execution acceptance. |
| VM100 runtime | V4 expects `/opt/no7-ai-trading-pro` | Read-only SSH audit on 2026-11-21 found no checkout at `/opt`; actual listeners are port 8000 development/simulated and port 18081 staging on `feature/u02-100pt-confirmation` (`06642a0`), with staging feed stale. Stage has durable `position_modify_intents` persistence/helpers absent from V4 target `0171e9e`. | Never touch 8000. Do not replace/restart 18081 with the whole V4 checkout until U05 parity is audited and restored. The existing publisher route accepts the V4 UTC schema; freshness still requires a PC-local data-only publisher and verified Demo identity. |
| Durable position modify | VM100 stage `06642a0` has `position_modify_intents` reservation/reconciliation; the V4 candidate on `feature/u05-durable-modify-ledger` ports an additive ledger and guarded gateway flow. Read-only stage DB inspection found SQLite integrity `ok`, the account/ticket/idempotency key and partial unique unresolved-intent index, with 0 rows at audit time. | U05 requires reuse, one unresolved writer per account/ticket, broker readback/reconciliation, and no stage regression | The empty table does not establish broker-state parity. Candidate source preserves the ledger behavior, but local tests and commit identity must be verified on this branch. U05 remains blocked until staging parity/reopen checks and an authorized Connext-Demo modify/readback receipt; U01 fresh quote is still a prerequisite. See `docs/U05-POSITION-MODIFY-STAGING-AUDIT-V4.md` and `docs/audits/U05-DURABLE-POSITION-MODIFY-2026-11-23.th.md`. Never drop the table or replace/restart staging before the remaining gates. |

## Document ownership and disposition
- `docs/UNIFIED-MASTER-PLAN-V4.md`: canonical planned behavior, phase order and module ownership.
- `docs/UNIFIED-TASK-REGISTER-V4.md`: canonical development queue and evidence statuses.
- `docs/UNIFIED-CONFLICTS-V4.md`: canonical conflict resolution and migration decisions.
- `docs/blueprint-v3/AGENTS.md`: binding non-negotiable system safety policy (higher priority than features). Keep and annotate pointer rather than wholesale replace.
- `README.md`: as-is overview and links; keep history and add pointer.
- `docs/DEVELOPMENT.md`: current developer workflow; add pointer, do not erase historical test reports.
- `docs/blueprint-v3/MASTER-BLUEPRINT.md`: ARCHIVED PLANNING REFERENCE; retains v3 rationale; not a second active task list.
- `docs/POSITION-PROTECTION-INTEGRATED-V1.1.md`: ARCHIVED INPUT / reference for detailed requirements; superseded as task execution source.
- `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/MATH.md`, `docs/RUNBOOK.md`, `docs/LIMITATIONS.md`: still canonical for CURRENT implemented behaviors and verified limitations; update only in code PR.
- `config/risk.yaml`: current executable defaults; no documentation-only mutation. Candidate config/version and migration needs separate reviewed implementation.
- Earlier prompts: design inputs only; never run sequentially in addition to V4 Task Register.

## Decisions before activation
1. Confirm broker XAUUSD vs XAUUSD.m specs and account currency.
2. Approve new weekly/DD/RR and partial preset migration after result comparison.
3. Approve real DEMO-only modify order support after tests and broker identity match.
4. Define emergency liquidation permissions distinct from kill-switch entry block.
5. Obtain real tick data and evidence before asserting an optimal 100-point/ATR/R policy.
