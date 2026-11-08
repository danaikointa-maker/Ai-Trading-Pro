# Test and model validation strategy

## Technical tests (enforced CI gates)
- Unit: precision/point math, risk guards, position state, timezone-close-date, partial fills, file access, RBAC, consent withdrawal.
- Contracts: OpenAPI/Pydantic compatibility from existing `/api/*` to new `/api/v1`, bad schema rejects, idempotency, authz and expiry.
- Integration: real Demo broker specs, duplicate event receipt, restart while order UNKNOWN, 1–10 minute disconnect, wrong account, stale quote, weekend/session gaps, negative balance risk, signed screenshot URLs.
- E2E: DEV -> staging Ubuntu -> Windows Demo -> broker response -> journal/report match, clean rollback.
- Load/security: simultaneous users, per-account broker terminal quotas, rate limit, SQL/RLS isolation, secrets, CSRF, WebSocket auth, backup recovery.

## Quant/AI research quality gates
- Dataset exact snapshots/checksums; no simulated-replay mixing; trading sessions, spread/commission/slippage/swap/symbol margin rules.
- No leakage: feature timestamp <= decision cutoff, unavailable future bars excluded, walk-forward purging/embargo when label horizon overlaps, separate OOS holdout, threshold pre-registration.
- Compare champion vs candidate on realistic net expectancy and drawdown with confidence intervals / uncertainty, trade count, calibration, subgroup regimes, time periods, Monte Carlo/stress variations.
- Correct for repeated strategy search/multiple hypothesis testing and nonstationarity; paper/shadow comparison; never optimize solely win rate.
- Model registry: immutable features/data/model/code hashes, owner, purpose, quality gate, expiry, sign-off; rollback champion if drift/regime shift.
- Loss review agent outputs evidence, probable cause, alternative **hypothesis**, and validation plan; never claim next trade win is guaranteed.

## Acceptance gates
- P0: no duplicate live broker order from same intent even across restart, or explicit UNKNOWN halt and reconciliation; risk veto independent; signed authenticated API; no cross-user reads; verified restore.
- P1: chart feed state accurate, journal totals exactly reconcile to broker history, reports units labeled, experiment rerun reproducible, demo broker contract specs respected.
- Evidence must include commands, versions, logs with secrets redacted, pass/fail, issue tracking and rollback procedure.
