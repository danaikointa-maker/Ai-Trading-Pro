# U03 — Versioned Risk Profile Candidate

## Status

**PARTIAL / NOT ACCEPTED.** `config/risk.yaml` remains the executable source of
current values. The new `config/candidates/conservative_v4_risk.yaml` is design
data only; `Settings` and `RiskEngine` do not load it. No migration, runtime
override, broker action or trading behavior was changed.

## Gap analysis

| Control | Legacy executable profile | V4 candidate | Current contract |
|---|---:|---:|---|
| Risk per trade | 0.50% | 0.50% | `RiskLimits` supports this |
| Daily loss stop | 2.00% | 2.00% | `RiskLimits` supports this |
| Weekly loss stop | 5.00% | 4.00% | `RiskLimits` supports this |
| Peak drawdown stop | 10.00% | 8.00% | `RiskLimits` supports this |
| Concurrent trades | 1 | 1 | Generic count supported |
| Concurrent XAUUSD positions | 1 per symbol | 1 | Generic per-symbol count supported |
| Minimum net RR | 1.30 | 1.50 | Field exists; cost-quality needs broker evidence |
| Aggregate open risk | No hard ceiling | 1.00% proposed | **Not enforced** by current `RiskLimits` |
| Trades per day | No dedicated count limit | 5 proposed | **Not enforced**; weekly count exists instead |
| Initial stop/target | ATR/structure + adaptive targets/ladder | Structure + 1.5 ATR M5, single 2R | Candidate semantics not represented by one existing setting |
| Partial closes | Enabled, 40/30/30 | Disabled | Legacy retained; candidate is not active |
| Automatic position modification | BE/trailing configured on | Off | Configured rules do not prove broker execution |

The candidate separates existing schema-compatible values from policy proposals
that the current runtime cannot enforce. It intentionally does not introduce
new engine fields or claim that unsupported values are effective controls.

## Precedence and migration

Current order of authority is broker/account/legal restrictions, the vetted
Risk Engine ceilings, strategy, symbol and position preferences. `config/risk.yaml`
remains `legacy_v1`; the candidate never overrides it. No automatic migration
is provided. To roll back this documentation candidate, remove its file and
report; the executable configuration remains unchanged.

## Evidence and remaining acceptance

- Automated profile tests: candidate/legacy values and runtime isolation are
  checked by `tests/test_v4_risk_candidate.py`.
- Risk Engine regression suite: existing `tests/test_risk_engine.py` remains
  unchanged and must continue to pass.
- Candidate activation, Paper A/B comparison and Demo: **NOT TESTED**.
- Before acceptance, define/enforce aggregate-risk and daily-trade controls in
  the existing Risk Engine without weakening any current gate; then validate
  broker-aware sizing and post-cost RR against real Demo symbol specifications.
- U02 still awaits Paper replay and U01's post-change bridge snapshot; this
  candidate does not consume live data and does not unblock U02/U05.
