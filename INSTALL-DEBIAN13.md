# BadBoerdi auf Debian 13 — Docker-Installation

Schritt-für-Schritt-Anleitung für eine produktionsähnliche Installation auf einem
Debian-13-vServer (Trixie). Verwendet **vorgebaute Docker-Images** vom Docker Hub —
kein lokaler Build-Schritt nötig.

**Zielsetup:**

| Komponente | Wo | Zweck |
|---|---|---|
| **Backend** (`jschachtschabel/badboerdi-backend`) | Container, intern :8000 | Chat-API, Pattern-Engine, Safety, RAG, Widget-Auslieferung |
| **Studio** (`jschachtschabel/badboerdi-studio`) | Container, intern :3001 | Konfigurations-UI mit Cookie-Login |
| **Caddy** | Container, öffentlich :80 + :443 | Reverse-Proxy mit automatischen Let's-Encrypt-Zertifikaten |
| **Watchtower** | Container, kein Port | Pullt täglich neue Images |
| **Widget** | Custom-Element `<boerdi-chat>` | Auf beliebige HTTPS-Webseiten einbindbar |

**Empfohlene Server-Größe:** 2 GB RAM, 2 CPU-Kerne, 20+ GB Disk. Mit nur 1 GB läuft
es zwar idle, ist aber unter Last und bei Eval-Runs OOM-gefährdet.

**Was dieser Guide nicht abdeckt:** Anbindung an eine echte Domain (kommt später —
unten als Side-Note erklärt) und Skalierung auf mehrere Backend-Worker. Beides ist
für Test-/Pilot-Deployments unnötig.

---

## 0. Sicherheitshinweis vorab

OpenAI-API-Keys, Studio-Passwörter etc. **niemals** in Chat-Verläufe (Slack, Discord,
ChatGPT, Tickets) posten. Wenn doch passiert: Key sofort in
<https://platform.openai.com/api-keys> revoken und neuen generieren.

Setze in deinem OpenAI-Dashboard ein **Spend-Limit** pro Monat —
<https://platform.openai.com/account/limits>. Sonst kann ein Bot-Loop teuer werden.

---

## 1. System-Vorbereitung

Als `root` einloggen (oder `sudo -i`) und folgende Befehle ausführen.

### 1.1 Updates und Basis-Tools

```bash
apt update && apt upgrade -y
apt install -y curl ca-certificates git ufw jq
```

### 1.2 2-GB-Swap als Sicherheitsnetz

Auf 2-GB-Servern dringend empfohlen — schützt vor OOM-Killer-Ereignissen bei
Eval-Runs oder Reranker-Spitzen.

```bash
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
free -h    # zeigt 2 GiB Swap aktiv
```

### 1.3 Firewall

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp        # SSH
ufw allow 80/tcp        # HTTP (Caddy ACME-Challenge)
ufw allow 443/tcp       # HTTPS (Caddy)
ufw --force enable
ufw status
```

> Wir lassen die Container-Ports `8000` und `3001` **bewusst nicht** durch die
> Firewall — alle externen Zugriffe gehen über Caddy auf Port 443. Falls du erst
> ohne HTTPS testen willst, ergänze `ufw allow 8000/tcp` und `ufw allow 3001/tcp`
> temporär (siehe Kapitel 9).

---

## 2. Docker installieren

Offizieller Installer von docker.com — unterstützt Debian 13 (Trixie):

```bash
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker
docker --version          # erwartet: Docker version 27.x oder 28.x
docker compose version    # erwartet: v2.x
```

---

## 3. Repository klonen

```bash
mkdir -p /opt
cd /opt
git clone https://github.com/janschachtschabel/badboerdi-chatframework.git badboerdi
cd badboerdi
```

Das Repo liefert **`docker-compose.yml`**, **`backend/chatbots/`** (Konfigurations-Tree),
**`backend/knowledge/factory-snapshot.zip`** (Werkseinstellung) — alles was die
Container per Volume-Mount erwarten.

---

## 4. `.env` im Repo-Root anlegen

Der `docker-compose.yml` erwartet eine `.env`-Datei direkt neben sich.

### 4.1 Random-Secrets für Studio-Schutz erzeugen

```bash
echo "STUDIO_API_KEY=$(openssl rand -hex 32)"
echo "STUDIO_PASSWORD=$(openssl rand -hex 16)"
```

→ Beide Werte aus der Ausgabe **notieren** (Studio-Login!).

### 4.2 `.env` schreiben

```bash
cat > /opt/badboerdi/.env <<'EOF'
# ── LLM-Provider ────────────────────────────────────────────────
LLM_PROVIDER=openai
LLM_CHAT_MODEL=gpt-5.4-mini
LLM_EMBED_MODEL=text-embedding-3-small
LLM_VERBOSITY=medium
LLM_REASONING_EFFORT=low

# ── OpenAI ──────────────────────────────────────────────────────
OPENAI_API_KEY=PASTE_NEW_KEY_HERE
# Explizit auf den Default zeigen — verhindert dass docker-compose's
# ${OPENAI_BASE_URL:-} einen leeren String an die SDK durchreicht.
# Aktuelle Backend-Images fangen das selbst ab; der explizite Eintrag
# schützt zusätzlich gegen Image-Versionen vor dem Fix (April 2026).
OPENAI_BASE_URL=https://api.openai.com/v1

# ── B-API (nur wenn LLM_PROVIDER=b-api-* — sonst ignoriert) ────
# Default = PROD. Für Integration-Tests gegen die Staging-Instanz
# stattdessen: https://b-api.staging.openeduhub.net/api/v1/llm
B_API_KEY=
B_API_BASE_URL=https://b-api.prod.openeduhub.net/api/v1/llm

# ── MCP / RAG (Defaults reichen) ────────────────────────────────
MCP_SERVER_URL=https://wlo-mcp-server.vercel.app/mcp
RAG_TOP_K=5
RAG_MIN_SCORE=0.3
RAG_MAX_CHARS_PER_AREA=2000

# ── Text-Extraction (für Remix-Feature, Phase 2) ────────────────
# Erwartet Base-URL — /from-url wird intern angehängt.
# Default = PROD. Staging-Variante:
#   TEXT_EXTRACTION_URL=https://text-extraction.staging.openeduhub.net
TEXT_EXTRACTION_URL=https://text-extraction.prod.openeduhub.net

# ── Studio-Schutz ───────────────────────────────────────────────
STUDIO_API_KEY=REPLACE_WITH_GENERATED_KEY
STUDIO_PASSWORD=REPLACE_WITH_GENERATED_PASSWORD

# ── Sonstiges ───────────────────────────────────────────────────
CORS_ORIGINS=*
LOG_LEVEL=INFO
TZ=Europe/Berlin

# Auto-Update-Frequenz (Sekunden). 86400 = 1x täglich. Default 300 ist zu aggressiv für 2-GB-Server.
WATCHTOWER_POLL_INTERVAL=86400
EOF

# Platzhalter ersetzen
nano /opt/badboerdi/.env
```

In `nano`:
- `OPENAI_API_KEY=` mit dem **frisch generierten** Key (nie aus Chat-Verläufen!)
- `STUDIO_API_KEY=` mit dem 64-Zeichen-Hex-Wert von oben
- `STUDIO_PASSWORD=` mit dem 32-Zeichen-Hex-Wert von oben

Speichern: `Strg+O`, `Enter`, `Strg+X`.

### 4.3 Optional: B-API mit OpenAI-Fallback für Moderation/Speech

Wenn du `LLM_PROVIDER=b-api-openai` oder `b-api-academiccloud` nutzt
(Chat + Embeddings über die B-API von edu-sharing), aber zusätzlich einen
`OPENAI_API_KEY` einträgst, nutzt das Backend OpenAI als **Side-Channel**
für Features, die die B-API nicht weiterleitet:

| Feature | B-API forwarded? | Mit OpenAI-Key parallel |
|---|:-:|:-:|
| Chat (`/v1/chat/completions`) | ✓ | weiter über B-API |
| Embeddings (`/v1/embeddings`) | ✓ | weiter über B-API |
| Moderation (`/v1/moderations`) | ✗ | ✓ über OpenAI (kostenlos) |
| Speech-to-Text (`/v1/audio/transcriptions`) | ✗ | ✓ über OpenAI |
| Text-to-Speech (`/v1/audio/speech`) | ✗ | ✓ über OpenAI |

Ohne `OPENAI_API_KEY` werden diese drei Features auf B-API-Setups still
übersprungen — das Backend funktioniert weiter, nur Moderation läuft dann
nur über die Regex-Safety-Floor.

---

## 5. Container starten

Wir lassen das **Chatbot-Frontend** (Port 8080, eigenständige Angular-App) bewusst
weg — Endnutzer-Zugang läuft per Widget-Embedding (Kapitel 8). Wer die Standalone-App
trotzdem will, ergänzt `chatbot` zur `docker compose up`-Befehlsliste.

```bash
cd /opt/badboerdi

# Pre-built Images vom Docker Hub ziehen
docker compose pull backend studio watchtower

# Im Hintergrund starten
docker compose up -d backend studio watchtower

# Status checken
docker compose ps
```

Der **erste Start** dauert ~30 Sekunden, weil das Backend den Factory-Snapshot
in die leere DB entpackt:

```bash
docker compose logs backend | grep -i factory
# → Empty DB + factory snapshot present → restoring from /app/knowledge/factory-snapshot.zip
# → Factory restore: 58 config files, db_restored=True
```

Das passiert nur **einmalig**. Spätere Restarts überspringen den Schritt
(Versions-Marker in der DB).

---

## 6. Verifikation

```bash
# Backend antwortet?
curl -s http://localhost:8000/health
# → {"status":"ok"}
# (Wird auch vom Docker-HEALTHCHECK alle 30s aufgerufen — siehe `docker compose ps`,
# Spalte STATUS sollte "healthy" zeigen.)

# Studio aktiv (mit Cookie-Login)?
curl -I http://localhost:3001
# → HTTP/1.1 307 Temporary Redirect, Location: /login?from=/

# Memory-Verbrauch?
docker stats --no-stream
# Erwarte:
#   backend  ~300-600 MB
#   studio   ~100-200 MB
#   watchtower idle

# Sessions werden in der DB persistiert?
docker compose exec backend python -c "
import sqlite3
db = sqlite3.connect('/data/badboerdi.db')
print('sessions:', db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0])
print('messages:', db.execute('SELECT COUNT(*) FROM messages').fetchone()[0])
"
```

---

## 7. HTTPS via Caddy + nip.io (kein Domain-Kauf nötig)

`nip.io` ist ein kostenloser Wildcard-DNS: jeder Hostname `<irgendwas>.<deine-IP>.nip.io`
löst automatisch zu deiner IP auf. Damit kann Caddy ganz normale Let's-Encrypt-Zertifikate
ziehen und du hast vollwertiges HTTPS ohne eigene Domain registrieren zu müssen.

Wenn du die echte IP deines Servers nicht weißt:
```bash
curl -s https://api.ipify.org
# → 85.215.211.50  (Beispiel)
```

In den folgenden Befehlen `<DEINE-IP>` durch die tatsächliche IP ersetzen.

### 7.1 Caddyfile

```bash
cd /opt/badboerdi
cat > Caddyfile <<'EOF'
chat.<DEINE-IP>.nip.io {
  reverse_proxy backend:8000
  encode gzip
}

studio.<DEINE-IP>.nip.io {
  reverse_proxy studio:3001
  encode gzip
}
EOF

# IP einsetzen, z.B.:
sed -i 's/<DEINE-IP>/85.215.211.50/g' Caddyfile
```

### 7.2 docker-compose.override.yml

Die Override-Datei ergänzt die `docker-compose.yml` ohne sie zu modifizieren —
beim nächsten `git pull` gibt's keinen Konflikt.

```bash
cat > /opt/badboerdi/docker-compose.override.yml <<'EOF'
services:
  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config

  # Memory-Limits gegen OOM-Spitzen (auf 2-GB-Servern empfohlen)
  backend:
    mem_limit: 1200m
    memswap_limit: 1500m

  studio:
    mem_limit: 512m
    memswap_limit: 700m

volumes:
  caddy_data:
  caddy_config:
EOF
```

### 7.3 Caddy starten

```bash
cd /opt/badboerdi
docker compose up -d caddy

# Caddy braucht ~30-40 Sekunden für die ersten ACME-Challenges
sleep 40
docker compose logs caddy | tail -20
# → "certificate obtained successfully"  (zwei Zeilen, einmal pro Subdomain)
```

### 7.4 Test

```bash
# IP entsprechend ersetzen
curl -I https://chat.85.215.211.50.nip.io/health
# → HTTP/2 200

curl -I https://studio.85.215.211.50.nip.io
# → HTTP/2 307  (Redirect auf /login — Cookie-Schutz aktiv)
```

**Browser-URLs** (deine IP entsprechend einsetzen):
- **Studio:** <https://studio.85.215.211.50.nip.io>
- **Backend Health:** <https://chat.85.215.211.50.nip.io/health>
- **Widget-Demo-Seite:** <https://chat.85.215.211.50.nip.io/widget/>

---

## 8. Widget einbinden

Das Backend liefert den Widget-Bundle selbst aus. Auf einer beliebigen
**HTTPS-Webseite** einbinden:

```html
<script src="https://chat.85.215.211.50.nip.io/widget/boerdi-widget.js" defer></script>

<boerdi-chat
  api-url="https://chat.85.215.211.50.nip.io"
  position="bottom-right"
  primary-color="#1c4587"
  show-debug-button="false"
  show-language-buttons="true">
</boerdi-chat>
```

Vollständige Attribut-Referenz im **Studio → System → Info → Widget-Einbettung**
oder in [`frontend/README.md`](frontend/README.md).

### Häufige Frage: Browser fragt nach „andere Apps und Dienste"

Das ist die **Mikrofon-Berechtigung** — wird vom 🎤-Button ausgelöst (Spracheingabe).

| Klick | Folge |
|---|---|
| **Zulassen** | Mic-Button funktioniert |
| **Blockieren** | Chat läuft normal weiter, nur Mic-Button wirft Fehler beim Klick |

Wenn du den Prompt komplett vermeiden willst, beim Embedding einfach
`show-language-buttons="false"` setzen — dann werden 🔊 und 🎤 gar nicht erst gerendert.

Mit einer eigenen Domain (statt nip.io) fragt der Browser meist erst beim
tatsächlichen Klick auf 🎤, nicht direkt beim Page-Load.

---

## 9. Optional: Direkter Container-Zugriff zum Debuggen

Wenn du **vor** dem HTTPS-Setup direkt auf Backend / Studio zugreifen willst
(z.B. aus dem Browser auf deinem Laptop ohne Caddy):

```bash
ufw allow 8000/tcp     # Backend
ufw allow 3001/tcp     # Studio
```

Browser:
- Backend: `http://<DEINE-IP>:8000/health`
- Studio: `http://<DEINE-IP>:3001`

**Wichtig**: Nach dem Caddy-Setup wieder schließen:
```bash
ufw delete allow 8000/tcp
ufw delete allow 3001/tcp
```

Sonst sind die Services parallel ohne TLS erreichbar.

---

## 10. Tägliches Backup der Datenbank

SQLite-Vec-DBs sind ohne Backup nicht trivial wiederherzustellen. Cronjob anlegen:

```bash
mkdir -p /var/backups/badboerdi
cat > /etc/cron.d/badboerdi-backup <<'EOF'
# Daily 03:00 — DB-Snapshot
0 3 * * * root cd /opt/badboerdi && docker compose exec -T backend sh -c "cp /data/badboerdi.db /data/backup-$(date +\%F).db" && docker compose cp backend:/data/backup-$(date +\%F).db /var/backups/badboerdi/ && docker compose exec -T backend rm /data/backup-$(date +\%F).db
# Wöchentliche Bereinigung — älter als 14 Tage löschen
0 4 * * 0 root find /var/backups/badboerdi/ -name 'backup-*.db' -mtime +14 -delete
EOF
```

Alternativ kannst du im **Studio** im Snapshots-Modal jederzeit einen
Server-Snapshot anlegen — der enthält Configs **+ DB**.

---

## 10a. Wöchentlicher Docker-Cleanup (empfohlen bei kleiner Disk)

Watchtower zieht regelmäßig neue Images. Ohne Cleanup häufen sich alte
Image-Layer und können auf 10-GB-Disks zu `no space left on device` führen
(typisch nach 3-4 Auto-Updates). Empfohlen für Server unter 20 GB Root-Disk:

```bash
sudo tee /etc/cron.weekly/docker-cleanup > /dev/null <<'EOF'
#!/bin/sh
# Boerdi: weekly Docker image+builder cleanup. Volumes (DB) bleiben unangetastet.
docker image prune -af   >> /var/log/docker-cleanup.log 2>&1
docker builder prune -af >> /var/log/docker-cleanup.log 2>&1
EOF
sudo chmod +x /etc/cron.weekly/docker-cleanup
```

Test des Scripts:
```bash
sudo /etc/cron.weekly/docker-cleanup && tail /var/log/docker-cleanup.log
```

**Falls die Disk gerade voll ist** (Symptom: `docker compose pull` schlägt mit
`no space left on device` fehl):
```bash
docker image prune -af       # zieht typisch 500 MB - 1 GB
docker builder prune -af     # zusätzlich, falls Build-Cache da
df -h /var/lib/docker        # prüfen ob's gereicht hat
docker compose pull          # erneut versuchen
```

⚠️ **Niemals** `docker system prune -af --volumes` — das löscht das
`backend_data`-Volume samt SQLite-DB. Nur Image-/Builder-Pruning ist sicher.

---

## 11. Updates

Die Watchtower-Komponente pullt täglich (`WATCHTOWER_POLL_INTERVAL=86400`) neue
Versionen der Images vom Docker Hub und startet die Container neu wenn nötig.

Manuell anstoßen:

```bash
cd /opt/badboerdi
docker compose pull
docker compose up -d backend studio
```

Bei größeren Schema-Änderungen (selten) eventuell:
```bash
docker compose down -v   # ⚠️ löscht das DB-Volume!
docker compose up -d
# → Backend entpackt Factory-Snapshot wie bei Erstinstallation
```

`-v` nur verwenden wenn du **wirklich** zurück auf Werkseinstellung willst.

---

## 12. Echte Domain anbinden (später)

Sobald du eine Domain hast (z.B. `badboerdi.de`):

1. DNS-A-Records für `chat.badboerdi.de` und `studio.badboerdi.de` auf die Server-IP
   setzen
2. `Caddyfile` editieren — alle nip.io-Hostnames durch die echten ersetzen
3. `docker compose restart caddy` — Caddy holt neue Zertifikate für die Domain
4. Widget-Embeddings auf die neue URL umstellen

DB und Configs bleiben unberührt — sind in Volumes / Bind-Mounts.

---

## 13. Troubleshooting

| Problem | Diagnose / Fix |
|---|---|
| Backend startet nicht | `docker compose logs backend` — meist fehlender / falscher OPENAI_API_KEY |
| `/api/chat` → HTTP 500 mit `httpx.UnsupportedProtocol` im Log | Älteres Backend-Image + `OPENAI_BASE_URL=` (leerer String) → SDK kann URL nicht parsen. **Fix:** in `.env` explizit `OPENAI_BASE_URL=https://api.openai.com/v1` setzen, dann `docker compose up -d --force-recreate backend`. Alternativ: Image rebuilden — aktuelle Versionen handhaben das selbst. |
| `/api/chat` → 200 aber `content` enthält `unexpected keyword argument 'verbosity'` | Backend-Image nutzt `openai`-SDK < 1.65 (kein GPT-5-Support). **Fix A** (kurzfristig): Modell auf `gpt-4.1-mini` umstellen. **Fix B**: Image rebuilden mit aktuellem `requirements.txt` (`openai>=1.78`). |
| Sessions im Studio leer trotz Chat-Aktivität | (1) Backend-Log prüfen: `docker compose logs backend \| grep "GET /api/sessions"`. Wenn `307 Temporary Redirect` ohne nachfolgenden `200 OK` erscheint, ist's der Trailing-Slash-Bug — Studio muss auf eine Version >= 28.04.2026 (`docker compose pull && up -d studio`). (2) STUDIO_API_KEY-Mismatch: `docker compose exec backend env \| grep STUDIO_API_KEY` mit `docker compose exec studio env \| grep STUDIO_API_KEY` vergleichen — müssen identisch sein. Ggf. `docker compose up -d --force-recreate studio backend`. (3) DB-Persistenz: `docker compose exec backend python -c "import sqlite3; print(sqlite3.connect('/data/badboerdi.db').execute('SELECT COUNT(*) FROM sessions').fetchone())"` zeigt, ob Sessions überhaupt geschrieben werden. |
| `no space left on device` beim Image-Pull | Docker-Cache zu groß für die Disk. Fix: `docker image prune -af && docker builder prune -af`. Vorbeugend Cron einrichten — siehe Kapitel 10a. |
| Moderation läuft auf B-API-Setup nicht | B-API forwarded `/v1/moderations` nicht. **Fix:** zusätzlich `OPENAI_API_KEY=...` setzen — Backend nutzt OpenAI dann als Side-Channel für Moderation/STT/TTS. |
| `502 Bad Gateway` von Caddy | Backend / Studio noch nicht hochgefahren — `docker compose ps`, ggf. `restart` |
| Caddy holt keine Zertifikate | Port 80 zugemacht? UFW-Regel checken. Logs: `docker compose logs caddy` zeigt ACME-Errors |
| Studio fragt nach Login, Passwort akzeptiert es nicht | `STUDIO_PASSWORD` in `.env` mit dem im Browser eingegebenen vergleichen, ggf. neu setzen + `docker compose up -d --force-recreate studio` |
| Memory-Verbrauch > 1,5 GB | `docker stats` — meist parallel laufender Eval-Run. Mit Limits in `docker-compose.override.yml` capping |
| Mixed-Content im Browser-Konsole | Backend wurde noch über HTTP angesprochen statt HTTPS. `api-url` im Widget auf `https://...` ändern |
| Werkseinstellung nicht entpackt | DB nicht leer? `docker compose exec backend ls -la /data/` — bei vorhandener `badboerdi.db` skipped der Restore |
| Komplett-Reset nötig | `docker compose down -v && docker compose up -d backend studio` (löscht DB-Volume → Factory-Restore beim nächsten Start) |

### Logs ansehen

```bash
# Live-Logs aller Container
docker compose logs -f

# Nur Backend, letzte 100 Zeilen
docker compose logs --tail=100 backend

# Caddy
docker compose logs caddy
```

### Container-Shell für Debugging

```bash
docker compose exec backend bash
# → /app # ls
docker compose exec studio sh
```

---

## 14. Sicherheits-Checkliste

- [x] **Swap aktiv** (`swapon --show`)
- [x] **UFW aktiv mit minimalen Ports** (`ufw status`)
- [x] **`.env` ist `0600` und gehört root** (`ls -la /opt/badboerdi/.env`) — falls nicht: `chmod 600 .env && chown root:root .env`
- [x] **STUDIO_API_KEY und STUDIO_PASSWORD gesetzt** und nirgends sonst gespeichert
- [x] **OpenAI Spend-Limit konfiguriert** im Dashboard
- [x] **Daily DB-Backup** läuft (Cronjob, siehe Kapitel 10)
- [x] **HTTPS aktiv** über Caddy (Browser zeigt Schloss)
- [ ] **Optional: SSH-Login nur via Schlüssel** (`/etc/ssh/sshd_config` → `PasswordAuthentication no`)
- [ ] **Optional: fail2ban** gegen SSH-Bruteforce (`apt install fail2ban`)

---

## 15. Befehlsreferenz

| Aktion | Befehl |
|---|---|
| Status aller Container | `docker compose ps` |
| Memory live | `docker stats` |
| Logs live | `docker compose logs -f` |
| Container neu starten | `docker compose restart backend` |
| Konfig-Änderung übernehmen | `.env` editieren → `docker compose up -d` (recreate) |
| Routing-Rules zur Laufzeit reloaden | `curl -X POST http://localhost:8000/api/routing-rules/reload` |
| Snapshot anlegen | Studio → 📦-Symbol → „Neuer Snapshot" |
| Werkseinstellung wiederherstellen | Studio → 📦 → gelber Block → „Zurücksetzen" |
| Backend-DB sichern | `docker compose exec backend sh -c 'cp /data/badboerdi.db /data/backup.db'` |
| Update aller Images | `docker compose pull && docker compose up -d` |
| Komplett aufräumen (⚠️ löscht DB) | `docker compose down -v` |

---

## 16. Verweise

- **Architektur-Doku:** [`README.md`](README.md) (Schichten, Patterns, Routing-Rules-Engine)
- **Backend-Endpoints:** [`backend/README.md`](backend/README.md)
- **Widget-Attribute:** [`frontend/README.md`](frontend/README.md)
- **Studio-Komponenten:** [`studio/README.md`](studio/README.md)
- **Werkseinstellungs-System:** [`backend/knowledge/README.md`](backend/knowledge/README.md)
