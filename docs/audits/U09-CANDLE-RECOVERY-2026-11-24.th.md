# U09 Candle Recovery Audit — 2026-11-24

## Scope

Continue the existing U09 Dashboard implementation in `PriceChart.vue`; do not create another chart/feed service. Keep U09 partial until authenticated visual acceptance and a real feed reconnect are observed.

## Gap found

- The chart applied a cached ticker without checking the store's stale-quote/API-unreachable flags, which could make an old quote look current.
- Candle history was loaded after symbol/timeframe/range changes only. A missed bar during API or stream loss could remain absent after recovery.
- Existing zoom, latest-bar following, viewport persistence, marker sizing and symbol scoping were already present; this change reuses them.

## Changes

- Reject chart quote updates while the quote is stale or the API is unreachable.
- Mark stale/no-quote/unreachable feed state in the existing feed badge and provide a Thai tooltip explaining that the shown chart may be historical.
- On confirmed WebSocket/API/quote recovery, debounce a silent candle-history reload. A request ID prevents superseded history responses from replacing a newer symbol/timeframe/range selection.
- Preserve the existing candles if a silent refresh fails; show an error when no candles are available.
- Add helper tests for recovery detection and stale quote suppression.

## Verification

- `npm run test:chart-viewport`: **9 passed, 0 failed**.
- `npm run build`: **passed**, Vite 8.3.8, 666 modules transformed.
- GitHub Actions Gate **#185 passed** on code commit `b6a2369d9bbeb83c4a4e9bf702508bb9515d6dcc`; Draft PR [#72](https://github.com/danaikointa-maker/Ai-Trading-Pro/pull/72) targets the U08 feature branch while PR #71 remains open.
- `git diff --check`: **passed**.
- Gate #186 found a session-scoped simulated-feed race in the existing API stale-quote regression. The test now freezes the simulator tick around that assertion; the targeted regression passed locally (**1 passed**). Full GitHub Actions Gate **#187 passed** on `de48308fe259ac8e07ca0738971541ea50c97059`. This test stabilization changed no production behavior.
- No MT5 account, broker setting, Auto mode, order, or Cloudflare/VM configuration was changed.

## Acceptance still outstanding

- Authenticated desktop/mobile screenshot review: **NOT TESTED** (no authenticated app session was available in this turn).
- Live MT5/Publisher stale-to-fresh recovery and bar-gap reconciliation: **NOT TESTED**.
- Real Demo order behavior: **NOT TESTED / not in scope**; no order was sent.

U09 remains **PARTIAL** until the outstanding runtime acceptance is recorded.

## Score-update chart scale stability (2026-11-24)

### Gap

- Every live score/version update redraws the analysis overlays. The old implementation recreated Support/Resistance, Fibonacci and market-structure levels as `PriceLine`s attached to the candle series. Those lines share the candle price scale, so a newly reported distant level can stretch the visible candle range.
- Latest-bar follow also reapplied `autoScale: true`; a new bar or chart resize could therefore undo a user's manually selected vertical zoom.

### Changes

- Draw analysis levels on the existing non-interactive overlay canvas, using the chart's current price-to-coordinate mapping. The overlay cannot contribute prices to chart auto-scaling; full-width lines, labels and line styles remain visible.
- Make latest-bar follow update only the horizontal time range. The explicit **Fit All** action remains the user-controlled path that restores automatic price scaling.
- Reset automatic price scaling only when the selected feed/symbol/timeframe changes; a same-view score refresh or reconnect keeps the user's chosen scale.
- Added focused helper tests for horizontal-only follow, plot-width bounds and the supported line styles.

### Verification

- `npm run test:chart-viewport`: **12 passed, 0 failed**.
- `npm run build`: **passed**, Vite 8.3.8, 666 modules transformed.
- `git diff --check`: **passed**.
- No MT5 account, order, Auto setting, broker, Cloudflare tunnel, VM service or runtime was changed.

### Acceptance still outstanding

- Authenticated visual review of manual vertical zoom during score updates and chart resize: **NOT TESTED**.
- Live MT5 publisher stale-to-fresh recovery and missed-bar reconciliation: **NOT TESTED**.

U09 remains **PARTIAL** until desktop/mobile visual and live-feed acceptance evidence is collected.

## Base consolidation (2026-11-24)

- U08 PR #71 merged into the V4 planning branch as `fd17eee`. U09 was rebased onto the current `plan/unified-development-v4` base after that merge; its diff now contains six U09 files and no duplicate calculator files.
- Post-rebase local checks: chart viewport **9/9**, stale-quote API regression **1/1**, Vite build **666 modules**, Ruff E9/F/I, compileall and `git diff --check` passed. GitHub Actions Gate **#194 passed** on rebased commit `6284da60001d98b978e93116dcfaa54696a1130a` (full tests, dashboard build and real-Redis checks).
- Read-only browser inventory found Chrome open to its Settings page, and the browser access host was unavailable; no authenticated Trading Pro page was accessible. MT5 was not running. Authenticated desktop/mobile visual review and a real MT5 stale-to-fresh recovery therefore remain **NOT TESTED**. No UI control, account, tunnel, publisher, broker or order was changed.
