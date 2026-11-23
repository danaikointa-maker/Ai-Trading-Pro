# U04 — Initial SL/TP Planner Gap Analysis

## State

**PARTIAL / NOT ACCEPTED.** Existing `TradePlanner` remains the single planning
source; no second SL/TP engine was created. An opt-in `PlanInputs` flag now
supports outward tick normalization for SL/TP. It defaults to `false`, so
legacy tick rounding is unchanged. An opt-in ATR+structure stop policy is also
available to direct planner callers; the candidate profile remains unloaded
from runtime settings. Its `plan_options` are recorded in the single canonical
inactive file `config/risk_v4_candidate.yaml`; no second U04 risk candidate is
maintained.

## Existing behavior

- `services/risk_engine/planner.py` builds a structural stop from support,
  resistance and confirmed swings, falls back to ATR, applies a volatility
  floor, uses broker symbol point/tick metadata, sizes volume from the risk
  budget, accounts for half spread and round-turn commission, checks net RR,
  and builds a target ladder with optional zone capping.
- `StrategyEngine.generate` supplies an ATR-derived input and risk-config
  values to the planner before its independent Risk Engine gate.
- `TradingRuntime.build_manual_plan` reuses `TradePlanner`, but supplies a
  narrower subset of the configuration than the strategy path. Both callers
  now use `build_plan_inputs(...)`, which reads the same effective RiskSettings
  snapshot and policy values; the legacy manual path now honors its configured
  ATR stop multiplier instead of the previous implicit 1.0 default.
- Existing executable profile uses structural/ATR stops, adaptive targets,
  40/30/30 partials and 1.30 minimum net RR. These settings are unchanged.

## Gaps against the V4 candidate

1. **DONE for candidate mode:** `sl_policy: atr_structure` uses the wider of
   ATR reference and most adverse confirmed swing in the configured closed-M5
   lookback. Candidate values are 1.5 ATR, 0.20 ATR buffer and 10 bars. Legacy
   mode retains its 0.35 ATR buffer and nearest structural candidate.
2. **DONE for candidate mode:** missing M5 lookback data or a missing confirmed
   swing now blocks the candidate plan instead of silently falling back to ATR.
3. `SymbolSpec.round_price` rounds to the nearest tick. A candidate-only
   normalization option now rounds BUY SL down / TP up and SELL SL up / TP down.
   Runtime callers still use the legacy nearest-tick behavior until a profile
   migration is explicitly reviewed.
4. **DONE:** Automatic and manual entry code now share `build_plan_inputs(...)`.
   Regression tests confirm the effective legacy profile and unchanged default
   nearest-tick mode.
5. The planner estimates spread and commission, but slippage, broker margin,
   stops/freeze constraints and post-fill accepted levels are not all verified
   there. These belong to the existing execution gateway / broker reconciliation
   contract and must remain a hard pre-send/post-fill gate.
6. Candidate planner support now produces one 2R broker TP, one 100% target
   record, disables manager partials for that plan and rejects opposing zones.
   Runtime profile remains inactive; post-fill broker acceptance remains
   unverified.
7. The audit found ATR buffers treated as raw price units and structural
   distances compared as prices to point thresholds. Both now convert between
   points and price using `SymbolSpec`. A high-quality opposing zone that leaves
   less than the configured minimum target now blocks planning instead of
   placing TP through the zone.

## Test evidence

`pytest tests/test_invariants.py tests/test_spec_safety.py
tests/test_risk_profile_candidate.py tests/test_v4_plan_candidate.py
tests/test_risk_engine.py tests/test_risk_state_failure.py
tests/test_smart_entry_continuation.py tests/test_v4_single_target_manager.py
-q` — **95 passed** after consolidating candidate configuration and adding
the single-candidate isolation regression.
These protect current sizing, side-correct geometry, broker tick grid, RR,
partial-volume feasibility, legacy Risk Engine vetoes and candidate isolation.
They do not establish broker Demo acceptance or validate an SL/TP order.

Candidate-only tick-normalization tests cover BUY and SELL geometry with a
0.05 tick size and verify the unchanged nearest-tick path when the flag is off.

## Safe implementation order

1. **DONE:** Candidate-only plan option exists with legacy-preserving defaults.
2. **DONE:** directional tick rounding is optional and covered for BUY/SELL;
   runtime remains on nearest rounding.
3. **DONE:** Auto and Manual construct inputs through the shared helper.
4. **DONE:** Candidate ATR+structure sizing, closed-M5 lookback, max-stop
   rejection and point/price conversion tests.
5. **DONE:** Candidate 2R target, partial-off, opposing-zone rejection and
   net-RR behavior are covered.
6. Verify `order_check`, margin, stops/freeze levels and post-fill SL/TP only
   through the existing ExecutionGateway and an explicitly approved Demo.

The candidate profile is represented only by `config/risk_v4_candidate.yaml`.
The older duplicate `config/candidates/conservative_v4_risk.yaml` was removed;
candidate isolation is regression-tested and `config/risk.yaml` remains the
runtime source.

No LIVE order, broker action, profile activation or migration occurred. U04 is
not complete; this audit merely clarifies the implementation boundary.
