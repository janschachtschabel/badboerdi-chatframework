#!/usr/bin/env bash
# update-vserver.sh
# ─────────────────────────────────────────────────────────────────────
# Production-Update für eine BadBoerdi-Instanz auf einem vserver.
#
# Hintergrund:
# Das docker-compose.yml mountet ``./backend/chatbots/`` und
# ``./backend/knowledge/`` als Bind-Mounts. Folge: ein reines
# ``docker compose pull && up`` aktualisiert NUR den Code im Image,
# nicht die Configs/Snapshots — die kommen aus dem Host-Filesystem.
# Daher sind drei Schritte nötig:
#
#   1. Lokale Studio-Edits sichern/verwerfen (sonst blockiert ``git pull``)
#   2. ``git pull`` zieht die neuen Files in den Bind-Mount
#   3. ``docker compose pull && up`` bringt das neue Image
#
# Dieses Skript orchestriert alle drei plus Pre-Update-Snapshot,
# Health-Check und Endpoint-Verifikation. Bricht bei jedem Fehler
# kontrolliert ab und gibt Diagnose aus.
#
# Voraussetzungen:
#   - Skript läuft im Repo-Root (dort wo docker-compose.yml liegt)
#   - ``.env`` mit STUDIO_API_KEY (für Snapshot-API) ist vorhanden
#   - User hat ``docker``-Berechtigung
#   - ``git remote`` ist erreichbar
#
# Aufruf:
#   ./scripts/update-vserver.sh                  # Standard: Studio-Edits stashen
#   ./scripts/update-vserver.sh --reset-edits    # Studio-Edits verwerfen
#   ./scripts/update-vserver.sh --skip-snapshot  # Kein Pre-Update-Snapshot
#   ./scripts/update-vserver.sh --dry-run        # Nur prüfen, nichts ändern
#   ./scripts/update-vserver.sh --help

set -euo pipefail

# ─── Optionen parsen ──────────────────────────────────────────────────
RESET_EDITS=0
SKIP_SNAPSHOT=0
DRY_RUN=0

usage() {
    cat <<EOF
update-vserver.sh — Production-Update für BadBoerdi

Standardablauf:
  1. Pre-Update-Snapshot via API (Backup vor dem Update)
  2. Lokale Studio-Edits stashen (git stash)
  3. git pull (zieht neue Configs, Patterns, Factory-Snapshot)
  4. Studio-Edits zurückspielen (git stash pop) — bei Konflikt manuell
  5. docker compose pull (neue Images von Docker Hub)
  6. docker compose up -d --force-recreate (Container neustarten)
  7. Health-Check warten (max 60s)
  8. Endpoint-Verifikation (/api/health, /api/config/guide-mode)

Optionen:
  --reset-edits     Lokale Studio-Edits VERWERFEN statt stashen.
                    Sinnvoll, wenn man weiß dass die Edits nicht
                    relevant waren (z.B. nur Test-Werte).
  --skip-snapshot   Kein Pre-Update-Snapshot anlegen (spart ~30s).
  --dry-run         Zeigt was gemacht würde, ohne zu ändern.
  --help            Diese Hilfe.

Voraussetzungen:
  - Im Repo-Root ausgeführt
  - .env mit STUDIO_API_KEY (oder ENV-Variable gesetzt)
  - User hat docker-/sudo-Rechte
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --reset-edits)   RESET_EDITS=1; shift ;;
        --skip-snapshot) SKIP_SNAPSHOT=1; shift ;;
        --dry-run)       DRY_RUN=1; shift ;;
        --help|-h)       usage ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# ─── Farben für Output ────────────────────────────────────────────────
if [ -t 1 ]; then
    C_RED=$'\e[31m'; C_GREEN=$'\e[32m'; C_YELLOW=$'\e[33m'
    C_BLUE=$'\e[34m'; C_GRAY=$'\e[90m'; C_RESET=$'\e[0m'
else
    C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_GRAY=""; C_RESET=""
fi

step()  { echo "${C_BLUE}━━━━━ $* ━━━━━${C_RESET}"; }
ok()    { echo "${C_GREEN}✓${C_RESET} $*"; }
warn()  { echo "${C_YELLOW}⚠${C_RESET}  $*"; }
fail()  { echo "${C_RED}✗${C_RESET} $*" >&2; }
info()  { echo "${C_GRAY}  $*${C_RESET}"; }

# ─── Pre-flight checks ────────────────────────────────────────────────
step "Vorab-Prüfungen"

[[ -f docker-compose.yml ]] || {
    fail "docker-compose.yml nicht gefunden — bist du im Repo-Root?"
    exit 1
}
ok "docker-compose.yml gefunden"

# .env laden, falls vorhanden — primär wegen STUDIO_API_KEY
if [[ -f .env ]]; then
    # nur Schlüssel-Wert-Paare ohne Whitespace lesen (sicher)
    set -a
    # shellcheck disable=SC1091
    source <(grep -E '^[A-Z_][A-Z_0-9]*=' .env | sed 's/^/export /')
    set +a
    ok ".env eingelesen"
else
    info ".env nicht vorhanden — STUDIO_API_KEY muss in der Shell gesetzt sein"
fi

if ! command -v git >/dev/null; then
    fail "git nicht gefunden"
    exit 1
fi
if ! command -v docker >/dev/null; then
    fail "docker nicht gefunden"
    exit 1
fi
ok "git + docker verfügbar"

if [[ $DRY_RUN -eq 1 ]]; then
    warn "DRY-RUN-Modus aktiv — keine Änderungen werden geschrieben"
fi
echo

# ─── 1. Pre-Update-Snapshot ───────────────────────────────────────────
if [[ $SKIP_SNAPSHOT -eq 0 ]]; then
    step "1. Pre-Update-Snapshot via API"
    SNAP_LABEL="pre-update-$(date +%Y%m%d-%H%M%S)"

    # Studio-Auth-Header nur senden wenn Key da ist (sonst egal — bei
    # offenem Backend ohne STUDIO_API_KEY ignoriert die Auth den Header).
    AUTH_HEADER=()
    if [[ -n "${STUDIO_API_KEY:-}" ]]; then
        AUTH_HEADER=(-H "X-Studio-Key: ${STUDIO_API_KEY}")
    fi

    if [[ $DRY_RUN -eq 1 ]]; then
        info "(DRY) curl -X POST .../api/config/snapshots?label=${SNAP_LABEL}"
    else
        if SNAP_BODY=$(curl -fsS \
            -X POST "http://localhost:8000/api/config/snapshots?label=${SNAP_LABEL}&include_db=true" \
            "${AUTH_HEADER[@]}" 2>/dev/null); then
            SNAP_ID=$(echo "$SNAP_BODY" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
            ok "Snapshot ${SNAP_ID:-(unbekannt)} angelegt"
            info "Roll-Back: POST /api/config/snapshots/<id>/restore?wipe=true&include_db=true"
        else
            warn "Snapshot-API nicht erreichbar — Backend läuft evtl. nicht. Update läuft trotzdem."
        fi
    fi
    echo
fi

# ─── 2. Lokale Studio-Edits behandeln ─────────────────────────────────
step "2. Lokale Studio-Edits behandeln"

# Welche tracked Files sind dirty?
DIRTY_FILES=$(git diff --name-only) || true

if [[ -z "$DIRTY_FILES" ]]; then
    ok "Keine lokalen Änderungen — git pull wird sauber durchlaufen"
else
    info "Geänderte Dateien:"
    while IFS= read -r f; do
        info "    $f"
    done <<< "$DIRTY_FILES"

    if [[ $RESET_EDITS -eq 1 ]]; then
        warn "--reset-edits: Lokale Edits werden VERWORFEN"
        if [[ $DRY_RUN -eq 0 ]]; then
            git checkout -- $DIRTY_FILES
            ok "Lokale Edits verworfen"
        fi
    else
        STASH_LABEL="auto-update-$(date +%Y%m%d-%H%M%S)"
        if [[ $DRY_RUN -eq 1 ]]; then
            info "(DRY) git stash push -m ${STASH_LABEL} ..."
        else
            # shellcheck disable=SC2086
            git stash push -m "${STASH_LABEL}" $DIRTY_FILES
            ok "Lokale Edits gestasht als '${STASH_LABEL}'"
            info "Wiederherstellen: git stash list && git stash pop"
        fi
    fi
fi
echo

# ─── 3. git pull ──────────────────────────────────────────────────────
step "3. Code + Configs vom Repo holen"
if [[ $DRY_RUN -eq 1 ]]; then
    info "(DRY) git pull"
    git fetch --dry-run 2>&1 | head -10
else
    BEFORE_HASH=$(git rev-parse HEAD)
    if git pull; then
        AFTER_HASH=$(git rev-parse HEAD)
        if [[ "$BEFORE_HASH" == "$AFTER_HASH" ]]; then
            ok "Schon auf dem aktuellsten Stand — kein Pull nötig"
        else
            ok "Pulled: ${BEFORE_HASH:0:7} → ${AFTER_HASH:0:7}"
            CHANGED=$(git diff --name-only "$BEFORE_HASH" "$AFTER_HASH")
            CHANGED_COUNT=$(echo "$CHANGED" | grep -c .)
            info "${CHANGED_COUNT} Datei(en) aktualisiert"
        fi
    else
        fail "git pull fehlgeschlagen — bitte manuell auflösen"
        exit 1
    fi
fi
echo

# ─── 4. Studio-Edits zurückspielen (nur wenn gestasht) ────────────────
if [[ $RESET_EDITS -eq 0 && -n "$DIRTY_FILES" && $DRY_RUN -eq 0 ]]; then
    step "4. Studio-Edits aus Stash zurückspielen"
    if git stash pop; then
        ok "Stash erfolgreich angewendet"
    else
        warn "Konflikt beim Stash-Pop — manuelle Auflösung nötig"
        warn "Tipp: git status / git diff / dann 'git stash drop' wenn fertig"
        # Wir brechen hier NICHT ab — Update kann mit altem Config-Stand fortfahren,
        # aber der User wird informiert.
    fi
    echo
fi

# ─── 5. Docker-Images ziehen ──────────────────────────────────────────
step "5. Neue Docker-Images von Hub ziehen"
if [[ $DRY_RUN -eq 1 ]]; then
    info "(DRY) docker compose pull backend studio chatbot"
else
    if docker compose pull backend studio chatbot; then
        ok "Images gezogen"
    else
        fail "docker compose pull fehlgeschlagen"
        exit 1
    fi
fi
echo

# ─── 6. Container neu starten ─────────────────────────────────────────
step "6. Container neu starten (--force-recreate)"
if [[ $DRY_RUN -eq 1 ]]; then
    info "(DRY) docker compose up -d --force-recreate backend studio chatbot"
else
    if docker compose up -d --force-recreate backend studio chatbot; then
        ok "Container gestartet"
    else
        fail "docker compose up fehlgeschlagen"
        exit 1
    fi
fi
echo

# ─── 7. Health-Check abwarten ─────────────────────────────────────────
step "7. Backend-Health-Check (max. 60s)"
if [[ $DRY_RUN -eq 1 ]]; then
    info "(DRY) Skip"
else
    HEALTH_OK=0
    for i in $(seq 1 60); do
        if curl -fsS --max-time 2 http://localhost:8000/api/health >/dev/null 2>&1; then
            HEALTH_OK=1
            ok "Backend antwortet nach ${i}s"
            break
        fi
        sleep 1
    done
    if [[ $HEALTH_OK -eq 0 ]]; then
        fail "Backend antwortet nach 60s nicht"
        info "Diagnose: docker compose logs --tail=50 backend"
        exit 1
    fi
fi
echo

# ─── 8. Endpoint-Verifikation ─────────────────────────────────────────
step "8. Endpoint-Verifikation"
if [[ $DRY_RUN -eq 1 ]]; then
    info "(DRY) Skip"
else
    # Health
    HEALTH=$(curl -fsS --max-time 5 http://localhost:8000/api/health || echo "")
    if echo "$HEALTH" | grep -q '"status":"ok"'; then
        ok "/api/health: ok"
    else
        fail "/api/health unerwartet: $HEALTH"
    fi

    # Guide-Mode-Endpoint (öffentlich, kein Auth)
    GM=$(curl -fsS --max-time 5 http://localhost:8000/api/config/guide-mode || echo "")
    if echo "$GM" | grep -q '"allowed_hosts":\['; then
        # Anzahl Hosts in der Liste
        HOST_COUNT=$(echo "$GM" | grep -o '"\*\?[a-z0-9.-]*"' | wc -l)
        if [[ $HOST_COUNT -lt 3 ]]; then
            warn "/api/config/guide-mode: Allow-Liste hat nur ${HOST_COUNT} Einträge — Bind-Mount evtl. nicht aktualisiert?"
            info "Check: ls -la backend/chatbots/wlo/v1/01-base/guide-mode.yaml"
        else
            ok "/api/config/guide-mode: Allow-Liste mit ${HOST_COUNT} Hosts"
        fi
    else
        fail "/api/config/guide-mode unerwartet: ${GM:0:200}"
    fi

    # Widget-Bundle vorhanden?
    if curl -fsS --max-time 5 -I http://localhost:8000/widget/boerdi-widget.js | grep -qi "200 OK"; then
        ok "/widget/boerdi-widget.js: ausgeliefert"
    else
        warn "/widget/boerdi-widget.js: nicht erreichbar"
    fi

    # Container-Status
    PS_OUTPUT=$(docker compose ps --format "table {{.Service}}\t{{.Status}}" 2>/dev/null || true)
    if echo "$PS_OUTPUT" | grep -qE "Up.*\(healthy\)|Up [0-9]"; then
        ok "Container-Status:"
        echo "$PS_OUTPUT" | sed 's/^/    /'
    else
        warn "Container-Status:"
        echo "$PS_OUTPUT" | sed 's/^/    /'
    fi
fi
echo

# ─── Abschluss ────────────────────────────────────────────────────────
if [[ $DRY_RUN -eq 1 ]]; then
    step "DRY-RUN beendet — keine Änderungen geschrieben"
else
    step "Update abgeschlossen"
    echo
    info "Im Studio (Snapshots-Modal) sollte 'Werkseinstellungen' jetzt das"
    info "aktuelle Datum zeigen. Auf einer Embed-Seite (/widget/) muss der"
    info "🧭-Toggle nach Hard-Refresh (Ctrl+F5) sichtbar sein, sofern der"
    info "Host auf der Allow-Liste in 01-base/guide-mode.yaml steht."
    echo
fi
