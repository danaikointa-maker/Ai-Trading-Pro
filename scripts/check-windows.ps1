. (Join-Path $PSScriptRoot 'windows-common.ps1')
Set-Location -LiteralPath $RepoRoot
$python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run scripts\setup-windows.ps1 first.' }
$null = Find-Npm
$node = (Get-Command node.exe -ErrorAction Stop).Source
$git = (Get-Command git.exe -ErrorAction Stop).Source
# Tests own their temporary paths; do not inherit development/production overrides.
Get-ChildItem Env: | Where-Object { $_.Name -like 'NO7_*' -or $_.Name -like 'MT5_*' } |
    ForEach-Object { Remove-Item -LiteralPath ("Env:" + $_.Name) }
Invoke-Checked $python @((Join-Path $RepoRoot 'scripts\verify_local.py'), '--node', $node, '--git', $git)
Write-Output 'Local QA finished; inspect summary.json for skips and unverified acceptance.'