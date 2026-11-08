. (Join-Path $PSScriptRoot 'windows-common.ps1')
Set-Location -LiteralPath $RepoRoot
$python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run scripts\setup-windows.ps1 first.' }
$npm = Find-Npm
# Tests own their temporary paths; do not inherit development/production overrides.
Get-ChildItem Env: | Where-Object { $_.Name -like 'NO7_*' -or $_.Name -like 'MT5_*' } |
    ForEach-Object { Remove-Item -LiteralPath ("Env:" + $_.Name) }
Invoke-Checked $python @('-m', 'pip', 'check')
Invoke-Checked $python @('-m', 'ruff', 'check', '--select', 'F,E9', '.')
Invoke-Checked $python @('-m', 'pytest', 'tests/', '-q')
Push-Location -LiteralPath $Dashboard
try { Invoke-Checked $npm @('run', 'build') } finally { Pop-Location }
Write-Output 'Dependency, lint, test and dashboard build checks passed.'