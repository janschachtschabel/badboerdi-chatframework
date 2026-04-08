#!/usr/bin/env bash
# Builds the embeddable BOERDi widget and copies it into backend/widget_dist/
# so it ships with a backend-only Vercel deployment.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/frontend/dist/widget/browser/main.js"
DST_DIR="$ROOT/backend/widget_dist"
DST="$DST_DIR/main.js"

cd "$ROOT/frontend"
[ -d node_modules ] || npm install
npm run build:widget

mkdir -p "$DST_DIR"
cp "$SRC" "$DST"

SIZE=$(wc -c <"$DST")
echo "[sync-widget] OK — $DST ($SIZE bytes)"
echo "[sync-widget] Now commit backend/widget_dist/main.js and redeploy to Vercel."
