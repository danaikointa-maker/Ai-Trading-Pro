param(
    [Parameter(Mandatory=$true)][long]$ExpectedLogin,
    [Parameter(Mandatory=$true)][string]$ExpectedServer,
    [string]$Symbol = 'XAUUSD',
    [string]$TerminalPath = 'C:\Program Files\MetaTrader 5\terminal64.exe'
)
. (Join-Path $PSScriptRoot 'windows-common.ps1')
Set-Location -LiteralPath $RepoRoot
$python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run setup-windows.ps1 first.' }
if (-not (Test-Path -LiteralPath $TerminalPath -PathType Leaf)) { throw 'MT5 terminal was not found.' }
$running = Get-Process terminal64 -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $TerminalPath }
if (-not $running) { throw 'Open this MT5 terminal manually and log into the intended Demo account first. This check will not launch it automatically.' }
Invoke-Checked $python @('-m', 'integrations.brokers.mt5_readonly', '--terminal', $TerminalPath,
    '--expected-login', "$ExpectedLogin", '--expected-server', $ExpectedServer, '--symbol', $Symbol)