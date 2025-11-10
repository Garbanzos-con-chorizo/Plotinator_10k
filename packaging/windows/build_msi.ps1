<#
.SYNOPSIS
  Builds the Plotinator 10k MSI installer using WiX v6.
  Requires wix.exe, Python, and a completed PyInstaller bundle.
#>

# Stop on errors
$ErrorActionPreference = 'Stop'

Write-Host "`n=== 🧩 Plotinator 10k MSI Build Script ===`n" -ForegroundColor Cyan

# Paths
$RepoRoot   = (Resolve-Path "$PSScriptRoot\..\..").Path
$BundlePath = Join-Path $RepoRoot "dist\plotinator-bundle"
$BuildPath  = Join-Path $RepoRoot "packaging\windows\build"
$OutMSI     = Join-Path $RepoRoot "dist"
$Version    = (python -c "import plotinator; print(plotinator.__version__)").Trim()

# Ensure build folder exists
New-Item -ItemType Directory -Force -Path $BuildPath | Out-Null
New-Item -ItemType Directory -Force -Path $OutMSI | Out-Null

Write-Host "Building Plotinator version $Version ..." -ForegroundColor Green

# 1️⃣ Harvest bundle files into WiX component list
Write-Host "Harvesting bundle..." -ForegroundColor Yellow
wix harvest dir $BundlePath `
    -id PlotinatorBundleComponents `
    -ext WixToolset.Heat.wixext `
    -out "$BuildPath\plotinator-files.wxs"

# 2️⃣ Build the MSI from WiX sources
Write-Host "Compiling and linking MSI..." -ForegroundColor Yellow
wix build `
    "$RepoRoot\packaging\windows\Product.wxs" `
    "$BuildPath\plotinator-files.wxs" `
    -ext WixToolset.UI.wixext `
    -out "$OutMSI\Plotinator_10k-$Version.msi" `
    -dPLOTINATOR_VERSION=$Version

Write-Host "`n✅ MSI successfully built:" -ForegroundColor Green
Write-Host "   $OutMSI\Plotinator_10k-$Version.msi`n" -ForegroundColor Cyan
