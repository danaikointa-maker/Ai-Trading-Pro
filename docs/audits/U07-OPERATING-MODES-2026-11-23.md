# U07 — Operating Modes / Full Auto RBAC Audit

Date: 2026-11-23  
Plan: Unified Master Plan V4 / Unified Task Register V4  
Branch: `feature/u07-full-auto-rbac-v4`

## Gap and change

The existing `manual` / `semi_auto` / `full_auto` entry mode is separate from the
four planned position-protection modes. No versioned, account-scoped protection
mode override was found, so that portion of U07 remains missing.

The legacy Full Auto setting had two authorization defects: any trader could
change the Risk Engine flag through the API, and a previously persisted
`full_auto` mode could remain selected after a safety switch was removed. The UI
also presented the Full Auto control without reflecting admin authority.

This slice keeps the existing APIs, roles, Risk Engine and Vue controls. It
restricts both Full Auto setting changes and entry into `full_auto` to admins;
rejects unauthorized mixed requests before changing limits; checks both the
deployment and Risk Engine switches at every full-auto risk gate; returns a
stale persisted mode to Manual when startup sees either switch off; and disables
Full Auto controls for non-admins or while either switch is off. Disabling the
Risk Engine switch also returns the active entry mode to Manual.

## Evidence

| Check | Result |
|---|---|
| Roles and risk regressions | PASS — `pytest tests/test_roles.py tests/test_risk_engine.py -q` — 32 passed, 1 existing Starlette/httpx deprecation warning |
| Selected Ruff checks | PASS — changed backend/tests, `--select F,E9` |
| Dashboard production build | PASS — Vite 5.4.21, 624 modules |
| Whitespace | PASS — `git diff --check` |
| Broker / Paper / Demo execution | NOT TESTED; no broker command was sent |
| Four position-protection modes and per-account versioned overrides | NOT IMPLEMENTED |

`npm ci` reported 3 dependency advisories in the installed dashboard dependency
tree (2 moderate, 1 high); dependency versions were not changed in this slice.

## Security and rollback

The code changes authorization and stale-mode recovery only; it does not enable
Full Auto, change `config/risk.yaml`, alter broker state, or authorize Live.
Rollback is a revert of the U07 source/documentation commit. No database schema
or active configuration migration is introduced.

U07 remains **PARTIAL / NOT ACCEPTED** until the four distinct protection modes,
versioned account-scoped overrides, audit/concurrency tests, and their UI behavior
are implemented and reviewed. Demo runtime acceptance remains separately gated.
