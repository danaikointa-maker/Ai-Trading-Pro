# No7 AI Dev Team — read-only integration contract

## Status

This is an offline contract and synthetic fixture only. No request is sent to the
No7 AI Dev Team service, no OIDC token or client certificate is present, and no
worker, task, repository, or trading state is represented as live.

The selected identity design is Keycloak plus Vault PKI, but those services have
not been provisioned. The default workspace was selected, but its tenant and
project IDs have not been supplied. Until those prerequisites exist, live reads
remain disabled.

## Pinned upstream read contract

The current upstream project record is `ProjectRead` from
[`schemas.py`](https://github.com/danaikointa-maker/no7_ai_dev_team_plan/blob/cb1ccaf6dd9fd999d82629d6e0f25748134c03d6/apps/api/no7_api/schemas.py)
at commit `cb1ccaf6dd9fd999d82629d6e0f25748134c03d6`. The read route is
`GET /api/v1/projects`; access requires an OIDC identity that is provisioned in
the upstream database and scoped to the requested tenant/project.

The Trading Pro contract mirrors only the project registry fields: project ID,
tenant ID, name, description, optional HTTPS repository URL, lifecycle status,
created/updated timestamps, and the caller's project role. It rejects unknown
fields and any record outside the selected tenant scope. Pagination is capped
at the upstream maximum of 200 records per page.
Before presenting a project, the adapter also requires the configured tenant
UUID and project UUID and requires exactly one matching row; an omitted ID,
missing row, duplicate, or cross-tenant row is rejected rather than selecting
the first result.

The upstream API currently does not expose worker/task execution state. The
contract therefore does not invent agents, task progress, approvals, or office
activity. Those can be added only when a versioned upstream route exists.

## Safety boundary

- This integration is read-only: `execution_enabled` is fixed to `false`.
- The fixture source is explicitly labeled `fixture`; it is not a connected or
  active project.
- The package makes no network calls, reads no credential, and accepts no
  caller-selected file path.
- Live mode still needs the provisioned issuer/audience/JWKS and approved
  Keycloak/Vault PKI service identity, plus the default workspace's tenant and
  project IDs. No endpoint or identity has been guessed.
- The trading officer team remains a separate view and receives no development
  repository, task-write, shell, approval, or deployment capability.

## Local checks

The contract can be checked offline with
`python -m pytest -q tests/test_no7_dev_team_contract.py`. No application port
is required for this contract-only phase. When a live read adapter is added,
its endpoint will be verified separately through the Trading Pro API proxy.
