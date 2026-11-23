# U08 — Calculator Core Audit

Date: 2026-11-23  
Plan: Unified Master Plan V4 / Unified Task Register V4  
Branch: `feature/u08-account-currency-calculator-v4`

## Gap and change

The repository already had one shared backend `points_calculator` used by both
`/api/market/calculator` and `/api/risk/calculator`; the Vue points calculator
calls the market endpoint. No second frontend arithmetic engine was added.

The shared calculator multiplied raw profit-currency P&L without applying
`quote_to_account_rate`, unlike `SymbolSpec.pnl_in_account_currency` and the
other risk/backtest paths. That could overstate a JPY-quoted trade on a USD
account by roughly the FX rate. The calculator now uses the shared account
currency conversion, preserves the existing `net_profit` field as gross less
commission, and separately exposes `net_after_known_costs` after typical spread
and commission. It exposes market feed, spec and FX source metadata. Unknown or
incomplete valuation inputs return no monetary figures rather than treating an
unresolved rate as 1.0. The dashboard labels the currency and source and shows a
warning when the monetary valuation is unavailable.

The 16-tool catalog is documented in
`docs/calculators/TRADING-CALCULATOR-16-TOOL-CATALOG-V4.md`. A later follow-up
implements the first catalog item as a read-only manual sandbox Position Size
tool using the shared `/api/risk/calculator` route and shared symbol math. The
other calculator flows remain unimplemented; U08 remains partial.

## Evidence

| Check | Result |
|---|---|
| Account-currency math and unknown/inconsistent-rate regressions | PASS — 21 passed |
| API source/provenance and shared-core regressions | PASS — included in the same 21-test run |
| Selected Ruff `--select F,E9`, compileall, diff check | PASS |
| Dashboard Vite production build | PASS — 624 modules |
| Paper / MT5 comparison | NOT TESTED; no broker command was sent |
| 16-tool catalog and missing calculator workflows | NOT IMPLEMENTED |

## 2026-11-23 follow-up — Position Size

The U06–U10 continuation added one calculator flow. Manual equity, risk percent,
and stop distance are sent to the existing read-only risk-calculator endpoint;
the server includes known typical spread and round-turn commission, floors
volume to the legal step, and reports `no_legal_lot` instead of rounding a
below-budget request up to minimum volume. Unknown symbol or FX specifications
fail closed. No account balance is read or stored, and the endpoint never calls
the execution gateway. The UI labels this `MANUAL · SANDBOX`.

Evidence: `tests/test_points_math.py tests/test_api.py tests/test_invariants.py`
— 75 passed (one existing Starlette/httpx deprecation warning); the shared U06–U10
regression set passed 289 tests (same warning). Ruff E9/F/I,
compileall, and `git diff --check` passed; the latest Vite 5.4.21 production build passed
with 627 modules. Broker-side comparison, remaining tools, exports, and lessons
remain NOT TESTED / NOT IMPLEMENTED. See
`docs/audits/U06-U10-position-size-followup-2026-11-23.th.md`.

## Safety and rollback

Only read-only calculation output changed. No order/modify endpoint is called,
no active config or broker state changed, and no Live or Demo trading action was
performed. Rollback is a revert of the U08 calculator commit; no persistence
migration is required.
