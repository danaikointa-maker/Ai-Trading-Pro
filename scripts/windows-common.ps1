$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Dashboard = Join-Path $RepoRoot 'apps\web-dashboard'

function Find-Python {
    $localPython = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
    $candidates = @($localPython, 'python', 'python3')
    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command -and $command.Source -notmatch '\\WindowsApps\\') {
            & $command.Source -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
            if ($LASTEXITCODE -eq 0) { return $command.Source }
        }
    }
    throw 'Python 3.11+ was not found. Install Python and reopen the terminal.'
}

function Find-Npm {
    $portableRoot = Join-Path $env:LOCALAPPDATA 'Programs\TradeAi'
    if (Test-Path -LiteralPath $portableRoot) {
        $node = Get-ChildItem -LiteralPath $portableRoot -Directory -Filter 'node-*-win-x64' |
            Sort-Object Name -Descending | Select-Object -First 1
        if ($node) { $env:Path = $node.FullName + ';' + $env:Path }
    }
    $installed = Join-Path $env:ProgramFiles 'nodejs'
    if (Test-Path -LiteralPath $installed) { $env:Path = $installed + ';' + $env:Path }
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npm) { throw 'Node.js/npm was not found. Install Node.js and reopen the terminal.' }
    return $npm.Source
}

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Executable $($Arguments -join ' ')" }
}

function Set-LocalSimulation {
    # Process-only overrides; never inherit production storage, broker or alert settings.
    $env:NO7_ENV = 'development'
    $env:NO7_ROOT = $RepoRoot
    $env:NO7_FEED_MODE = 'simulate'
    $env:NO7_ALLOW_FULL_AUTO = 'false'
    $env:NO7_BRIDGE_ENABLED = 'false'
    $env:NO7_TELEGRAM_ENABLED = 'false'
    $env:NO7_LINE_ENABLED = 'false'
    $env:NO7_WEBHOOK_ENABLED = 'false'
    $env:NO7_CLUSTER_BACKEND = 'local'
    $env:NO7_ALLOW_MULTI_RUNTIME = 'false'
    $env:NO7_AUTO_TRAIN_ON_BOOT = 'false'
    $env:NO7_RATELIMIT_STORE = 'memory'
    $env:NO7_DB_PATH = Join-Path $RepoRoot 'storage\local-dev\db\no7.sqlite3'
    $env:NO7_DATA_DIR = Join-Path $RepoRoot 'storage\local-dev\datasets'
    $env:NO7_MODEL_DIR = Join-Path $RepoRoot 'storage\local-dev\models'
    $env:NO7_BACKTEST_DIR = Join-Path $RepoRoot 'storage\local-dev\backtests'
    $env:NO7_LOG_DIR = Join-Path $RepoRoot 'storage\local-dev\logs'
    # These must never be used to initialise a real terminal during local development.
    $env:MT5_LOGIN = ''
    $env:MT5_PASSWORD = ''
    $env:MT5_SERVER = ''
    $env:MT5_TERMINAL_PATH = Join-Path $RepoRoot 'storage\local-dev\NO_TERMINAL.exe'
}