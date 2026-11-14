# Read-only inventory from Windows developer workstation
$ErrorActionPreference = 'Continue'
Write-Host '=== DEV PC ==='; Get-ComputerInfo | Select-Object WindowsProductName,OsVersion,OsArchitecture
Write-Host '=== NETWORK ==='; Get-NetIPConfiguration | Select-Object InterfaceAlias,IPv4Address,IPv4DefaultGateway
Write-Host '=== TOOLING ==='
foreach ($cmd in @('git','ssh','py','python','node','npm','code')) {
  Write-Host "-- $cmd --"; Get-Command $cmd -ErrorAction SilentlyContinue | Select-Object Name,Source
}
Write-Host '=== GIT ==='
if (Test-Path 'C:\workspace\TradeAi\.git') {
  git -C 'C:\workspace\TradeAi' remote -v
  git -C 'C:\workspace\TradeAi' status --short
} else { Write-Host 'NOT CLONED at proposed path' }
Write-Host 'No changes made.'
