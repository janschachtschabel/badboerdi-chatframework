#!/bin/sh
# Render index.template.html into index.html at container start, substituting
# __BACKEND_URL__ with the BACKEND_URL env var. Runs on every start so the
# same image works in any environment.
set -e

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
# Strip trailing slash
BACKEND_URL="${BACKEND_URL%/}"

sed "s|__BACKEND_URL__|${BACKEND_URL}|g" \
    /usr/share/nginx/html/index.template.html \
    > /usr/share/nginx/html/index.html

echo "[chatbot] rendered index.html with BACKEND_URL=${BACKEND_URL}"
