$ErrorActionPreference='Continue'
Write-Output '=== WINDOWS VM200 READ-ONLY PREFLIGHT ==='
Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, LastBootUpTime
Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -notlike '169.254*'} | Select-Object InterfaceAlias,IPAddress
Get-Service sshd -ErrorAction SilentlyContinue
Get-Command py,python,git,ssh -ErrorAction SilentlyContinue | Select-Object Name,Source
Get-Process terminal64 -ErrorAction SilentlyContinue | Select-Object Name,Id,Path
Test-Path 'C:\app\app\No7-Ai-Trading-Pro'
Write-Output 'No changes performed.'
