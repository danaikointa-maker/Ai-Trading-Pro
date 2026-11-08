param([ValidateRange(1024, 65535)][int]$Port = 8000)
. (Join-Path $PSScriptRoot 'windows-common.ps1')
Set-Location -LiteralPath $RepoRoot
$python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run scripts\setup-windows.ps1 first.' }
if (-not (Test-Path -LiteralPath (Join-Path $Dashboard 'dist\index.html'))) {
    throw 'Dashboard build missing. Run scripts\setup-windows.ps1 first.'
}
Set-LocalSimulation
$guard = @'
from packages.shared_schemas.settings import get_settings
s = get_settings()
assert s.market_data['feed_mode'] == 'simulate', 'Local run requires simulated prices'
assert all(p.get('adapter', 'simulated_mt5') in ('paper', 'simulated_mt5') for p in s.brokers['brokers']), 'Local config contains terminal/bridge profiles'
assert not s.security['allow_full_auto'], 'Full auto must remain disabled'
assert s.security.get('require_auth', True), 'Authentication must remain enabled'
assert len(s.security['jwt_secret']) >= 32 and s.security['jwt_secret'] != 'no7-local-development-secret-key-change-me-48chars', 'Set a private NO7_JWT_SECRET in .env'
'@
# Validate a paper-only copy of broker profiles without changing tracked configuration.
$env:NO7_LOCAL_SIMULATION = 'true'
Invoke-Checked $python @('-c', $guard)
Write-Output "Local simulated trading only: http://127.0.0.1:$Port (Ctrl+C to stop)"
Invoke-Checked $python @('-m', 'uvicorn', 'services.api_gateway.app:app', '--host', '127.0.0.1', '--port', "$Port", '--workers', '1', '--no-proxy-headers')