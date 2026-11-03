# One-time setup on Windows: Python virtual environment + backend packages + UI packages.
# Run from the repo root:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"

function Assert-Success($what) {
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE). See the messages above." }
}

function Find-Python {
    $candidates = @(
        @{ Exe = "py"; Args = @("-3") },
        @{ Exe = "py"; Args = @("-3.13") },
        @{ Exe = "py"; Args = @("-3.12") },
        @{ Exe = "python"; Args = @() }
    )
    foreach ($c in $candidates) {
        try {
            $ok = & $c.Exe @($c.Args + @("-c", "import sys; print(sys.version_info >= (3, 12))")) 2>$null
            if ($LASTEXITCODE -eq 0 -and "$ok".Trim() -eq "True") { return $c }
        } catch { }
    }
    throw "Python 3.12 or newer was not found. Install it from https://www.python.org/downloads/ and run this script again."
}

Write-Host "== Checking prerequisites" -ForegroundColor Cyan
$py = Find-Python
Write-Host ("Python: " + (& $py.Exe @($py.Args + @("--version"))))
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "Node.js (npm) was not found. Install Node.js 20 LTS or newer from https://nodejs.org and run this script again."
}
Write-Host ("Node: " + (node --version))

Write-Host "== Creating backend virtual environment" -ForegroundColor Cyan
$Venv = Join-Path $Backend ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    & $py.Exe @($py.Args + @("-m", "venv", "--clear", $Venv))
    Assert-Success "Creating the virtual environment"
}
& $VenvPython -m pip install --upgrade pip
Assert-Success "Upgrading pip"
& $VenvPython -m pip install -e "$Backend[dev]"
Assert-Success "Installing the backend packages"

$EnvFile = Join-Path $Backend ".env"
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $Backend ".env.example") $EnvFile
    Write-Host "Created backend\.env from the example (only the CLI uses it)."
}

Write-Host "== Installing UI packages" -ForegroundColor Cyan
Push-Location $Frontend
try {
    npm install
    Assert-Success "npm install"
} finally { Pop-Location }

Write-Host ""
Write-Host "Setup complete. Start the app with:  powershell -ExecutionPolicy Bypass -File scripts\start.ps1" -ForegroundColor Green
