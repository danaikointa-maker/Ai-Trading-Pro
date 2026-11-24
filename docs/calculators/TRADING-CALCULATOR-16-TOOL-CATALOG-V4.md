# Trading Calculator & Learning Center — 16-tool catalog (V4)

Status: **partial implementation**. Tools 1, 2, 4, 5, 6, and 12 have read-only/sandbox UI and shared backend math. The other tools, full exports, and lessons are not implemented. No calculator may call an order, modify, or close endpoint.

## Shared rules

- Reuse `TradePlanner`, `points_calculator`, `SymbolSpec.pnl_in_account_currency`, the existing analysis snapshot, Risk Engine read models, and backtest/replay code. Do not add a second arithmetic engine in Vue.
- Inputs may come from `LIVE_MT5`, `RISK_PROFILE`, `AI_SIGNAL`, or `MANUAL`. Every imported value carries source, account/broker scope where applicable, unit, and capture time. Manual values stay in a sandbox and never write to Risk Profile or trading state.
- Never expose MT5 credentials to the browser. Enforce the current user's account ownership for balance, equity, signals, and positions. Reject stale/incomplete specifications and suppress monetary output when currency conversion is unknown.
- Use broker `tick_size` for prices, account currency for money, and decimal-safe calculations. Distinguish estimates from broker-confirmed values. No calculator can approve an order or bypass confirmation and Risk Engine.
- Each tool needs an input form, result, reset, copy/export, formula, beginner explanation, source label, risk warning, and optional comparison/visualization. Saving and exports remain separate from live trading configuration.

## Catalog

| # | Group / tool | Main inputs | Core result / calculation | Reuse and current evidence |
|---:|---|---|---|---|
| 1 | Capital & risk — Position Size / Lot | Equity, risk %, entry, SL, symbol spec, account currency | Maximum legal lot at or below the risk budget, using adverse P/L at SL and broker lot min/max/step | First read-only manual sandbox version reuses the shared calculator endpoint and `SymbolSpec`; known spread/commission are included and below-minimum budgets are rejected. MT5 account/spec comparison, entry-price constraints and remaining acceptance are NOT TESTED |
| 2 | Capital & risk — Risk Reward | Entry, SL, TP, side, volume, spread, commission | Gross RR and net RR after known costs; show risk and reward in account currency | Implemented as a manual sandbox via `risk_reward_calculator`; uses symbol spec, typical spread and commission; slippage/swap excluded; not an order plan |
| 3 | Capital & risk — Auto SL/TP | Entry, side, closed M5 ATR, confirmed swings/zones, broker constraints | Fixed / ATR / Structure / ATR+Structure candidates, lot-at-risk, RR and blocking reasons | Reuse `TradePlanner`; V4 ATR+structure profile is inactive and must remain so without migration approval |
| 4 | Capital & risk — Drawdown & Recovery | Balance/equity/peak, loss %, recovery target | Drawdown from peak and gain needed to recover: `loss / remaining_equity` | Implemented as manual-only arithmetic; does not read simulator or broker equity |
| 5 | Price & costs — Point / Pip / Tick Converter | Price delta, point, digits, tick size | Point distance, price delta, and legal tick count; a tick is not assumed to equal a point | Implemented using declared/broker `SymbolSpec`; fractional tick counts are explicitly marked unaligned |
| 6 | Price & costs — Profit & Loss | Side, entry/exit, lot, symbol spec, account currency | Gross broker-aware P/L plus separately itemized known costs and net estimate | Implemented by reusing `points_calculator`; unresolved FX suppresses monetary output |
| 7 | Price & costs — Spread / Commission / Swap | Bid/Ask, volume, commission, swap mode/rates, holding nights | Spread cost, commission, swap estimate, and total known cost by account currency | Reuse broker `SymbolSpec`; identify excluded slippage and unknown broker charges |
| 8 | Price & costs — Margin / Leverage | Side, symbol, lot, price, leverage, equity/free margin | Estimated required margin and projected free margin; never label margin as maximum loss | Prefer MT5 `order_calc_margin`; unavailable or stale values are marked NOT AVAILABLE, not guessed |
| 9 | AI & strategy — 100-Point Confirmation | Side, reference Bid/Ask, current price, broker point, closed M1/M5 context | Threshold `100 × point`, directional progress, and confirmation blockers | Reuse the existing confirmation state/read-only readiness; reaching 100 points alone is not order approval |
| 10 | AI & strategy — ATR & Volatility | Closed bars, period, symbol price/point | ATR in price and points, ATR/price %, volatility label with timeframe | Reuse analysis snapshot; only closed bars and source timestamp are accepted |
| 11 | AI & strategy — Support & Resistance | Analysis snapshot, timeframe, zones and quality | Nearby support/resistance distances and zone quality/confluence | Reuse existing zone builder/snapshot; do not recompute or promote candidate zones to confirmed |
| 12 | AI & strategy — Break-Even Win Rate | Gross reward, gross loss, estimated same-currency cost per trade | Required win rate for zero expectancy: `net loss / (net win + net loss) × 100` | Implemented as a manual sandbox; cost is applied to both winning and losing outcomes; non-positive net reward is unavailable; not a forecast |
| 13 | Planning & education — Trading Scenario Simulator | Manual/demo-only entry, SL/TP, outcomes, costs, sample size | Hypothetical outcome distribution and expectancy; no broker actions | Reuse sandbox/backtest primitives where appropriate; never label a scenario as historical backtest |
| 14 | Planning & education — Capital Growth Simulator | Starting capital, risk/return assumptions, number of periods | Compounded illustrative range using explicit user assumptions | New sandbox calculation; show drawdown and losing-streak examples, not a return prediction |
| 15 | Planning & education — USD / THB Converter | Amount, currency pair, timestamped rate/source | Converted estimate with rate timestamp and provenance | Reuse the existing FX rate resolver when available; no fixed USD/THB assumption |
| 16 | Planning & education — Trade Review & What-if | Owned closed trade, actual fills/costs, isolated what-if values | Compare actual result with explicit alternate SL/TP/entry assumptions | Reuse owned trade/history and sandbox calculator; hypothetical values cannot alter trade records |

## Source selector and display levels

- `LIVE_MT5`: read broker snapshot through the backend; verify account identity and freshness on each refresh.
- `RISK_PROFILE`: show the effective profile and version without editing it from a calculator.
- `AI_SIGNAL`: select an owned signal and display its original reference/plan with provenance.
- `MANUAL`: editable sandbox only. If a live update arrives while the user has edited manual values, retain their draft and offer an explicit refresh.
- Beginner view shows essential fields and a short Thai answer to “what does this mean?”, “where did it come from?”, and “what changes if I adjust it?”. Intermediate adds custom assumptions and comparisons. Professional adds full broker specs and replay evidence.

## Acceptance and tests

- Unit and API tests for every calculator: BUY/SELL symmetry, point/tick/contract variation, min/max/step lot, zero/invalid distances, low equity, spread/commission/swap, insufficient margin, stale or offline MT5, unknown FX, NaN/Infinity, and currency precision.
- Ownership tests prove one account's equity, history, signal, and saved scenario never appear for another account. Manual overrides never mutate profile, orders, or positions.
- Source tests prove every value is labelled with provenance/time and that stale values are refused. Broker-aware comparisons use an explicitly authorized Demo receipt and never send a trading request.
- UI tests cover reset, copy/export totals, refresh while editing, Thai formatting, desktop/mobile, access control, and no order/modify calls.
- Learning quizzes and scenario exercises are simulation-only and must never be presented as broker results.

## Implemented slice boundary

`GET /api/risk/calculator` is extended; no new database/table or account-balance read is added. The UI has a source label, reset, JSON copy, formulas/help text and manual-sandbox inputs. PDF export, save-scenario features, learning lessons, account-owned live values, MT5 margin calculation and tools 3, 7–11, 13–16 remain queued separately under U08 and subject to the shared read-only boundary above.
