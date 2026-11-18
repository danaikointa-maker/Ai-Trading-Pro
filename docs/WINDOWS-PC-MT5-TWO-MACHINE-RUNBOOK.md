# Two-machine deployment: VM100 + Windows MT5 PC (proposed)

This document records the selected target topology. It does **not** certify deployment or override the safety rules in `docs/blueprint-v3/AGENTS.md`.

## Host responsibilities

| Host | Role | Runtime |
| --- | --- | --- |
| Proxmox VM100, Ubuntu | Authoritative AI Trading Core | FastAPI, dashboard, strategy/AI, risk veto, persistence, telemetry |
| Physical Windows PC | Development and MT5 execution node | VS Code, installed MT5 terminal, Python MT5 adapter, broker observations, single-account execution bridge |
| Windows VM200 | Standby/retired only after acceptance | Do not delete until the replacement has passed operator acceptance |

Do not run a second authoritative trading core on Windows. A working copy of the repository on Windows is for development and the MT5-specific components, not an excuse to run two independent execution leaders.

## First Windows PC acceptance step (read-only)

1. Open the installed MetaTrader 5 terminal manually, authenticate to a **Demo** account, and note the actual account login, broker server, terminal executable path, and exact broker symbol (for example, a broker may use a suffix).
2. In PowerShell at the repository root, run the existing `scripts/setup-windows.ps1` only after reviewing its installation effects and prerequisites.
3. Run:
   ```powershell
   .\scripts\check-mt5-demo.ps1 -ExpectedLogin <DEMO_LOGIN> -ExpectedServer '<DEMO_SERVER>' -Symbol '<BROKER_SYMBOL>' -TerminalPath 'C:\Path\To\terminal64.exe'
   ```
4. Confirm the returned login/server are those expected and `read_only` is true. **A successful last-tick read does not prove freshness or that the market is open.** This probe does not place orders.
5. Do not store credentials in Git, shell history, screenshots or diagnostic output. Do not enable AutoTrading for this check.

## Dashboard chart feed through the MT5 bridge (read-only)

- The browser on the development PC uses port `18000`; its API tunnel uses `18080` and forwards to VM100's loopback API on `8000`. Keep that SSH tunnel open while the MT5 terminal runs on this PC. The EA's default `InpServerUrl` is `http://127.0.0.1:18080`.
- Log in to a Demo account manually in MT5, then attach the compiled `bridge/No7BridgeEA.mq5` to a chart. Keep `InpReadOnly=true`, set the exact Demo login/server identity, and set the broker's exact gold symbol in `InpSymbols`. Do not enter broker passwords in the EA or chat.
- The EA forwards current quotes every poll and 600 bars for M1/M5/M15/H1/H4 once per minute. The dashboard prefers a connected MT5 bridge for the chart only; it does not change the execution broker. If no MT5 session is connected, the chart keeps the configured feed label. If the terminal is connected but the symbol/rates are missing, the chart reports the failure rather than presenting simulated bars as MT5 data.
- The chart is read-only. Runtime signals and positions from a different feed/account are hidden over an MT5 chart. No order is sent as part of chart connection or refresh.
- Bridge credentials and expected Demo identity must be configured on VM100 through its secure service environment and entered into the EA inputs locally. Never put the bridge token or broker password in Git, screenshots, or chat.

## Subsequent operational gates (not yet verified)

- Record actual VM100/Windows IPs and versions; verify secure LAN connectivity and authenticated bridge communications without publishing execution ports to the Internet.
- Demonstrate terminal disconnect/reconnect and process restart, durable idempotency and no duplicate broker sends, with operator-observed broker history.
- Reconcile partial fills, deal IDs, manual interventions and account switches against broker statements. Ambiguity must block new orders.
- Prove independent healthy backups and tested restore. Do not use the previously failed external Seagate disk.
- Require forward Demo evidence, risk review and explicit human authorization before any LIVE activation. Passing CI is not LIVE approval.

## Deferred remote access

Tailscale VPN/remote access hardening is deliberately deferred. Do not open SSH, RDP, database or MT5 execution ports to the public Internet as a shortcut.
