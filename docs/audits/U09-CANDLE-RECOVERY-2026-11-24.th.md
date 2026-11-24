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
