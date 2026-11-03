# Run every check: backend lint, types and tests; UI type check and production build.
# Run from the repo root:  powershell -ExecutionPolicy Bypass -File scripts\check.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$VenvPython = Join-Path $Backend ".venv\Scripts\python.exe"

function Step($name, [scriptblock]$block) {
    Write-Host "== $name" -ForegroundColor Cyan
    & $block
    if ($LASTEXITCODE -ne 0) { throw "$name failed" }
}

Push-Location $Backend
try {
    Step "ruff (lint)"   { & $VenvPython -m ruff check src tests }
    Step "ruff (format)" { & $VenvPython -m ruff format --check src tests }
    Step "mypy"          { & $VenvPython -m mypy }
    Step "pytest"        { & $VenvPython -m pytest -q }
} finally { Pop-Location }

Push-Location $Frontend
try {
    Step "UI build" { npm run build }
} finally { Pop-Location }

Write-Host "All checks passed." -ForegroundColor Green
