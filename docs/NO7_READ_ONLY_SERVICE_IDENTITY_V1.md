# No7 read-only service identity v1 — proposal

**Status: disabled design contract.** This document does not change route
dependencies, issue tokens, configure mTLS, or enable a machine identity. The current
API continues to use the existing human-user authentication path. Keep the integration
off until a separate implementation has a deployed Keycloak/Vault configuration,
verified client-credentials certificate-bound tokens, and an approved workspace
binding.

## Identity and authorization boundary

The selected provider plan is Keycloak for OAuth client credentials and Vault PKI for
the client certificate. The initial principal is intended for the Trading Pro
`default` workspace, with audience `ai-trading-pro-read`, an access-token lifetime no
longer than five minutes, and only `market:read` and `analysis:read` scopes. The target
label `default` does not identify a tenant, project, broker, or trading workspace and
does not grant access by itself.

Before implementing token verification, prove that the deployed Keycloak version can
issue a certificate-bound access token using the client-credentials grant and the
selected X.509 client authentication method. The API must validate the signature,
issuer, audience, expiry, not-before, scope, service principal status, certificate
binding and server-side workspace mapping. A TLS-terminating proxy may supply a
certificate fingerprint only when the API has independently authenticated that proxy;
caller-controlled forwarding headers are never identity evidence.

Use a dedicated service principal and a server-side binding to exactly one active
Trading Pro tenant/project/workspace/broker tuple. Resolve that tuple from the verified
principal. Reject absent, wildcard, ambiguous, inactive or mismatched bindings and
caller-provided tenant/workspace headers. Do not create a synthetic `users` row, reuse
the human HS256 secret/token, accept a service token in a query parameter, or weaken the
existing human dependency.

## Initial route and scope map

This is an exact allowlist proposal, not a wildcard prefix. All service routes must
require both the service identity dependency and the mapped scope. Routes not listed
here remain unavailable to the service principal, including any future route added
under the same router prefix.

| Method | Exact route | Required scope | Data boundary |
| --- | --- | --- | --- |
| `GET` | `/api/market/symbols` | `market:read` | Symbol metadata for the bound workspace |
| `GET` | `/api/market/candles` | `market:read` | OHLC candles and the associated ticker/spec for the bound workspace |
| `GET` | `/api/market/ticker` | `market:read` | Current quote for the bound workspace |
| `GET` | `/api/analysis/{symbol}` | `analysis:read` | Analysis snapshot, bias and support/resistance summary |

`GET /api/system/health` remains a public health route and does not establish service
identity or workspace access. The client must not infer market authorization from a
successful health response.

Do not include `/api/market/spec`, `/api/market/specs`, `/api/market/calculator`,
`/api/analysis/{symbol}/zones`, forecast/model routes, live account/position/risk
routes, performance/equity/trade routes, or any other route unless their payloads,
scope and workspace policy receive separate review. All order, close, mode, approval,
account-write and risk-write routes are categorically unavailable to this principal,
regardless of HTTP verb or role claims.

## Implementation gates

Keep the feature disabled until a separate reviewed change supplies and validates:

1. The Keycloak issuer, realm and token endpoint; Vault PKI mount, issuance role and a
   named certificate rotation owner. Store no private key, token, or deployment secret
   in source control.
2. Evidence for mTLS client authentication and certificate-bound access tokens on the
   client-credentials flow used by the deployed Keycloak version.
3. A concrete default workspace mapping: tenant ID, project ID, trading workspace ID
   and broker ID. Reject a request when any mapping is missing or inactive.
4. A dedicated machine-auth dependency that is separate from `current_user`, and an
   explicit route-to-scope map applied only to the four routes above.
5. Negative tests for wrong issuer/audience, expired token, missing scope, certificate
   mismatch, revoked principal, missing/cross-workspace binding, tenant headers,
   query-token authentication and every write/account/risk route.
6. Sanitized deployment response fixtures and audit/logging checks proving that
   credentials, certificate material and tokens never appear in responses, logs or
   task events.

No broker connection, MT5 action, account mutation or live order is an authentication
acceptance test. A read-only integration must not influence the deterministic risk or
execution engines.
