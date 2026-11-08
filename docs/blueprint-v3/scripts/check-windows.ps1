# Read-only audit on Windows MT5 VM200
Write-Host '=== WINDOWS ==='; Get-ComputerInfo | Select-Object WindowsProductName,OsVersion,OsArchitecture
Write-Host '=== NETWORK ==='; ipconfig /all
Write-Host '=== RESOURCES ==='; Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory,NumberOfLogicalProcessors
Write-Host '=== TOOLS ==='; foreach ($c in @('python','py','ssh','git')) { Get-Command $c -ErrorAction SilentlyContinue | Select-Object Name,Source }
Write-Host '=== MT5 PROCESSES ==='; Get-Process terminal64,metaeditor64 -ErrorAction SilentlyContinue | Select-Object Name,Id,Path
Write-Host '=== SSH SERVICE ==='; Get-Service sshd -ErrorAction SilentlyContinue
Write-Host '=== WORKSPACE ==='; Test-Path 'C:\app\app\No7-Ai-Trading-Pro'
Write-Host 'No changes made.'
