# 04 — Professional Trader Dashboard UX Specification

## Design language
Modern institutional trading terminal: controlled dark palette, high contrast data density, clear typography (Thai/English), responsive 1440p/1080p/tablet/mobile, keyboard navigation, non-color indicators for BUY/SELL, WCAG contrast. Avoid neon overload, animated background, distracting particle FX, or excessive cards. Show data provenance, timestamps, market/session status prominently.

## Desktop layout
Top: symbol/account selector, SIMULATED/REPLAY/BROKER flag, demo/live lock, connection state, latency, London/New York session, UTC/Bangkok clocks, market status.
Left: watchlist symbols/markets and multi-timeframe trend matrix.
Center (largest): price chart with candles, volume, VWAP, EMA, confirmed/candidate S/R, BOS/CHoCH, entry/SL/TP, adjustable risk-reward overlay; synchronized crosshair and broker data freshness.
Right: AI Forecast scenario ranges (P10/P50/P90 with calibration status), strategy checklist, confidence vs heuristic score explicit, risk veto reasons, proposed plan only, human approval.
Bottom: open positions, orders, deals, journal, event logs, bridge health, unresolved incidents, paper/demo P&L and execution receipts.

## Pages (retain existing 10-page Vue routing)
- Terminal: trading center, live chart and risk overview.
- Forecast: time horizons, scenario fan, calibration and OOS model validity.
- Zones: 3+ confirmed levels if supported by evidence; no invented levels.
- Trades: open/closed orders, fills, realized cost, partials, reconciliation.
- Risk: immutable veto reason list, exposure heatmaps, kill switch, broker spec.
- Backtest: frozen dataset, OOS walk-forward, costs and robustness.
- Journal: complete trade lifecycle + AI postmortem and proposed experiments.
- Brokers: broker source, symbol specs, connection status, account mode.
- System: Proxmox/VM health, API/EA heartbeat, queue/DB, backup restore age, disk errors.
- Add Agent Lab route later: candidate models/champion/shadow comparison, review queue, promotions.

## Critical safety UX
Show large persistent DEMO/PAPER/LIVE state, source badge, stale quotes, model unvalidated status, news lockout, risk veto and disconnect status. Never show green 'connected' when quote is stale. Default CTA is 'Review Plan' (not one-click BUY). Trading buttons remain disabled until account identity, kill switch and risk gate pass and operator approval is recorded.

## Implementation guidance
Extend `apps/web-dashboard/src/components` and existing `src/views`, keep API compatibility. Design tokens CSS custom properties, central Store, typed contracts as desired, error/empty/loading states, mobile constraints. Use synthetic preview data with SIMULATED badge and make it impossible to misidentify as real quotes.
