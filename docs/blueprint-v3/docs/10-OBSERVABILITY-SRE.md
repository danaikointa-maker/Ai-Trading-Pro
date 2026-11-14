# Observability, reliability and recovery

## Service Level Indicators (proposed pilot targets, not guarantees)
- API authenticated health; MT5 terminal heartbeat 2–5 sec; quote freshness and bid/ask age per symbol; broker reconnect detection; outbound bridge lag; order intent queue depth; unknown-order count; reconcile delay; error/dead-letter queue size; DB latency; disk free; RAM/CPU; cron/worker health.
- Starter availability target 99.5% **during defined supported hours**; record downtime from end-to-end probe, not merely process alive.
- RPO target <=15min with verified archiving/backup design, RTO 1–4h if provisioned replacement hardware is ready; a single physical 7040 is not HA.
- Incident severity: P0 unknown order, execution duplicates, wrong account, severe data contamination; P1 stale market, backup failure, DB slow; P2 degraded report/AI explanations.

## Fail-safe rules
- Loss of MT5 bridge or stale quote -> `NO_NEW_ORDERS`, alarm, existing broker-native SL/TP maintained where possible.
- Ambiguous order send -> `UNKNOWN`, block fresh intents until history reconciliation, human escalation if uncertain.
- Model invalid/dataset corrupt -> pause model signal, serve baseline/WAIT as explicitly labeled, never hallucinate price.
- Restart recovery -> durable event replay + reconcile, never assume queued order not sent.
- Auto-restart on CPU overload is not a substitute for root-cause and memory pressure limits; critical Windows broker worker prioritized.

## Backups
- External Seagate 3TB (`sdd1`, WWN `0x5000c5005cfe8624`) yielded `Hardware Error`, `Medium Error`, failed ext4 superblock writes and readonly remount: **quarantine, don't use**. SMART PASSED not sufficient.
- Separate replacement external backup, off-host/offline copy, encrypted DB backup + VM backup; sample restore verification and documented checksum.
- Do not repartition `sda`, `sdb`, `sdc` or move Windows VM until verified backups and recovery procedures.
- Proxmox snapshots are not a substitute for an off-host backup. Protect broker secrets independently from backups and restrict restore access.

## Windows/Ubuntu operations
- Use SSH keys, low privilege accounts and audit; no blanket root automation. NTP clock sync both VMs; trusted certificates; monitor firewall and EDR.
- Config-as-code checked in without secrets; env secret files on hosts only; rotate bridge keys, API tokens and incident-exposed credentials.
- UPS and safe shutdown for host power cuts; check disk smart/self-tests and CPU thermals.
