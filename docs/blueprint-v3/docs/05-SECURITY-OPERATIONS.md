# 05 — Security / Operations / Disaster Recovery

## Network access
Proxmox 192.168.1.254:8006 and :22 only from trusted management VLAN/VPN/DevPC, MFA for admin UI. Ubuntu SSH 22 from DevPC, HTTPS 443 from allowed clients/WinMT5; API localhost behind nginx TLS. Windows SSH 22 from DevPC VPN/LAN for admin, outbound HTTPS 443 to Ubuntu and broker connection; inbound trading APIs forbidden. PostgreSQL/Redis localhost or private only.

## Security gates
- Rotate README default demo password and JWT secret before binding API to LAN; no plaintext secrets in Git, screenshots or logs.
- Bridge account token distinct from user tokens; short-lived/scope demo, rotation procedure and revocation. TLS certificate trust established in Windows/MT5; no `verify=False`.
- MT5 EA WebRequest URL allowlist; avoid enabling Python auto trading in first read-only stage; enable demo EA autotrading only after signed review and kill-switch verification.
- Windows service runs under dedicated standard user; no local admin account needed for MT5 runtime.
- Developer SSH key with passphrase, individual identities, least-privileged sudo, no root AI automation.
- No automatic retry of uncertain orders. On backend reboot reconcile broker state before new orders.

## Backup
- STOP: existing Seagate 3TB ext4 encountered `Medium Error`, `Hardware Error`, aborted journal, and remount read-only. Not a viable backup target.
- Arrange healthy external drive/NAS/Proxmox Backup Server; back up both VMs, database, model registry, secrets escrow and Git. Test restoring VM to isolated network before SSD/LVM edits. Use a second offsite copy.
- Record RPO/RTO targets and rotate daily/weekly backups; verify last successful RESTORE, not just file existence.

## Monitoring
Alert on broker/bridge disconnect, quotes > freshness limit, no ack, ambiguous order, risk engine disabled, wrong account, JWT failures, DB pressure, CPU>85% sustained, RAM pressure, disk SMART errors, backup overdue and clock skew. Central correlation_id links MT5 command to API, risk decision, DB ledger and UI.

## Safe recovery
1. Halt new execution (fail closed); do not cancel/alter broker-side hard stops blindly.
2. Snapshot logs and affected event IDs. Verify current broker positions and pending orders directly at MT5.
3. Repair connectivity only after identifying root cause; reconcile ledger against broker; require manual resolution for discrepancies.
4. Resume read-only/paper first; turn on demo execution only via explicit approved runbook.
