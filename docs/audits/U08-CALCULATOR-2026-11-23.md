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

The 16-tool catalog is not present in the current branch. The Master Plan does
not define the names, formulas, inputs or acceptance criteria for the remaining
tools, so this change does not invent them. U08 remains partial.

## Evidence

| Check | Result |
|---|---|
| Account-currency math and unknown/inconsistent-rate regressions | PASS — 21 passed |
| API source/provenance and shared-core regressions | PASS — included in the same 21-test run |
| Selected Ruff `--select F,E9`, compileall, diff check | PASS |
| Dashboard Vite production build | PASS — 624 modules |
| Paper / MT5 comparison | NOT TESTED; no broker command was sent |
| 16-tool catalog and missing calculator workflows | NOT IMPLEMENTED |

## Safety and rollback

Only read-only calculation output changed. No order/modify endpoint is called,
no active config or broker state changed, and no Live or Demo trading action was
performed. Rollback is a revert of the U08 calculator commit; no persistence
migration is required.
