#!/usr/bin/env bash
# Read-only audit on Ubuntu VM100
set -u
printf '\n=== HOST ===\n'; hostnamectl 2>/dev/null || true
printf '\n=== IPS ===\n'; ip -br address; ip route
printf '\n=== RESOURCES ===\n'; free -h; df -hT; nproc
printf '\n=== TOOLS ===\n'; for t in git python3 node npm docker nginx psql redis-cli; do command -v "$t" || true; done
printf '\n=== PROCESSES ===\n'; ps -eo pid,comm,pcpu,pmem --sort=-pcpu | head -20
printf '\n=== LISTENING ===\n'; ss -lnt
printf '\n=== GUEST AGENT ===\n'; systemctl is-active qemu-guest-agent 2>/dev/null || true
printf '\n=== APPS ===\n'; test -d /opt/no7-ai-trading-pro/.git && git -C /opt/no7-ai-trading-pro status --short || echo 'NO git checkout at target path'
printf '\nRead-only audit complete.\n'
