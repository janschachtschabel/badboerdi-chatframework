# Deployment-Anleitung

> **Google Colab Notebook:** [BadBoerdi im Browser ausprobieren](https://drive.google.com/file/d/1BFZpEEogOYJa50k7NRxuUVA12Hb89x96/view?usp=sharing) — komplettes Setup ohne lokale Installation.

## Inhalt

1. [Lokales Setup (Windows + Docker Desktop)](#1-lokales-setup)
2. [Produktions-Deployment](#2-produktions-deployment)
3. [Chat-Widget einbinden](#3-chat-widget-einbinden)
4. [RAG-Wissensbasis (Seed-System)](#4-rag-wissensbasis-seed-system)
5. [B-API statt OpenAI](#5-b-api-statt-openai)
6. [Google Colab Notebook](#6-google-colab-notebook)

---

## 1. Lokales Setup

**Voraussetzungen:** Windows 10/11, [Docker Desktop](https://www.docker.com/products/docker-desktop/) installiert und gestartet.

### Schritt 1 — Arbeitsverzeichnis

```powershell
mkdir C:\badboerdi
cd C:\badboerdi
```

### Schritt 2 — docker-compose.yml

Erstelle die Datei `C:\badboerdi\docker-compose.yml`:

```yaml
services:
  backend:
    image: jschachtschabel/badboerdi-backend:latest
    container_name: badboerdi-backend
    restart: unless-stopped
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      - DATABASE_PATH=/data/badboerdi.db
    volumes:
      - backend_data:/data

  chatbot:
    image: jschachtschabel/badboerdi-chatbot:latest
    container_name: badboerdi-chatbot
    restart: unless-stopped
    ports:
      - "8080:80"
    environment:
      - BACKEND_URL=http://localhost:8000
    depends_on:
      - backend

  studio:
    image: jschachtschabel/badboerdi-studio:latest
    container_name: badboerdi-studio
    restart: unless-stopped
    ports:
      - "3001:3001"
    environment:
      - BACKEND_URL=http://backend:8000
    depends_on:
      - backend

volumes:
  backend_data:
```

### Schritt 3 — .env

Erstelle die Datei `C:\badboerdi\.env`:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-DEIN-OPENAI-KEY-HIER
```

**Nur diese zwei Zeilen werden benoetigt.** Den OpenAI-Key erhaeltst du unter https://platform.openai.com/api-keys.

### Schritt 4 — Starten

```powershell
docker compose pull
docker compose up -d
```

### Schritt 5 — Testen

| Dienst | URL | Erwartung |
|--------|-----|-----------|
| Backend Health | http://localhost:8000/health | `{"status":"ok","provider":"openai",...}` |
| Backend API-Docs | http://localhost:8000/docs | Swagger-Oberflaeche |
| Chatbot | http://localhost:8080 | Hostseite mit Eulen-Button unten rechts |
| Widget-Demo | http://localhost:8000/widget/ | Demo-Seite mit eingebettetem Chat |
| Studio | http://localhost:3001 | Konfigurations-Oberflaeche |

### Nuetzliche Befehle

```powershell
docker compose logs -f backend      # Backend-Logs live
docker compose logs -f studio       # Studio-Logs live
docker compose ps                   # Status aller Container
docker compose down                 # Stoppen (Daten bleiben)
docker compose down -v              # Stoppen + Daten loeschen (Reset)
docker compose pull && docker compose up -d   # Update auf neueste Images
```

---

## 2. Produktions-Deployment

Fuer den Produktionsbetrieb werden **nur Backend und Studio** gehostet. Die Chatbot-Hostseite ist optional — in der Praxis wird das Widget direkt in die Zielseite (z.B. wirlernenonline.de) eingebettet.

### Schritt 1 — Server vorbereiten

Voraussetzung: Linux-Server mit Docker + Docker Compose.

```bash
mkdir -p /opt/badboerdi && cd /opt/badboerdi
```

### Schritt 2 — docker-compose.yml

```yaml
services:
  backend:
    image: jschachtschabel/badboerdi-backend:latest
    container_name: badboerdi-backend
    restart: unless-stopped
    ports:
      - "127.0.0.1:8000:8000"
    env_file:
      - .env
    environment:
      - DATABASE_PATH=/data/badboerdi.db
    volumes:
      - backend_data:/data
      - ./chatbots:/app/chatbots
    labels:
      - "com.centurylinklabs.watchtower.enable=true"

  studio:
    image: jschachtschabel/badboerdi-studio:latest
    container_name: badboerdi-studio
    restart: unless-stopped
    ports:
      - "127.0.0.1:3001:3001"
    environment:
      - BACKEND_URL=http://backend:8000
      - STUDIO_API_KEY=${STUDIO_API_KEY}
      - STUDIO_PASSWORD=${STUDIO_PASSWORD}
    depends_on:
      - backend
    labels:
      - "com.centurylinklabs.watchtower.enable=true"

  watchtower:
    image: containrrr/watchtower:latest
    container_name: badboerdi-watchtower
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - TZ=Europe/Berlin
      - WATCHTOWER_CLEANUP=true
      - WATCHTOWER_LABEL_ENABLE=true
      - WATCHTOWER_POLL_INTERVAL=300

volumes:
  backend_data:
```

**Wichtige Unterschiede zum lokalen Setup:**
- Ports binden an `127.0.0.1` (nicht von aussen erreichbar — Reverse-Proxy davor!)
- `STUDIO_API_KEY` und `STUDIO_PASSWORD` sind gesetzt (fehlt `STUDIO_API_KEY`, loggt das Backend eine Warnung beim Start). Schuetzt `/api/config`, `/api/rag`, `/api/safety`, `/api/quality`
- `CORS_ORIGINS` auf spezifische Domains beschraenkt (nicht `*`)
- `chatbots/` als Bind-Mount (Config-Aenderungen ueber Studio bleiben bei Container-Updates erhalten)
- Watchtower fuer automatische Image-Updates

### Schritt 3 — .env (Produktion)

```env
# LLM
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-DEIN-PRODUKTIONS-KEY

# Studio-Sicherheit
STUDIO_API_KEY=LANGER-ZUFALLS-STRING-HIER
STUDIO_PASSWORD=SICHERES-PASSWORT-HIER

# CORS — nur die tatsaechlich verwendeten Origins erlauben
CORS_ORIGINS=https://wirlernenonline.de,https://studio.meinedomain.de,https://api.meinedomain.de
```

**Keys generieren:**
```bash
# STUDIO_API_KEY (32 Byte Hex)
openssl rand -hex 32

# STUDIO_PASSWORD (beliebig, z.B.)
openssl rand -base64 24
```

### Schritt 4 — Reverse-Proxy (Caddy-Beispiel)

Datei `/etc/caddy/Caddyfile`:

```
api.meinedomain.de {
    reverse_proxy localhost:8000
}

studio.meinedomain.de {
    reverse_proxy localhost:3001
}
```

```bash
sudo systemctl restart caddy
```

Caddy holt automatisch Let's-Encrypt-Zertifikate. Backend ist dann unter `https://api.meinedomain.de` erreichbar, Studio unter `https://studio.meinedomain.de`.

### Schritt 5 — Starten

```bash
docker compose pull
docker compose up -d
docker compose logs -f
```

### Schritt 6 — Smoke-Tests

```bash
curl https://api.meinedomain.de/health
# → {"status":"ok","provider":"openai",...}

curl https://studio.meinedomain.de
# → Redirect auf /login (Passwortschutz aktiv)
```

### Auto-Updates

Watchtower prueft alle 5 Minuten Docker Hub auf neue `:latest`-Images. Ablauf:
1. Push auf `main` → GitHub Actions baut neue Images (~5 min)
2. Watchtower erkennt neues Image-Digest → zieht Image → Rolling Restart
3. Volumes und Bind-Mounts bleiben erhalten

Ueberwachung:
```bash
docker compose logs watchtower
```

---

## 3. Chat-Widget einbinden

Das Widget wird als Web Component `<boerdi-chat>` ausgeliefert und kann in jede HTML-Seite eingebettet werden.

### Variante A — Schwebender Button (Standard)

Das Widget erscheint als rundes Eulen-Icon in einer Bildschirmecke. Ein Klick oeffnet das Chat-Panel.

```html
<script src="https://api.meinedomain.de/widget/boerdi-widget.js" defer></script>
<boerdi-chat
  api-url="https://api.meinedomain.de"
  position="bottom-right"
  primary-color="#1c4587"
  initial-state="collapsed"
  greeting="Hallo! Wie kann ich dir helfen?"
  persist-session="true"
  auto-context="true">
</boerdi-chat>
```

### Variante B — Direkt geoeffnet (ohne Klick)

Das Widget startet sofort im offenen Zustand.

```html
<script src="https://api.meinedomain.de/widget/boerdi-widget.js" defer></script>
<boerdi-chat
  api-url="https://api.meinedomain.de"
  initial-state="expanded"
  position="bottom-right"
  primary-color="#1c4587">
</boerdi-chat>
```

### Variante C — Eingebettet in einen Container (Inline, kein schwebender Button)

Das Widget wird in einen festen Container auf der Seite eingebettet, ohne schwebendes Icon.

```html
<div id="chat-container" style="width: 100%; max-width: 500px; height: 700px; border: 1px solid #e5e7eb; border-radius: 12px; overflow: hidden;">
  <script src="https://api.meinedomain.de/widget/boerdi-widget.js" defer></script>

  <style>
    #chat-container boerdi-chat {
      --boerdi-position: static;
    }
    /* Shadow-DOM-Overrides fuer Inline-Modus */
    #chat-container boerdi-chat::part(widget) {
      position: static !important;
      width: 100% !important;
      height: 100% !important;
    }
  </style>

  <boerdi-chat
    api-url="https://api.meinedomain.de"
    initial-state="expanded"
    primary-color="#1c4587">
  </boerdi-chat>
</div>
```

**Hinweis:** Der Inline-Modus erfordert CSS-Overrides fuer die Shadow-DOM-Positionierung. Nicht alle Styles lassen sich von aussen ueberschreiben. Fuer eine native Inline-Unterstuetzung muesste das Angular-Widget um eine `mode="inline"`-Property erweitert werden.

### Alle Widget-Properties

| Property | Typ | Default | Beschreibung |
|----------|-----|---------|--------------|
| `api-url` | String | `/api` | Backend-URL (aus Browser-Sicht erreichbar!) |
| `position` | Enum | `bottom-right` | `bottom-right`, `bottom-left`, `top-right`, `top-left` |
| `initial-state` | Enum | `collapsed` | `collapsed` (nur Button) oder `expanded` (Panel offen) |
| `primary-color` | Hex-Farbe | `#1c4587` | Akzentfarbe (Header, Button) |
| `greeting` | String | BOERDi-Standard | Begruessung beim ersten Oeffnen |
| `persist-session` | Boolean | `true` | Session-ID in localStorage speichern (Cross-Page) |
| `session-key` | String | `boerdi_session_id` | localStorage-Key fuer Session |
| `page-context` | JSON-String | `""` | Zusaetzlicher Kontext (z.B. `'{"thema":"eiszeit"}'`) |
| `auto-context` | Boolean | `true` | Automatisch URL, Titel, Referrer erfassen |

### Backend-URL zur Laufzeit setzen

Alternativ zur `api-url`-Property kann die Backend-URL global gesetzt werden:

```html
<script>
  window.BOERDI_API_URL = "https://api.meinedomain.de";
</script>
<script src="https://api.meinedomain.de/widget/boerdi-widget.js" defer></script>
<boerdi-chat></boerdi-chat>
```

---

## 4. RAG-Wissensbasis (Seed-System)

Das Backend liefert eine **initiale Wissensbasis** als JSON-Seed-Datei mit (`knowledge/rag-seed.json`). So funktioniert bei jeder Neuinstallation der Chatbot sofort mit Grundwissen, ohne dass zuerst Dokumente im Studio hochgeladen werden muessen.

### Automatischer Import beim Start

Beim Start prueft das Backend die Seed-Version (Datumsformat, z.B. `2026-04-11`) gegen die in der Datenbank gespeicherte Version (`meta`-Tabelle):

| Situation | Verhalten |
|-----------|-----------|
| Leere Datenbank (Neuinstallation) | Alle Seed-Chunks werden importiert |
| Gleiche Seed-Version wie in DB | Skip — nichts passiert |
| Neuere Seed-Version mit **neuen Areas** | Nur die neuen Areas werden importiert, bestehende (evtl. via Studio editierte) bleiben unberuehrt |
| Neuere Seed-Version ohne neue Areas | Nur der Version-Marker wird aktualisiert |

Nach dem Import werden Embeddings im Hintergrund generiert (benoetigt LLM-API-Key).

**Aktueller Seed (Version `2026-04-11`):** 348 Chunks in 4 Bereichen:

| Bereich | Chunks | Beschreibung |
|---------|--------|--------------|
| `edu-sharing-com-webseite` | 54 | edu-sharing als Open-Source-Loesung fuer Bildungscloud, E-Learning, Suche und Content-Management |
| `edu-sharing-net-webseite` | 37 | edu-sharing.net e.V. — gemeinnuetziges Netzwerk fuer digitale Bildungsclouds und OER |
| `wirlernenonline.de-webseite` | 106 | WirLernenOnline — offene Bildungsplattform mit Suchmaschine, Fachportalen und Community |
| `wissenlebtonline-webseite` | 151 | WLO-Oekosystem — KI-gestuetzte Infrastruktur fuer Bildungsinhalte |

### Seed aktualisieren (Entwickler-Workflow)

1. Im Studio die RAG-Wissensbereiche bearbeiten (Dokumente hochladen/loeschen)
2. Datenbank aus dem Docker-Container kopieren:
   ```bash
   docker cp badboerdi-backend:/data/badboerdi.db badboerdi-docker.db
   ```
3. Export ausfuehren (Version wird automatisch auf das aktuelle Datum gesetzt):
   ```bash
   cd backend
   python scripts/rag_export.py --db badboerdi-docker.db
   ```
   Optional mit expliziter Version:
   ```bash
   python scripts/rag_export.py --db badboerdi-docker.db --version 2026-05-01
   ```
4. Die aktualisierte `knowledge/rag-seed.json` committen und pushen
5. Bestehende Deployments erhalten die neuen Areas automatisch beim naechsten Container-Restart (via Watchtower oder manuell)

### Embeddings manuell generieren

Falls Embeddings nach dem Import fehlen (z.B. wegen fehlendem API-Key beim Start):

```bash
curl -X POST http://localhost:8000/api/rag/embed
```

---

## 5. B-API statt OpenAI

Das Framework unterstuetzt neben OpenAI auch die **B-API** (Bildungs-API) als LLM-Provider. Die B-API ist ein Proxy-Dienst, der verschiedene Modelle (inkl. Open-Source) ueber eine OpenAI-kompatible Schnittstelle bereitstellt.

### Konfiguration

**.env fuer B-API mit OpenAI-Modellen:**
```env
LLM_PROVIDER=b-api-openai
B_API_KEY=DEIN-B-API-KEY
B_API_BASE_URL=https://b-api.2bn.de/api/v1/llm
LLM_CHAT_MODEL=gpt-4.1-mini
LLM_EMBED_MODEL=text-embedding-3-small
OPENAI_API_KEY=sk-...
```

**.env fuer B-API mit AcademicCloud (Open-Source):**
```env
LLM_PROVIDER=b-api-academiccloud
B_API_KEY=DEIN-B-API-KEY
B_API_BASE_URL=https://b-api.2bn.de/api/v1/llm
LLM_CHAT_MODEL=Qwen/Qwen3.5-122B
LLM_EMBED_MODEL=e5-mistral-7b-instruct
```

### Was nicht mehr funktioniert (B-API-Einschraenkungen)

Beim Wechsel von `openai` auf einen B-API-Provider verlierst du folgende Features:

| Feature | openai | b-api-openai | b-api-academiccloud |
|---------|:------:|:------------:|:-------------------:|
| Chat (Textantworten) | x | x | x |
| MCP-Tool-Calls (WLO-Suche) | x | x | eingeschraenkt* |
| RAG-Wissensabfrage | x | x | x |
| Safety Stage 2 (OpenAI Moderation) | x | - | - |
| Safety Stage 3 (Legal Classifier) | x | x | eingeschraenkt* |
| Whisper STT (Spracheingabe) | x | - | - |
| TTS (Sprachausgabe) | x | - | - |
| JSON-Mode (strukturierte Ausgabe) | x | x | eingeschraenkt* |
| Embedding-Kompatibilitaet | x | x | inkompatibel** |

**Legende:**
- `x` = voll funktionsfaehig
- `-` = nicht verfuegbar (Feature deaktiviert, Fallback greift)
- `eingeschraenkt*` = Modellabhaengig. Tool-Calling und JSON-Mode funktionieren nicht mit allen Modellen auf AcademicCloud zuverlaessig.
- `inkompatibel**` = AcademicCloud nutzt `e5-mistral-7b-instruct` (1024 Dimensionen), OpenAI nutzt `text-embedding-3-small` (1536 Dimensionen). **Nach einem Provider-Wechsel muessen alle RAG-Dokumente neu indexiert werden**, da die Vektoren nicht kompatibel sind.

### Detailerklaerung der Einschraenkungen

**OpenAI Moderation (Stage 2):**
Die OpenAI Moderation API (`omni-moderation-latest`) ist kostenlos, aber nur mit einem nativen OpenAI-API-Key nutzbar. Bei B-API-Providern wird Stage 2 uebersprungen. Kompensation: Stage 1 (Regex) und Stage 3 (LLM Legal Classifier) laufen weiterhin.

**Tipp:** Setze auch bei B-API-Nutzung `OPENAI_API_KEY` in der `.env`. Dann wird Stage 2 trotzdem ausgefuehrt (der Moderation-Call geht direkt an OpenAI, der Chat-Call ueber die B-API). Der Moderation-Call ist kostenlos.

**Whisper & TTS:**
Spracherkennung (Whisper) und Sprachsynthese (TTS) benoetigen den nativen OpenAI-Endpunkt. Bei B-API-Providern sind die `/api/speech/transcribe` und `/api/speech/synthesize` Endpoints nicht verfuegbar (HTTP 500).

**Embedding-Wechsel:**
Beim Wechsel zwischen Providern mit unterschiedlichen Embedding-Modellen werden bestehende RAG-Vektoren ungueltig. Im Studio muessen alle Wissensbereiche geloescht und Dokumente neu hochgeladen werden. **Empfehlung:** Provider vor dem Befuellen der Wissensbasis festlegen.

### Empfehlung

| Szenario | Empfohlener Provider |
|----------|---------------------|
| Volle Funktionalitaet | `openai` |
| Kosten senken, B-API verfuegbar | `b-api-openai` + `OPENAI_API_KEY` fuer Moderation |
| Datenschutz-Anforderungen (EU-Hosting) | `b-api-academiccloud` (mit Einschraenkungen) |

---

## 6. Google Colab Notebook

Fuer einen schnellen Einstieg ohne lokale Installation steht ein Google Colab Notebook bereit:

**[BadBoerdi im Google Colab oeffnen](https://drive.google.com/file/d/1BFZpEEogOYJa50k7NRxuUVA12Hb89x96/view?usp=sharing)**

Das Notebook startet Backend, Studio und Chat-Widget komplett in der Cloud. Nur ein OpenAI-API-Key (oder B-API-Key) wird benoetigt.
