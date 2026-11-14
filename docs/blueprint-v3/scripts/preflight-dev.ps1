$ErrorActionPreference='Continue'
Write-Output '=== DEV PC READ-ONLY PREFLIGHT ==='
$root='C:\workspace\TradeAi'
Write-Output "Workspace exists: $(Test-Path $root)"
Get-Command code,git,ssh,py,node,npm -ErrorAction SilentlyContinue | Select-Object Name,Source
if(Test-Path "$root\.git") {git -C $root status --short;git -C $root remote -v;git -C $root branch --show-current}
Write-Output 'Do not upload credentials/SSH private keys to chat or Git.'
