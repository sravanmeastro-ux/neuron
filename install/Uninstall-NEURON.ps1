#Requires -Version 5.1
<#
.SYNOPSIS
  Remove NEURON desktop/start-menu shortcuts and optional install marker.
#>
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Desktop = [Environment]::GetFolderPath("Desktop")
$Start = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\NEURON"
@(
  (Join-Path $Desktop "NEURON.lnk"),
  (Join-Path $Start "NEURON.lnk")
) | ForEach-Object { if (Test-Path $_) { Remove-Item $_ -Force } }
if (Test-Path $Start) { Remove-Item $Start -Recurse -Force -ErrorAction SilentlyContinue }
$marker = Join-Path $Root "backend\data\production\install_marker.json"
if (Test-Path $marker) { Remove-Item $marker -Force }
Write-Host "NEURON shortcuts removed. Project files left intact at $Root"
