#!/usr/bin/env bash
# Builds the embeddable BOERDi widget and verifies the bundle.
# The FastAPI backend reads frontend/dist/widget/browser/main.js directly,
# so no copy step is required.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND="$ROOT/frontend"
BUNDLE="$FRONTEND/dist/widget/browser/main.js"

echo "[build-widget] frontend dir: $FRONTEND"
cd "$FRONTEND"

if [ ! -d node_modules ]; then
  echo "[build-widget] installing npm deps…"
  npm install
fi

echo "[build-widget] running 'npm run build:widget'…"
npm run build:widget

if [ ! -f "$BUNDLE" ]; then
  echo "[build-widget] ERROR: expected bundle not found at $BUNDLE" >&2
  exit 1
fi

SIZE=$(wc -c <"$BUNDLE")
echo "[build-widget] OK — bundle size: ${SIZE} bytes"
echo "[build-widget] FastAPI serves it at: http://localhost:8000/widget/boerdi-widget.js"
echo "[build-widget] Demo page:           http://localhost:8000/widget/"
