# U01 — Isolated VM100 API Staging Check (2026-11-24)

## Scope and safety

The user authorized an isolated VM100 staging environment. This check used a new detached worktree at `/home/danai/no7-ai-trading-pro-v4-staging-u01`, commit `5ad5652f48c370ea6b735b1c1cf55db6139089e6`. It did not replace or restart the existing VM100 checkout, read `.env`/`.env.save`, change broker identity, publish a quote, send an order, or modify a position.

The API process runs only on VM100 loopback `127.0.0.1:18082`. It was started with a clean environment (`NO7_LOCAL_SIMULATION=true`, `NO7_ALLOW_FULL_AUTO=false`, development mode, a staging-only workspace ID, and an ephemeral process JWT secret). No publisher token, expected MT5 login/server, or publisher symbol allowlist was configured. The process therefore cannot accept the PC publisher and cannot reach a broker adapter. Existing VM100 processes on ports 8000 and 18081 were left untouched.

## Evidence

| Check | Result |
|---|---|
| New worktree source | PASS — detached at planning commit `5ad5652`; `git status --short --branch` clean |
| Runtime dependencies | PASS — FastAPI 0.165.0, Uvicorn 0.54.0, Pydantic 2.14.4 import successfully |
| Bind address | PASS — listener is `127.0.0.1:18082`, not a public interface |
| `GET /api/system/health` | PASS — HTTP success, `status=ok`, `feed_mode=simulate` |
| `GET /api/openapi.json` | PASS — documents `POST /api/market/publish/mt5` |
| Publisher enabled / authenticated | NOT TESTED — intentionally disabled; no token or expected Demo identity was configured |
| Fresh MT5 quote, rates/spec comparison, clock/freshness, stale/reconnect | NOT TESTED — no PC publisher request was sent and the health feed remains simulated |
| Trading commands | NOT SENT — no order or position endpoint was called |

The older checkout `/home/danai/no7-ai-trading-pro-v4-staging` remains on `feature/u02-100pt-confirmation` at `06642a06`; its environment and database were not read or changed. This check establishes route availability only in the separate V4 staging artifact. It does not certify rollout parity or U05 database/recovery acceptance.

## PC connection shape (after local secret configuration)

A user-side SSH forward can expose only this loopback service to the Windows publisher:

```powershell
ssh -N -L 18182:127.0.0.1:18082 danai@192.168.1.10
```

The PC publisher URL would then be `http://127.0.0.1:18182/api/market/publish/mt5`. The bearer token and expected Demo login/server/symbol allowlist must be provisioned through the local secret mechanism and must never be pasted into chat or committed. No such values are present in this report.

## Rollback

The isolated process is manual staging, not a systemd service. To stop it, first verify that the recorded PID still runs the command for this exact worktree and port 18082, then send it `TERM`. Do not stop ports 8000 or 18081. Keep the separate staging worktree until rollback/recovery is reviewed; do not replace the old checkout.

## Regression recheck

The focused 18-file U01–U05 suite was rerun against this base: **350 passed**, one pre-existing Starlette/httpx deprecation warning. Ruff E9/F passed. No source or test files were changed in this documentation-only update.

## Status

U01 remains **PARTIAL / BLOCKED**. Route parity is verified on a separate loopback-only staging artifact. Fresh, identity-matched MT5 Demo quotes and publisher acceptance remain outstanding, as do U05 persistence/restart parity prerequisites before any whole-checkout replacement.
