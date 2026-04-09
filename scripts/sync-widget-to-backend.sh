#!/usr/bin/env bash
# Builds the embeddable BOERDi widget, copies it into backend/widget_dist/,
# and (optionally) commits + pushes the result so CI rebuilds the backend image.
#
# Usage:
#   ./scripts/sync-widget-to-backend.sh            # build + copy only
#   ./scripts/sync-widget-to-backend.sh --commit   # build + copy + git commit + push
set -euo pipefail

COMMIT=0
if [[ "${1:-}" == "--commit" ]]; then COMMIT=1; fi

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
echo "[sync-widget] OK - $DST ($SIZE bytes)"

if [[ "$COMMIT" == "1" ]]; then
  cd "$ROOT"
  git add backend/widget_dist/main.js
  if git diff --cached --quiet; then
    echo "[sync-widget] nothing changed, skipping commit"
    exit 0
  fi
  git commit -m "widget: rebuild and sync bundle to backend/widget_dist"
  git push
  echo "[sync-widget] pushed - CI will rebuild backend image"
else
  echo "[sync-widget] re-run with --commit to auto-commit + push"
fi
