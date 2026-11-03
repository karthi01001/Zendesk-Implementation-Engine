# Start the engine for development: backend on :8000, UI on :5173, then open the browser.
# Run from the repo root:  powershell -ExecutionPolicy Bypass -File scripts\start.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$VenvPython = Join-Path $Backend ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) { throw "Run scripts\setup.ps1 first." }
if (-not (Test-Path (Join-Path $Frontend "node_modules"))) { throw "Run scripts\setup.ps1 first." }

Start-Process powershell -ArgumentList @(
    "-NoExit", "-ExecutionPolicy", "Bypass", "-Command",
    "`$Host.UI.RawUI.WindowTitle = 'ZIE backend'; Set-Location '$Backend'; & '$VenvPython' -m zie serve --reload"
)
Start-Process powershell -ArgumentList @(
    "-NoExit", "-ExecutionPolicy", "Bypass", "-Command",
    "`$Host.UI.RawUI.WindowTitle = 'ZIE UI'; Set-Location '$Frontend'; npm run dev"
)

Write-Host "Waiting for the backend to start..."
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 2
        if ($health.status -eq "ok") { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
}
if (-not $ready) {
    Write-Warning "The backend did not answer within 60 seconds. Check the 'ZIE backend' window for errors."
}
Start-Sleep -Seconds 2  # give the UI dev server a moment
Start-Process "http://127.0.0.1:5173"
Write-Host "Opened http://127.0.0.1:5173. Close the two windows to stop."
