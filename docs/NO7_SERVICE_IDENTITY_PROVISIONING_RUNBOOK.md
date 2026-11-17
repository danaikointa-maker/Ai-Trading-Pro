# No7 read-only service identity provisioning runbook — draft

**Status: preparation only.** Keycloak and Vault PKI are not provisioned yet. This
runbook is an operator checklist, not evidence that a realm, PKI mount, role, client,
certificate, or Trading Pro service identity exists. It does not install software,
issue credentials, enable runtime authentication, or authorize a broker action.

Use this with [the disabled service identity proposal](NO7_READ_ONLY_SERVICE_IDENTITY_V1.md).
Do not paste tokens, client secrets, Vault tokens, private keys, or full certificates
into GitHub, tickets, chat, CI logs, or this repository.

## 1. Record deployment facts (no credentials)

The operator records these values in the approved deployment inventory, not in a
committed environment file:

- Keycloak exact version/build, HTTPS issuer URL, realm, and OIDC token endpoint.
- Whether Keycloak is directly TLS-terminated or sits behind a proxy; identify the
  trusted proxy and how it strips untrusted certificate-forwarding headers.
- Vault exact version, PKI mount path, signing role, CA/issuer owner, and certificate
  rotation/revocation owner.
- The concrete default workspace binding: tenant ID, project ID, trading workspace
  ID, broker ID, and the operator who approved it.
- Where the API terminates client TLS, which CA chain it trusts, and how certificate
  revocation/expiry is enforced.

`default` is only the requested workspace label. It is not a workspace ID and grants
no access until all four IDs above are approved and bound server-side to the service
principal.

## 2. Prepare Vault PKI issuance

1. Have the PKI owner use an approved CA hierarchy. HashiCorp recommends keeping a
   root CA outside Vault and placing a signed intermediate in the PKI engine where
   that deployment model is available.
2. Use a dedicated PKI mount or tightly scoped mount path and a dedicated signing
   role for this service. Restrict permitted subject/SAN values to the service
   identity, set an explicitly short maximum certificate TTL, and allow client
   authentication EKU only. Do not permit wildcard names or CA certificates.
3. Prefer generating the private key and CSR on the service host, then use the
   role-restricted `pki/sign/<role>` operation. The private key then stays with the
   client; do not use the broader `sign-verbatim` endpoint. If the selected workflow
   instead uses `pki/issue/<role>`, its response contains the private key: deliver it
   directly into an approved secret store or memory-only credential path and ensure
   command history, shell tracing, CI logs, temporary files, and backups cannot
   capture it.
4. Ensure the role cannot issue outside its intended identity. Record mount, role,
   allowed identity, maximum TTL, certificate owner, rotation procedure, revocation
   procedure, and CA chain fingerprint as non-secret inventory data.
5. Confirm a test certificate has client-auth EKU, the expected issuer and subject,
   an acceptable key algorithm, a bounded expiry, and a chain that the API can
   validate. Do not publish the certificate or key as a test artifact.

## 3. Prepare Keycloak client and token policy

1. Create a dedicated confidential OIDC client/service account for this integration
   in the approved realm. Enable the client-credentials grant through Service
   Accounts; disable browser, direct-access/password, implicit, and other unused
   grants. Do not create a human user or share a human client.
2. Configure X.509 Certificate as the client authenticator and trust only the
   approved Vault-issued client certificate chain. Do not configure a client-secret
   fallback. Keep the service account's assigned permissions minimal.
3. Configure Keycloak's mutual-TLS certificate-bound access-token setting for the
   realm/client as supported by the deployed version. Ensure the token endpoint
   actually requires and verifies the client certificate for this client-credentials
   request. Keycloak's current docs describe certificate-bound access tokens using
   the `cnf.x5t#S256` confirmation claim; do not infer support from the UI toggle
   alone.
4. Configure an access-token lifetime no longer than five minutes, the exact
   `ai-trading-pro-read` audience, and only `market:read` and `analysis:read` scopes.
   Do not use `Full Scope Allowed`; map only the required service-account roles and
   token claims. The emitted token must not carry order, account, portfolio, risk
   write, or administration permissions.
5. Obtain sanitized discovery metadata and record the exact issuer and token endpoint.
   Verify that `issuer` in the token exactly equals the configured issuer. A hostname,
   realm alias, proxy URL, or discovery URL mismatch is a hard failure.

## 4. Prove certificate binding before implementing the API

Use a disposable non-production client/certificate and a local verifier. Redact the
JWT and certificate material from all output. The operator records only pass/fail,
Keycloak version, configuration revision, and the expected non-secret claim names.

- The client-credentials request without a certificate fails.
- The request with the issued client certificate succeeds, and the access token is
  short-lived and contains the expected `iss`, `aud`, service principal, scopes, and
  `cnf.x5t#S256` value.
- The API-side verifier computes the presented TLS leaf certificate's RFC 8705
  thumbprint and compares it to the token's `cnf.x5t#S256`; it rejects a different
  certificate even when the JWT signature and other claims are valid.
- A token without `cnf`, with an invalid thumbprint, or used without the matching TLS
  certificate is rejected. A bearer-only call must never be accepted.
- The API validates the certificate chain, validity period, client-auth EKU and
  configured revocation policy. If a proxy terminates TLS, prove it authenticates the
  client certificate, removes caller-supplied forwarding headers, and sends verified
  identity data over a separately trusted channel to the API.
- The API validates JWT signature against the realm's published keys, exact issuer,
  audience, expiry, not-before, service account status, and required route scope.
  Unknown algorithms, missing claims, key-fetch failure, issuer/key rotation
  ambiguity, and any unverifiable condition fail closed.

Current Keycloak documentation describes both client-credentials service accounts
and X.509 client authentication, plus the certificate-bound token setting. The exact
deployed build and end-to-end behavior still require this acceptance proof. See the
official [Keycloak server administration guide](https://www.keycloak.org/docs/latest/server_admin/),
[Keycloak mTLS setup](https://www.keycloak.org/server/mutual-tls),
[Vault PKI setup](https://developer.hashicorp.com/vault/docs/secrets/pki/setup), and
[Vault PKI API](https://developer.hashicorp.com/vault/api-docs/secret/pki).

## 5. Bind the service principal to one Trading Pro workspace

Before any runtime implementation, provision exactly one active server-side mapping
from the verified Keycloak service principal to:

```text
tenant_id
project_id
trading_workspace_id
broker_id
```

All IDs must be real, approved deployment IDs. Reject missing, wildcard, duplicate,
inactive, or ambiguous mappings. Ignore/reject caller-provided tenant/workspace
headers and query values. The UI's label `default` is not a substitute for the mapping.

## 6. API implementation and acceptance gate

Only after Sections 1–5 have evidence, implement the separate machine-identity
dependency and apply it to the exact GET routes and scopes in the proposal. Keep the
existing human-user authentication path unchanged. Acceptance must include positive
tests for every allowlisted read route and negative tests for invalid issuer/audience,
expiry/not-before, missing scope, wrong/missing certificate binding, revoked/disabled
principal, missing or cross-workspace mapping, caller-supplied tenant headers, query
tokens, and all account/order/risk/write routes.

The integration remains disabled if any provider fact or test evidence is missing.
Do not use a health endpoint as authorization evidence. Do not use a broker or MT5
action as an authentication test. No certificate, token, identity binding, live API
connection, or order is created by this runbook.
