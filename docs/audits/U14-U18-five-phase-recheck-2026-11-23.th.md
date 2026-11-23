# U14–U18 — TradingView Intelligence five-phase recheck

วันที่: 2026-11-23 (Asia/Bangkok)
Plan: Unified Master Plan V4 / Task Register U14–U18
Baseline: planning branch `7cee568`
Feature commit: `109fa50`

## Scope and implementation review

| Phase | Result | Evidence and remaining gate |
|---|---|---|
| U14 — contract | DONE for local contract scope | Strict `ai-agent-lens/v1` Pydantic packet, explicit symbol mapping, UTC close time, OHLC/range/enum checks, pinned upstream sample and non-executable normalization. Upstream MIT attribution is recorded. Pine compiler and Bar Replay are release gates, not represented as passed. |
| U15 — secure adapter | PARTIAL | Reuses the API gateway and SQLite. Ingress is disabled by default; requires a dedicated body credential and exact symbol map; applies a 64 KiB body cap, rate-limit bucket, dedupe and bounded retention; never stores token/raw packet/trade map. HTTPS termination, proxy body-log redaction, real secret-manager rotation and shared multi-worker rate limiting remain NOT TESTED. |
| U16 — shadow comparison | PARTIAL | Authenticated read-only latest endpoint compares only exact canonical symbol, timeframe and candle-close matches. Lens and No7 scores remain separate. Historical no-lookahead replay and cost-aware discrepancy/outcome analysis remain NOT TESTED. |
| U17 — visualization | PARTIAL | Collapsed read-only panel built with source, mapping, timeframe, UTC close time, freshness and separate scores. Authenticated browser screenshot, role matrix and desktop/mobile visual acceptance remain NOT TESTED. |
| U18 — validation/release | BLOCKED | Pine alert chronology/repaint, historical replay with spread/fees/slippage, load/performance, Paper failure/reconnect and rollback rehearsal are outstanding. Demo needs separate explicit authorization. Live remains OFF. |

Review found `LensLevels` could accept positive infinity during schema validation. Added `allow_inf_nan=false` to that nested model and extended the contract regression; the normalizer already refused non-JSON finite values before persistence.

## Validation receipts

- Focused contract, ingress, persistence, API and rate-limit suite: **73 passed**, 1 existing Starlette/httpx deprecation warning.
- Dashboard build: **Vite 5.4.21, 625 modules — PASS**.
- Ruff `E9,F,I`, `compileall`, and diff check against the current planning base: **PASS**.
- Upstream fixture pinned to `f1aa6ce185f943f1e825f638c10b1201ef0e1e0a`; fixture is sample contract data only, not market data or a trade instruction.

## Safety and rollback

- `NO7_TRADINGVIEW_ENABLED` remains `false` by default. No staging/API/Cloudflare route, trading profile, MT5 session, order, Demo, or Live setting was changed.
- TradingView evidence is advisory only; it cannot change MT5 quotes/specs, signal approval, Risk Engine, Auto state or Execution Gateway behavior.
- Roll back by reverting this feature PR. Keep any created `tradingview_evidence` rows/table during application rollback; do not delete user evidence as part of rollback.
- `vm100/README.md` is an operational handoff plan only. It does not confirm DNS, Cloudflare, staging, or host readiness.
