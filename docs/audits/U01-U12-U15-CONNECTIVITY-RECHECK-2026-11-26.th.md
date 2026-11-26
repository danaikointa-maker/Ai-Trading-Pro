# U01 / U12 / U15 connectivity recheck — 2026-11-26

## Scope and safety

Read-only Windows, VM100 and public-host checks for the V4 market-data and Office/TradingView integration dependencies. No `.env`, shell environment values, tokens, tunnel credentials, broker credentials or private keys were read. No service, tunnel, DNS, firewall, account, Auto/Live, order or position was changed.

## Results

| Check | Result | Meaning |
|---|---|---|
| Windows MT5 process | No matching `terminal64`, `terminal` or `metatrader` process was returned | There is no local MT5 session available for a fresh identity-matched Demo quote in this check |
| Windows app listeners | No listener matched ports 8000, 18000, 18080, 18081, 18082 or 18182 | No local Trading Pro API, SSH publisher forward or MT5 terminal bridge was observed |
| VM100 identity | SSH read-only query returned `ai-server` | LAN host `192.168.1.10` is reachable using the already configured SSH identity |
| VM100 tunnel | `systemctl is-active cloudflared` returned `active` | Tunnel process is running; this alone does not prove a healthy public origin |
| VM100 app listeners | `ss -ltn` showed `127.0.0.1:8000`, `127.0.0.1:18081` and `127.0.0.1:18082`; no listener on `:8080` | Existing Trading Pro services are loopback-only; the configured public origin port is not served |
| Isolated market staging | `http://127.0.0.1:18082/api/system/health` returned HTTP 200; `/api/openapi.json` returned HTTP 200 and advertises `POST /api/market/publish/mt5` | The staging API and publisher route are reachable locally on VM100; no publisher submission was made |
| Configured tunnel origin | `http://127.0.0.1:8080/` refused the connection | The public tunnel's configured origin is unavailable at the time of this check |
| Public hostname | `https://agent.youridea168.com/` returned HTTP 502 via Cloudflare (`172.67.183.70`); HTTPS certificate validation succeeded in curl | Public DNS/TLS reaches Cloudflare, but the origin request is failing |

## V4 task impact

- **U01 — PARTIAL / BLOCKED.** The isolated VM100 market API is healthy and its data-only route is advertised. Windows currently has no MT5 terminal process or publisher forward, so a fresh Demo quote cannot be received or verified. Demo identity, symbol, bid/ask/rates/spec comparison, freshness, clock normalization and stale/reconnect acceptance remain NOT TESTED.
- **U12 — PARTIAL / BLOCKED.** VM100 has no listener on the configured `:8080` Office origin. This check does not establish a dedicated Office API, Keycloak/Vault machine identity, tenant/project/workspace binding, or a Windows Trading Pro service client. Keep the integration advisory-only and unimplemented until those dependencies are provisioned and reviewed.
- **U15 — PARTIAL.** Public hostname remains HTTP 502 although the tunnel service is active. Do not repoint the hostname to loopback ports 8000, 18081 or 18082: they are existing Trading Pro/simulation/staging services, not a verified dedicated Office API. Cloudflare Access policy, proxy body-log redaction, managed secret rotation and multi-worker rate-limit acceptance remain NOT TESTED.

## Commands and limits

- Windows: process and `Get-NetTCPConnection -State Listen` queries filtered to the six ports above; no matching output.
- VM100: `systemctl is-active cloudflared`, `ss -ltn`, and loopback-only HTTP status/OpenAPI checks over SSH.
- Public edge: `curl.exe -sS -o NUL -w "%{http_code} %{remote_ip}\n" --max-time 10 https://agent.youridea168.com/`.
- This is a point-in-time connectivity check only. It does not test the publisher token, send a quote, authenticate to Office API, validate Cloudflare Access, or authorize any trade.

## Next required evidence

1. Start and log into the intended MT5 Demo terminal on Windows; configure the read-only publisher and localhost SSH forward without exposing credentials.
2. Capture a fresh quote whose broker/server/account identity matches the selected Demo session, then compare rates/specs and exercise stale/reconnect handling.
3. Provision and independently review the dedicated VM100 Office API, service identity, tenant/workspace mapping, Cloudflare Access and origin/logging policy before implementing the Windows client.
