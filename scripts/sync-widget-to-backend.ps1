# Builds the embeddable BOERDi widget, copies it into backend/widget_dist/,
# and (optionally) commits + pushes the result so CI rebuilds the backend image.
#
# Usage:
#   .\scripts\sync-widget-to-backend.ps1            # build + copy only
#   .\scripts\sync-widget-to-backend.ps1 -Commit    # build + copy + git commit + push

param(
    [switch]$Commit
)

$ErrorActionPreference = "Stop"

$root    = Resolve-Path (Join-Path $PSScriptRoot "..")
$src     = Join-Path $root "frontend\dist\widget\browser\main.js"
$dstDir  = Join-Path $root "backend\widget_dist"
$dst     = Join-Path $dstDir "main.js"

# 1. Build widget
Set-Location (Join-Path $root "frontend")
if (-not (Test-Path "node_modules")) { npm install }
npm run build:widget
if ($LASTEXITCODE -ne 0) { throw "build:widget failed" }

# 2. Copy into backend/widget_dist
New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
Copy-Item $src $dst -Force

$size = (Get-Item $dst).Length
Write-Host "[sync-widget] OK - $dst ($size bytes)"

# 3. Optional: commit + push
if ($Commit) {
    Set-Location $root
    git add backend/widget_dist/main.js
    git diff --cached --quiet -- backend/widget_dist/main.js
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[sync-widget] nothing changed, skipping commit"
        exit 0
    }
    git commit -m "widget: rebuild and sync bundle to backend/widget_dist"
    if ($LASTEXITCODE -ne 0) { throw "git commit failed" }
    git push
    if ($LASTEXITCODE -ne 0) { throw "git push failed" }
    Write-Host "[sync-widget] pushed - CI will rebuild backend image"
} else {
    Write-Host "[sync-widget] re-run with -Commit to auto-commit + push"
}
