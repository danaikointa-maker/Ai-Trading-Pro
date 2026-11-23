# U12 AI Trader Team Read-only Integration Audit

Date: 2026-11-23  
Repository: `danaikointa-maker/Ai-Trading-Pro`  
Branch: `feature/u12-ai-trader-readonly-v4`  
Base: `1742ca5df0969a5b699945b73fdf40e1cedc5bb3`

## Scope and decision

U12 is scoped by Unified Master Plan V4, W9: a separate read-only research/explanation
integration. This change extends the existing `TradeExplainer` and authenticated
`POST /api/explain`; it does not create a second agent runtime or trading subsystem.

## Gap analysis

| Area | Existing source | Finding | This change |
|---|---|---|---|
| AI interface | `integrations/no7_local_ai/client.py` | Ollama-compatible text generation only; enabled only by explicit setting; no tool/function calling | Reuse as text-only optional renderer |
| Research context | `services/strategy_engine/explainer.py` | Compact facts from existing signal, snapshot, and forecast; feed/clock provenance absent | Add allowlisted feed mode, quote freshness/source, display basis, and bounded UTC offset |
| Order intent | `TradeExplainer.explain()` | Deterministic refusal existed, but code then continued to LLM when enabled | Return the deterministic refusal before any model call |
| Execution boundary | `services/execution_gateway/` and existing trading routes | Existing single gateway is authoritative; explain route has no gateway dependency | Keep route read-only; regression test spies on submit/modify/close |
| AI officer orchestration | No current orchestrator or role/task registry found in audited paths | Not implemented by this slice | Keep U12 PARTIAL; design/review separate officers before implementation |

No new Signal Engine, Risk Engine, MT5 connector, API, database, execution route, or
agent tool was introduced. LLM output cannot approve, submit, retry, modify, or close an order.

## Changes

- `/api/explain` attaches sanitized market provenance to the same facts returned to the
  dashboard and optionally supplied to local text generation.
- Provenance is allowlisted; unknown feed/source/time labels are replaced with
  `unknown`/`unavailable`. Account identifiers, credentials, terminal paths, positions,
  and arbitrary error text are excluded.
- Detected order-intent questions return a deterministic explanation before calling the
  model. The existing endpoint has no `ExecutionGateway` dependency.
- Tests cover stale/fresh labeling, unknown metadata, allowlisted facts, model-call refusal,
  and absence of gateway method calls.

## Acceptance and verification

| Acceptance | Status |
|---|---|
| Reuse the existing read-only explainer and shared market service | PASS (source inspection) |
| Expose only bounded, allowlisted provenance | PASS (unit and route tests; see CI evidence in PR) |
| Order-intent prompt does not reach the model | PASS (mocked enabled model test) |
| Explain request does not call gateway submission/modification/close | PASS (gateway spies in API test) |
| Automated regression / lint | PASS locally: 17 targeted tests; Ruff E9/F; compileall and `git diff --check`. Hosted CI #152 passed full Gate, real-Redis proof and dashboard bundle |
| Real MT5 Demo observation | NOT TESTED; not needed for read-only code acceptance and U01 feed remains blocked |
| Multiple AI officer orchestration | NOT IMPLEMENTED; remains outside this slice |
| Live trading | NOT ENABLED; no broker or execution action performed |

## Security, config, migration, rollback

- No new configuration, migration, secret, or permission is required.
- The local AI stays disabled by default. The new prompt is informational and not an
  authorization control; HTTP auth/RBAC, Risk Engine, and ExecutionGateway remain the
  only applicable action controls.
- Rollback: revert the focused code and documentation changes in this PR. No DB or
  runtime state needs restoration.

## Follow-up queue

1. Keep U11 Demo acceptance BLOCKED pending the fresh publisher quote and a separate
   explicit operator authorization; do not send an order in this task.
2. Keep U12 PARTIAL until a reviewed AI-officer design defines non-execution roles,
   data boundaries, audit behavior, and proves no duplicated trading engines.
3. Continue only with the next unblocked item in the Unified Task Register; do not
   invent additional phases outside V4.
