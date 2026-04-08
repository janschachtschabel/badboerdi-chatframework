# Builds the embeddable BOERDi widget and copies it into backend/widget_dist/
# so it ships with a backend-only Vercel deployment.

$ErrorActionPreference = "Stop"

$root    = Resolve-Path (Join-Path $PSScriptRoot "..")
$src     = Join-Path $root "frontend\dist\widget\browser\main.js"
$dstDir  = Join-Path $root "backend\widget_dist"
$dst     = Join-Path $dstDir "main.js"

Set-Location (Join-Path $root "frontend")
if (-not (Test-Path "node_modules")) { npm install }
npm run build:widget
if ($LASTEXITCODE -ne 0) { throw "build:widget failed" }

New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
Copy-Item $src $dst -Force

$size = (Get-Item $dst).Length
Write-Host "[sync-widget] OK - $dst ($size bytes)"
Write-Host "[sync-widget] Now commit backend/widget_dist/main.js and redeploy to Vercel."
