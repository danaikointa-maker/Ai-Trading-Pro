#!/usr/bin/env bash
set -u
printf '%s\n' '=== UBUNTU VM100 READ-ONLY PREFLIGHT ==='
printf '%s\n' 'OS'; cat /etc/os-release | head -6
printf '%s\n' 'IP'; hostname -I
printf '%s\n' 'Time'; timedatectl | head -12
printf '%s\n' 'Resources'; free -h; df -hT; nproc
printf '%s\n' 'Software'; for x in python3 git node npm nginx psql redis-cli docker; do command -v "$x" || :; done
printf '%s\n' 'Listening TCP ports'; ss -lnt || :
printf '%s\n' 'No changes performed.'
