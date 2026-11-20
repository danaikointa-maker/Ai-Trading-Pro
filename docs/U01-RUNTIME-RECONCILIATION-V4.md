# U01 Runtime Reconciliation — MT5 Market Publisher

Status: SOURCE/TEST COMPLETE; ACTIVE RUNTIME BLOCKED. Read-only investigation on 2026-11-20. No runtime, account, bridge flag, order, or position was changed.

## Observed runtime

| Surface | Read-only result |
|---|---|
| PC `18000` and VM tunnel `18080` health | `status=ok`, `feed_mode=simulate` |
| Active OpenAPI schema | no `POST /api/market/publish/mt5` |
| Current old PC publisher | not running after it was refused by VM100 |
| VM bridge process configuration | `NO7_BRIDGE_ENABLED=true`, `NO7_BRIDGE_READ_ONLY=false` |
| Current PC launcher defaults | 1,000 ms polling, 10 second rates refresh, includes positions |

The active PC and VM checkouts are dirty `integration/unified-tradeai` copies, not this V4 worktree. Preserve them for reviewed reconciliation; do not overwrite either checkout or infer that V4 is deployed.

## Follow-up read-only probe

A later PC probe first used the wrong paths (`/api/health`, `/openapi.json`), which returned 404/frontend HTML. Listener inspection found `18000` owned by `node` and `18080` owned by `ssh`; no local listener was found on `8000`. The active SSH command maps `127.0.0.1:18080` to `127.0.0.1:8000` on `danai@192.168.1.10`.

Using the actual paths, read-only GET requests to `/api/system/health` and `/api/openapi.json` both succeeded on ports `18000` and `18080`. Both health responses report `status=ok`, `feed_mode=simulate`; both schemas expose 88 paths and do not contain `/api/market/publish/mt5`. Direct SSH confirmed VM100's `integration/unified-tradeai` Uvicorn process on `127.0.0.1:8000`, with the same health and schema results. Therefore the API tunnel works; the runtime itself is still the older simulated-feed API without the isolated publisher route. No authenticated API call, configuration change, or trading mutation was attempted. Review/reconcile the dirty VM runtime and deploy the reviewed isolated market route before Demo data acceptance.

## Why the old publisher was refused

The old `scripts/mt5_readonly_market_publisher.py` registers through `/api/bridge/register` and sends market snapshots through `/api/bridge/poll`. It stops unless the bridge registration response says `read_only=true`. Its loop does not execute returned commands, but it logs and ignores them. In the active relay, `read_only=false` causes `/api/bridge/poll` to claim queued commands for the polling session. Therefore weakening the publisher guard would let the market process drain an execution command before ignoring it. Setting the shared bridge `read_only=true` is not a safe quick fix either: the same flag blocks command enqueue and can disable the intended Demo execution path.

## V4 path and reviewed rollout sequence

V4 uses a separate `POST /api/market/publish/mt5` route with its own credential and data-only schema. It does not call bridge register/poll, and rejects snapshots without an exact Demo identity, approved symbols and fresh clock anchors. The PC publisher refreshes quotes at the configured short interval and rates on a separate interval. The API is disabled by default.

When runtime rollout is separately authorized, follow this sequence:

1. Review the active dirty runtime diff and create a backed-up, reviewable deployment artifact; do not copy files over the dirty checkout.
2. Deploy the reviewed V4 API source as a separate release candidate while preserving the current bridge mode and its command queue.
3. Configure a dedicated market publisher token, expected Demo login/server, account namespace and canonical symbol allowlist. Keep secrets out of command output, Git and logs.
4. Stop the old publisher before launching the V4 PC publisher over HTTPS or the existing loopback SSH tunnel. Use a canonical mapping such as `XAUUSD=XAUUSD.s` only after verifying the terminal's Market Watch symbol.
5. Run `scripts/check_mt5_market_runtime.py`; require the publisher route, `feed_mode=mt5_demo_publisher` and `fresh=true`. Then verify quote and closed-bar provenance/time conversion and confirm stale feed fails closed.
6. Roll back by stopping the new publisher and setting its dedicated enable flag false. Keep the existing EA bridge flag unchanged. Do not fall back to the old poll-based publisher while the bridge is writable.

Do not mark U01 accepted until this runtime receipt, actual Demo quote/rates comparison, symbol mapping, server-clock/DST evidence and stale/reconnect evidence are recorded. The present readiness check is `ready=false`; no rollout has occurred.
