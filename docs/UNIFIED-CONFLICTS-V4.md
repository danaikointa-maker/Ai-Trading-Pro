# No7 AI Trading Pro — Conflict and Document Disposition Register V4
Updated: 2026-11-19. These are comparisons based on repository content, NOT installed runtime verification.

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
| Linked MT5 Demo orders | Dirty PC dashboard/runtime source has per-account `demo-execution`, `orders`, and `demo-auto` routes; current VM OpenAPI exposes them as POST. V4 branch lacks these routes and `/api/trading/order` still targets only the active runtime adapter. VM feed is `simulate`, and the VM checkout is dirty | UI shows per-account Demo control and order buttons | do not treat the dirty runtime as a V4 release; reconcile the per-account ownership/bridge/risk guards into the canonical branch after U01 review, then validate Demo end-to-end. The earlier 405 is not reproduced by current OpenAPI; method availability alone does not certify account readiness or order safety |
| MATH | old docs describe point/lot and legacy partials | newer risk/BE maths | tech math doc reflects active code; new math in plan until implemented |
| Reality | simulation default; demo not fully validated | prompts say auto/open immediately | not considered operational; Demo explicit permission only |

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
