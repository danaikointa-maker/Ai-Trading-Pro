# U08 Follow-up — Trade Review, Saved Scenarios, Exports and Learning

Date: 2026-11-24
Branch: `feature/u08-calculator-tools-20261124`
PR: #71, Draft, targets `plan/unified-development-v4`

## Scope and result

| Slice | Result | Remaining acceptance |
|---|---|---|
| Tool 16 — Trade Review / What-if | **PASS (local contract)** — reuses the active adapter trade list, existing `TradeRecord`, current account identity/owner record, `risk_reward_calculator`, and `profit_loss_calculator`. Recorded fills/costs/swap/net P&L are separate from hypothetical entry/SL/TP and the result is explicitly non-executable. Foreign broker ticket returns 404; mismatched active-account owner returns 409. | **NOT TESTED** with a connected MT5 account. It does not replay price bars or estimate which level would have hit first. |
| Manual scenario save/load/delete | **PASS (local API)** — persists numeric `scenario` and `capital_growth` inputs in existing `kv`, namespaced by workspace, tenant and normalized user email. Rejects unsupported fields, non-numeric/non-finite inputs, unsupported tools, and names outside the allowed length. User-isolation and delete-boundary tests pass. | Multi-worker/production database deployment acceptance **NOT TESTED**. |
| JSON / CSV result export | **PASS (frontend helper)** — retains nested evidence for JSON and quotes CSV fields; formula-like text is neutralized while numeric negative P&L remains numeric. | Browser download confirmation **NOT TESTED**. PDF export was added in the 2026-11-24 follow-up below. |
| Beginner learning center | **PASS (local UI build)** — five short Thai lessons on risk, R:R, costs, drawdown and the limits of simulation, each with a one-question quiz. | Authenticated visual/usability review on desktop and mobile **NOT TESTED**. |

## Safety and account boundary

- No new calculator engine, database table, account flow or execution endpoint was added. Saved assumptions are isolated by current workspace, tenant and user; they are not linked to broker accounts and contain no balance, positions or credentials.
- What-if fetches a closed trade only when its `broker_id` is the active adapter, checks the stored account owner against the current gateway account identity, rejects unresolved or mismatched identity, and returns actual results separately from manual assumptions.
- The what-if route uses the existing read-only Risk Engine calculators. No `submit`, `modify`, `close`, `order_check` or `order_send` call is made. What-if does not rewrite trade history and does not claim a candle-level path simulation.
- No MT5 Demo/Live account was switched, no broker command was sent, no Auto state changed, and nothing was deployed or merged.

## Verification evidence

Python command:

```powershell
python -m pytest tests\test_v4_plan_candidate.py tests\test_calculator_tools_v4.py tests\test_points_math.py tests\test_swap.py tests\test_analysis_atr_validity.py tests\test_api.py tests\test_mt5_order_preflight.py tests\test_signal_confirmation_v4.py -q
```

Result: **161 passed**, one existing Starlette/httpx `TestClient` deprecation warning. Added API coverage for manual scenario CRUD and user isolation, forbidden inputs, What-if actual-vs-manual separation, missing/cross-broker tickets, active-owner mismatch and no execution gateway calls.

Dashboard checks in `apps/web-dashboard`:

```powershell
npm run test:calculator-export
npm run test:calculator-analysis
npm run test:chart-viewport
npm run build
```

Results: exports **2 passed**; calculator analysis **2 passed**; chart viewport **7 passed**; Vite 8.3.8 build passed (**666 modules**). Ruff E9/F/I and Python `compileall` passed after cleanup; `git diff --check` passed. GitHub Actions **Gate #183 passed** for head `34b59d8f0f5e8e392ba32bdbdeaf481f915ab095`.

## Remaining U08 gates

U08 stays **PARTIAL** until authenticated desktop/mobile visual review, connected Demo history review, and real MT5 margin comparison are recorded. The earlier U08 slices were merged via PR #71 as `fd17eee`; this PDF follow-up is isolated from runtime configuration. Rollback is a revert of the implementation commit, with no live profile or persisted trading state changed.

## Browser-native PDF export follow-up (2026-11-24)

- Branch: `feature/u08-pdf-export-20261124`.
- Added a compact **PDF** action beside JSON/CSV in the existing calculator toolbar. It opens a self-contained printable result page; the user can choose the browser's **Save as PDF** destination. It does not send the report to a server.
- Escapes every payload field and value before embedding it in the printable HTML. The report preserves the selected tool, result, symbol and provenance and labels the content as calculation/review only—not an order, Risk Engine approval or guaranteed result.
- Reuses the existing calculator export module and current `copyPayload`; no dependency, API, persistence, account read or trading path was added.
- Verification: `npm run test:calculator-export` **3 passed**; `npm run test:calculator-analysis` **2 passed**; Vite 8.3.8 build **666 modules**; `npm ci` reported **0 vulnerabilities**; `git diff --check` passed.
- Browser popup/print dialog and actual PDF save are **NOT TESTED**; authenticated desktop/mobile review, real Demo history, and MT5 margin comparison are still **NOT TESTED**. No broker command or account state changed.
- Rollback: revert the follow-up commit. No schema/config migration or runtime deployment is involved.
