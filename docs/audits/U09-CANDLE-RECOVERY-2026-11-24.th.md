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
- `git diff --check`: **passed**.
- No MT5 account, broker setting, Auto mode, order, or Cloudflare/VM configuration was changed.

## Acceptance still outstanding

- Authenticated desktop/mobile screenshot review: **NOT TESTED** (no authenticated app session was available in this turn).
- Live MT5/Publisher stale-to-fresh recovery and bar-gap reconciliation: **NOT TESTED**.
- Real Demo order behavior: **NOT TESTED / not in scope**; no order was sent.

U09 remains **PARTIAL** until the outstanding runtime acceptance is recorded.
