param([switch]$CheckOnly)
. (Join-Path $PSScriptRoot 'windows-common.ps1')
Set-Location -LiteralPath $RepoRoot
$python = Find-Python
$npm = Find-Npm
Invoke-Checked $python @('--version')
Invoke-Checked $npm @('--version')
if ($CheckOnly) { Write-Output 'Runtime checks passed.'; return }

$venv = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venv)) { Invoke-Checked $python @('-m', 'venv', '.venv') }
Invoke-Checked $venv @('-m', 'pip', 'install', '-r', 'requirements-dev.txt')
Invoke-Checked $venv @('-m', 'pip', 'check')

$envFile = Join-Path $RepoRoot '.env'
if (-not (Test-Path -LiteralPath $envFile)) {
    $template = [IO.File]::ReadAllText((Join-Path $RepoRoot '.env.example'))
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $bytes = New-Object byte[] 48; $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $secret = [Convert]::ToBase64String($bytes)
    $template = $template.Replace('NO7_JWT_SECRET=', "NO7_JWT_SECRET=$secret")
    $template = $template.Replace('NO7_HOST=0.0.0.0', 'NO7_HOST=127.0.0.1')
    [IO.File]::WriteAllText($envFile, $template, (New-Object Text.UTF8Encoding $false))
    Write-Output 'Created ignored .env with a random JWT secret; existing files are never overwritten.'
}
Push-Location -LiteralPath $Dashboard
try {
    Invoke-Checked $npm @('ci')
    Invoke-Checked $npm @('run', 'build')
} finally { Pop-Location }
Write-Output 'Setup complete. Run scripts\check-windows.ps1, then scripts\run-local.ps1.'