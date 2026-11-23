# U06–U10 Regression and Dashboard Dependency Recheck

Date: 2026-11-23
Base: `plan/unified-development-v4` at `14a7be593f71c876aabcf22ddc9089778fad6528`
Scope: local source regression and dashboard dependency remediation. No VM deployment, broker/account action, Auto activation, Demo order, or Live order.

## Results

| Task | Local result | Remaining acceptance |
|---|---|---|
| U06 Position protection | PASS: PositionManager → ExecutionGateway → PaperBroker lifecycle, intent reconciliation and failure-path regression are included in the 478-test suite | PARTIAL: U05 stage parity/recovery and broker Demo protection lifecycle remain NOT TESTED |
| U07 Operating modes | PASS: role and Risk Engine authorization regression | PARTIAL: Manual/Semi/Full/Hybrid position-protection modes and versioned account overrides remain incomplete; no Auto state changed |
| U08 Calculators | PASS: math/API/spec and account-ownership regression | PARTIAL: remaining calculator flows, save/export and learning-center content are NOT IMPLEMENTED |
| U09 Dashboard | PASS: clean install, build, chart viewport and UI smoke; npm audit reports zero vulnerabilities | PARTIAL: authenticated desktop/mobile visual acceptance, fresh-feed behavior and reconnect review remain NOT TESTED |
| U10 Alerts | PASS: notification dedupe/outbox, delivery, restart and ownership regression; prior hosted Gate #156/PR #53 evidence remains valid | DONE; no external notification sent during this recheck |

## Verification evidence

- Sequential focused Python regression over PositionManager, modify-intent/execution, roles/Risk Engine, calculator/API, dashboard UI, notification, and account/history ownership: **478 passed**, one pre-existing Starlette/httpx deprecation warning.
- First local attempt had 476 passing tests and two environment-dependent failures because this isolated worktree had no built `dist` and no `node_modules`; after clean dashboard installation/build, those same UI tests passed (**2 passed**) and the entire Python regression passed (**478 passed**).
- Dashboard `npm ci`: PASS; 117 packages audited, **0 vulnerabilities**.
- Vite 8.3.8 production build: PASS, **664 modules**.
- `npm run test:chart-viewport`: **7 passed**.
- `tests/test_api.py::test_spa_deep_links_are_served` and `tests/test_positions_ui.py`: **2 passed**.
- No authenticated browser screenshot/role check or live-feed/reconnect review was performed.

## Dependency security change

Before remediation, `npm audit` reported three vulnerabilities: ECharts moderate, esbuild moderate, and Vite high. The current app registers only ECharts `LineChart`; the published ECharts advisory describes the vulnerable path in the separate `Lines` series tooltip. Nevertheless, ECharts is a production dependency and was upgraded to its patched 6.1.0 release. Vite and `@vitejs/plugin-vue` were upgraded together to 8.3.8 and `^6.0.10` (lock resolves plugin 6.0.11), respectively; package-lock was regenerated and a clean `npm ci` was verified. No `npm audit fix --force` was used.

Both ECharts components now explicitly use the V5 theme so the V6 default palette and component layout changes do not alter their prior defaults. Build and chart viewport tests pass; visual comparison in an authenticated browser remains NOT TESTED. See the [ECharts 6 upgrade guide](https://echarts.apache.org/handbook/en/basics/release-note/v6-upgrade-guide/), [ECharts security advisory](https://github.com/advisories/GHSA-fgmj-fm8m-jvvx), and [Vite migration guide](https://vite.dev/guide/migration.html).

## Safety

This change set does not activate Auto, alter Risk Engine settings, deploy to VM100, connect/switch broker accounts, or send trade/position/notification commands. U06/U07/U08/U09 stay PARTIAL pending the acceptance listed above. U10 remains DONE based on existing acceptance evidence.

## 2026-11-24 follow-up on V4 merge base `198c333625fc082a37cddba7b06520aefea8cc53`

- Rechecked the U06–U10 focused regression on a clean worktree. After `npm ci` (116 packages; 0 vulnerabilities), Vite 8.3.8 production build passed (664 modules) and `npm run test:chart-viewport` passed (7 tests).
- The selected 16-file Python suite first exposed an environment issue (no `dist`/`node_modules`) and then a flaky assertion in `test_ticker_endpoint_retains_quote_when_market_is_closed`: the session-scoped API runtime continued producing simulated ticks in a background thread while the test asserted one fixed tick. The test passes in isolation. Updated the test to hold the simulated tick constant during that assertion; no production code or runtime behavior changed.
- After the test-only isolation fix, the same selected regression passed: **300 passed**, one pre-existing Starlette/httpx deprecation warning. Ruff E9/F on `tests/test_api.py` and `git diff --check` passed.
- This does not satisfy external acceptance: U06 still needs U05 stage parity and broker Demo protection/reconciliation; U07 protection modes remain incomplete; U08 remaining calculators/learning/export remain unimplemented; U09 authenticated desktop/mobile and fresh-feed/reconnect visual acceptance remain NOT TESTED. U10 remains DONE. No VM, account, Auto, order or position was changed.
