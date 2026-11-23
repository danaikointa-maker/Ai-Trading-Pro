# Windows Trader ↔ VM100 Office API — Interface Boundary

Status: design contract for the VM100 side; not an active API specification or deployment authorization.

## Ownership

- Windows AI Trading Pro owns the selected MT5 session, broker identity, trading strategy, RiskEngine, ExecutionGateway, EA/adapter and final order/fill reconciliation.
- VM100 owns the AI Development/QA/Creative Office API and its scoped task, event, advisory and media workflows.
- This split keeps one broker execution leader. Do not move or duplicate trading execution to VM100 as part of an Office API task.

## Allowed connection shape

- Windows initiates authenticated outbound HTTPS/WebSocket sessions to `https://agent.youridea168.com` after the Cloudflare route, identity policy and TLS are verified.
- Both sides use versioned, documented schemas, request/correlation IDs, timestamps, provenance and per-user/project/account authorization.
- Exchange only allowlisted data needed for the active feature. Reject unknown fields; label the source and freshness; do not silently substitute stale or simulator values for broker data.
- Use separate short-lived/scoped service identity for a publisher or worker. Never place credentials in browser code, URLs, project documents, video prompts or logs.

## VM100 must not do

- Store broker passwords or private trading keys.
- Toggle Auto or choose/switch the user's broker account.
- Send, queue, retry or modify broker orders/positions, control MT5/EA or bypass Windows confirmation, RiskEngine or ExecutionGateway.
- Treat a TradingView webhook, LLM response, AI Officer persona or video/QA worker as an executable trading instruction.
- Expose database, shell, worker control, MT5 command bridge or raw media bucket through the public Cloudflare hostname.

## Trading mode boundary

- **Manual:** VM100 may return advisory analysis/notifications; Windows user submits the trade.
- **Semi-Auto:** VM100 may return a candidate; Windows waits for explicit user confirmation for that individual entry.
- **Auto:** only the Windows runtime may execute an allowlisted, versioned deterministic rule, and only when the user explicitly enabled Auto for that account. VM100 cannot enable Auto or issue the order.
- Auto defaults OFF; Live remains separately unauthorized. If the Windows runtime or MT5 terminal is offline, VM100 does not take over trading.

## Hostname and operational gate

`agent.youridea168.com` is a requested target, not proof of active DNS/Tunnel/Access/TLS configuration. Route only the VM100 Office API/UI to a verified loopback-bound origin after security and readiness review. Never publish the Windows trading port, VM100 development/simulator port `8000`, MT5 bridge or broker command surface. Existing staging port `18081` is historical and must be verified before use.
