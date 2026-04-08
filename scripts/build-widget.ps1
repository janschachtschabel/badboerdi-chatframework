# Builds the embeddable BOERDi widget and verifies the bundle.
# The FastAPI backend reads frontend/dist/widget/browser/main.js directly,
# so no copy step is required.

$ErrorActionPreference = "Stop"

$root     = Resolve-Path (Join-Path $PSScriptRoot "..")
$frontend = Join-Path $root "frontend"
$bundle   = Join-Path $frontend "dist\widget\browser\main.js"

Write-Host "[build-widget] frontend dir: $frontend"
Set-Location $frontend

if (-not (Test-Path "node_modules")) {
    Write-Host "[build-widget] installing npm deps..."
    npm install
}

Write-Host "[build-widget] running 'npm run build:widget'..."
npm run build:widget
if ($LASTEXITCODE -ne 0) { throw "npm run build:widget failed" }

if (-not (Test-Path $bundle)) {
    Write-Error "[build-widget] expected bundle not found at $bundle"
    exit 1
}

$size = (Get-Item $bundle).Length
Write-Host "[build-widget] OK - bundle size: $size bytes"
Write-Host "[build-widget] FastAPI serves it at: http://localhost:8000/widget/boerdi-widget.js"
Write-Host "[build-widget] Demo page:           http://localhost:8000/widget/"
