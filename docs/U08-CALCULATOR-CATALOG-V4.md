# U08 — Candidate calculator catalog

Status: **PROPOSAL ONLY**. This is a reviewable inventory, not a claim that all 16 tools are implemented. Keep the calculator read-only and use one backend calculation core shared with Risk/Planner. The Vue layer formats inputs and outputs only.

| # | Calculator | Inputs / source | Shared owner or gap |
|---:|---|---|---|
| 1 | Points to price distance | points, `point`, digits | `SymbolSpec`; existing math |
| 2 | Price distance to points | price distance, `point` | `SymbolSpec`; existing contract |
| 3 | Gross P/L | side, entry/exit distance, volume, contract spec | `TradePlanner.profit_at` / shared calculator; reconcile profit-currency conversion |
| 4 | Commission | volume, round-turn commission spec | `SymbolSpec`; existing spec field |
| 5 | Spread cost | current or typical spread, point value, volume | `SymbolSpec`; display actual vs typical and freshness separately |
| 6 | Net P/L estimate | gross, commission, spread, swap, slippage | Extend shared cost model; every included/excluded cost must be explicit |
| 7 | Value per point / lot | point, tick size/value, contract, conversion | `SymbolSpec.value_per_point_per_lot`; verify broker metadata |
| 8 | Lot by risk budget | equity, risk %, SL distance, cost assumptions | `TradePlanner.lot_for_risk`; enforce lot step/min/max and never exceed budget |
| 9 | Risk at proposed lot | volume, entry, SL, point value, costs | Existing planner/Risk math; fail closed on incomplete spec |
| 10 | SL/TP price from points | side, entry Bid/Ask, points, tick size | Shared planner normalization; side-aware outward rounding |
| 11 | Gross / net reward-to-risk | entry, SL, TP, cost model | `TradePlanner`; distinguish gross from net RR |
| 12 | Break-even exit price | side, entry, volume, commission, spread/swap assumptions | New shared pure function only if existing planner does not cover the exact semantics |
| 13 | ATR distance | closed-bar ATR, point, multiplier | Existing indicator pipeline + `SymbolSpec`; reject unfinished/invalid bars |
| 14 | ATR + structure SL/TP preview | closed M5 bars, swings/zones, ATR, plan profile | Existing `TradePlanner`; read-only preview, no config mutation |
| 15 | Swap carry estimate | side, volume, price, holding days, swap mode/rates | `SymbolSpec.swap_for`; clarify triple-rollover and broker calendar gap |
| 16 | Account-currency / THB conversion | profit currency, account currency, fresh FX quotes | Missing verified conversion service/source; unavailable or stale rates must fail closed |

## Common contract

- Sources must be explicit: `LIVE_MT5`, `RISK_PROFILE`, `AI_SIGNAL`, or `MANUAL`; include symbol/account scope, timestamp/freshness and currency when applicable.
- A linked-account spec is valid only after U01 verifies the terminal/account identity and symbol metadata. Runtime/simulator specs must remain visibly labeled and must never be presented as the selected MT5 account.
- Manual what-if values stay isolated from persisted risk settings. No calculator endpoint may call an order, close, modify, auto-toggle, or execution gateway.
- Margin estimation is intentionally not a calculator in this list until broker margin behavior is verified; do not present notional as required margin.
- Before implementation: review this proposed list, confirm intended scope, then implement only the tools supported by verified inputs. MT5 comparison, FX conversion, and account-currency acceptance are NOT TESTED.
