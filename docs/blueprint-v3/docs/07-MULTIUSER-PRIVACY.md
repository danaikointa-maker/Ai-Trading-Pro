# Multi-user privacy and shared learning

## Separation model
- PostgreSQL target schema: `users`, `tenants`, `memberships`, `roles`, `broker_accounts`, `strategies`, `trade_intents`, `orders`, `deals`, `trades`, `trade_images`, `reports`, `model_versions`, `agent_jobs`, `consents`, `pooled_features`, `audit_events`.
- Define tenant/account ownership for all data; service-role permissions separate from end users. API authorization on every object; DB Row-Level Security **with tests** (admin/service bypass must be explicitly reviewed); signed expiring access for images.
- Encrypt broker account secrets with managed encryption keys outside Git; audit reads/deletes/exports. Never expose other users' private balances, screenshots, tickets, names, or strategies.

## Shared intelligence — opt-in
- Personal records remain private. Central training only uses consented, minimal feature vectors (market regime, normalized entry/exit setup, R multiple, costs, timestamp buckets) after privacy review, aggregation and thresholding.
- Pseudonymization by deleting names is NOT guaranteed anonymity; maintain linkage only in separately protected consent service where needed for withdrawal.
- Risk of re-identification exists with sparse/highly specific trade data; minimum cohort size, generalization, access limits, retention, audit and privacy testing are required. Consider privacy-preserving aggregate statistics or differential privacy when feasible.
- Dataset/Model provenance logs include allowed use/purpose, dataset version and consent scope; implement withdrawal/retention policy and handle trained models per policy/legal review.

## Multi-account execution
- Distinct MT5 terminal instance and controlled executor for each **actively connected account**, with account-scoped bridge key. A single Windows VM200 with 8GB RAM and 2 vCPU is a small pilot, NOT enough to promise unlimited concurrent traders. Plan capacity tests and scale to additional isolated Windows workers when load justifies it.
- User risk limits must never be shared. Global model can be reused for general signals but decisions incorporate each account's broker contract, margin and risk policy.

## Compliance
- Define legal basis and documented user consent for learning/data retention/sharing; review applicable Thai PDPA and financial platform/broker requirements with specialists before multi-user public deployment or live order routing.
