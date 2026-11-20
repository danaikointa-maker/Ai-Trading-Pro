# U04 — Initial SL/TP Planner Gap Analysis

## State

**PARTIAL / NOT ACCEPTED.** Existing `TradePlanner` remains the single planning
source; no second SL/TP engine was created. An opt-in `PlanInputs` flag now
supports outward tick normalization for SL/TP. It defaults to `false`, so
legacy plan output is unchanged. The candidate profile is not read by runtime.

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

1. Structure stop selection currently chooses the *nearest* valid structural
   candidate and widens it to a volatility floor. The candidate asks for enough
   room to satisfy both the ATR reference and structure distance; encode this
   explicitly behind a versioned candidate profile, never by silently changing
   the legacy result.
2. Structural buffer is hard-coded to 0.35 ATR in `_stop_from_structure`, while
   the earlier proposed dynamic profile specifies 0.20 ATR. This needs a named
   input and defaults that preserve legacy behavior.
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
6. The runtime has no accepted V4 mode that guarantees single 2R target,
   partials off, ATR(14) from a closed M5 bar and 10-bar swing provenance.
   `AnalysisService` already passes closed M5 frames for structure, but these
   exact inputs need explicit tests before they can be called verified.

## Test evidence

`pytest tests/test_invariants.py tests/test_spec_safety.py
tests/test_v4_risk_candidate.py tests/test_v4_plan_candidate.py
tests/test_risk_engine.py tests/test_risk_state_failure.py
tests/test_smart_entry_continuation.py -q` — **80 passed**.
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
4. Add candidate ATR+structure / single-2R policy tests, min-lot and cost cases.
5. Verify `order_check`, margin, stops/freeze levels and post-fill SL/TP only
   through the existing ExecutionGateway and an explicitly approved Demo.

No LIVE order, broker action, profile activation or migration occurred. U04 is
not complete; this audit merely clarifies the implementation boundary.
