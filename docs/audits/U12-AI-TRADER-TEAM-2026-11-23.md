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
2. Keep U12 PARTIAL until this design receives an independent security review and
   any implementation proves the data boundaries and no-duplicate-engine contract.
3. Continue only with the next unblocked item in the Unified Task Register; do not
   invent additional phases outside V4.

## U12 design follow-up — proposed boundary, not implemented

This proposal would reuse the existing authenticated `/api/explain`,
`TradeExplainer`, `AnalysisSnapshot`, `Signal`, `TradePlan` and forecast. The
current explain route does not pass a Risk Engine read model; a future Risk
Officer may read one only through an existing authorized read-only interface,
and must report it unavailable until that interface is verified. It does not
add a second signal/risk/position engine, broker connector, execution API, model
tool, persistence table or Auto switch.

| Officer role | Reads and reports | Must not do |
|---|---|---|
| Market Data Steward | Existing quote source, freshness, timestamp basis and missing-data state | Replace MT5 price/specs or relabel stale/simulated data as live |
| Structure Analyst | Existing trend, indicators, confirmed zones and structure from the canonical analysis snapshot | Recompute a second indicator/structure engine or promote candidate zones |
| Signal Analyst | Explain the existing StrategyEngine action, score, reasons and blockers | Create/change a signal, signal score, entry, lot or target |
| Risk Officer | Explain the existing account-scoped Risk Engine result and blockers when that read model is available | Approve, waive or edit a veto, risk limit, account or position |
| Desk Chair | Summarize agreement, disagreement, uncertainty and cited fact IDs from the same snapshot | Average officer votes into a new trade score or authorize an order |

The orchestrator should be deterministic and pass one immutable, bounded fact
packet to the existing text-only model. Each officer response is advisory text
with role ID, model/prompt version, source fact references, source timestamp and
freshness. Missing Risk Engine/account context must be reported as unavailable;
the model must not infer it. Every request is resolved server-side for the
authenticated user's authorized workspace and selected account. Do not put raw
login, credentials, terminal paths, private position tickets or another
account's balance/history into model context. If account scope cannot be verified,
do not generate an account-specific officer response.

Manual and Semi-Auto officer output is advisory and does not remove the existing
user confirmation step. In Auto mode, only an already configured deterministic
rule may enter the existing StrategyEngine → confirmation/freshness → RiskEngine
→ ExecutionGateway → Windows MT5 path. Officer text, disagreement, or an LLM
response cannot create/alter that rule, enable Auto, call execution, retry an
ambiguous command, or override RiskEngine. Auto remains OFF by default and Live
remains separately locked.

Before implementation, extend or reuse the existing audit trail with a sanitized
request ID, actor, opaque account-scope reference, snapshot/freshness reference,
officer-set and prompt version, model version, output hash, and safety outcome.
Do not persist raw prompts or secrets by default. If the existing audit table is
insufficient, propose an additive migration and retention/rollback plan before
writing code.

Required acceptance tests: account A/B isolation; feed-stale and missing-risk
context refusal; prompt-injection and order-intent handling before model calls;
model-disabled/timeout deterministic fallback; output source-reference validation;
secret and identifier redaction; role/RBAC access; and spies proving no
ExecutionGateway submit/modify/close method is called. A separate reviewer must
review prompt injection, data minimization, output handling and the runtime's
account scoping. At the date of this design (2026-11-23), officer orchestration
was not implemented. See the dated continuation below for the current candidate
and still-open independent review gates.

## 2026-11-24 continuation — deterministic read-only officer brief

- Extended the existing authenticated `POST /api/explain` response with five role cards from one allowlisted fact sheet: Market Data Steward, Structure Analyst, Signal Analyst, Risk Officer and Desk Chair. This reuses `TradeExplainer`, the existing API and existing audit table; it creates no service, agent runtime, model tool, signal/risk/execution engine, database or order route.
- Cards are deterministic and source-referenced. Each includes status, summary, fact references, source timestamp, time basis, quote freshness and analysis-quality status. Structure/signal/chair conclusions require both a fresh quote and `data_quality.ok=true`; stale or unverified analysis suppresses them. The Risk Officer always reports unavailable until an authorized Risk Engine read model is added. `account_specific` and `execution_capability` are false; no balance, login, position, ticket, user question or raw prompt is included in the officer packet.
- The existing `/api/explain` text answer remains separate and can use the optional local LLM; order-intent refusal still returns before the model call. Officers cannot change Manual/Semi/Auto, create or alter strategy rules, approve Risk Engine, call ExecutionGateway or issue MT5 commands.
- Audit uses the existing table and stores request ID, a tenant/workspace/broker/symbol runtime-scope hash (not a verified broker-login identity), source time/freshness, officer version, output hash and fixed safety outcome. It does not store the raw question or prompt.
- Independent source review found that the unscoped runtime signal could carry account-derived lot/risk/expected-value numbers and raw risk blocker text into the fact sheet and deterministic answer. This is now redacted from `/api/explain` facts and LLM context; only stable blocker codes and market-level entry/SL/TP/RR remain. The endpoint still has no selected-account authorization, so this does not prove account A/B isolation or enable account-specific risk summaries.
- The route-level regression also exercised the existing deterministic answer with a real `TradePlan`; it exposed that `tp_points` contains numeric values, not target objects. The formatter now reads the declared numeric values, so a valid planned signal no longer raises an attribute error in `/api/explain`.
- Vue ExplainPanel shows the read-only cards and source refs. It is a text-card surface, not a virtual-office character implementation.
- Recheck after unscoped account-sizing redaction: API/account/workspace/auth/rate-limit regression **85 passed** (includes 10 U12 tests and SPA deep-link smoke); dashboard Vite 8.3.8 build **666 modules**, chart viewport **7 passed**; Ruff E9/F/I, compileall and `git diff --check` passed. One existing Starlette/httpx deprecation warning remains. The broader default Ruff rules also report existing FastAPI `Depends` B008 findings and SIM114 in unchanged observability logic; these are outside the selected repository lint gate.
- **U12 stays PARTIAL.** Independent prompt/data/account-boundary security review, true account A/B identity isolation, VM100 Office API/service identity and end-to-end Windows↔VM100 connectivity remain NOT TESTED. No Auto/Live or broker action was changed.
