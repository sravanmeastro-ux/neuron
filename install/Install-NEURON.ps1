#Requires -Version 5.1
<#
.SYNOPSIS
  Professional installer for N.E.U.R.O.N (public release).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install\Install-NEURON.ps1
  powershell -ExecutionPolicy Bypass -File .\install\Install-NEURON.ps1 -Preset balanced -SkipDeps
#>
param(
  [ValidateSet("safe", "balanced", "performance", "developer")]
  [string]$Preset = "balanced",
  [switch]$SkipDeps,
  [switch]$NoShortcuts
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Backend = Join-Path $Root "backend"
Set-Location $Root

Write-Host "=== N.E.U.R.O.N Installer ===" -ForegroundColor Cyan
Write-Host "Root: $Root"

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
  Write-Host "Python not found. Install Python 3.10+ from https://www.python.org/downloads/" -ForegroundColor Red
  exit 1
}
$ver = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "Python: $ver"

if (-not $SkipDeps) {
  Write-Host "Installing dependencies ..."
  & python -m pip install --upgrade pip
  & python -m pip install -r (Join-Path $Root "requirements.txt")
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$env:PYTHONPATH = $Backend
$installArgs = @("-m", "neuron.production.cli", "install")
if ($SkipDeps) { $installArgs += "--skip-deps" }
if ($NoShortcuts) { $installArgs += "--no-shortcuts" }
Write-Host "Finalizing install markers/shortcuts ..."
& python @installArgs

Write-Host "Applying configuration preset: $Preset"
& python -m neuron.production.cli wizard $Preset

Write-Host ""
Write-Host "Install complete." -ForegroundColor Green
Write-Host "Launch:   .\launch-jarvis.bat"
Write-Host "Diagnose: python -m neuron.production.cli diagnostics   (from backend/ with PYTHONPATH)"
Write-Host "Or say:   Run diagnostics"
