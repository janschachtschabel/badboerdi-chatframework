# BadBoerdi Backend (FastAPI)

Python-Service mit Chat-API, Pattern-Engine, mehrstufiger Safety-Pipeline, RAG, MCP-Integration
und Auslieferung des `<boerdi-chat>`-Widgets. Konfiguration ausschließlich über Dateien unter
`chatbots/wlo/v1/` — kein Code-Deploy für inhaltliche Änderungen nötig.

## 1. Setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # OPENAI_API_KEY, OPENAI_MODEL, MCP-URL, …
python run.py              # uvicorn auf :8000
```

Health-Check: `GET http://localhost:8000/api/health`

### Env-Variablen

| Variable | Default | Wirkung |
|----------|---------|---------|
| `LLM_PROVIDER` | `openai` | LLM-Backend (Standard ist `openai` — leer/unset verhält sich identisch). Werte: `openai` (nativ), `b-api-openai` (B-API → OpenAI), `b-api-academiccloud` (B-API → AcademicCloud / GWDG). Siehe Abschnitt **LLM-Provider & Einschränkungen** unten. |
| `OPENAI_API_KEY` | _Pflicht bei `openai`_ | OpenAI-Key für Chat-Modell, Moderation, Legal-Classifier, Whisper und TTS. |
| `B_API_KEY` | _Pflicht bei `b-api-*`_ | API-Key für `b-api.staging.openeduhub.net`. Wird als Header `X-API-KEY` gesendet. |
| `B_API_BASE_URL` | `https://b-api.staging.openeduhub.net/api/v1/llm` | Basis-URL der B-API. `/openai` bzw. `/academiccloud` werden je nach Provider angehängt. |
| `LLM_CHAT_MODEL` | provider-spezifisch | Override für das Chat-Modell. Defaults: `gpt-4.1-mini` (openai, b-api-openai), `Qwen/Qwen3.5-122B-A10B-GPTQ-Int4` (b-api-academiccloud). |
| `LLM_EMBED_MODEL` | provider-spezifisch | Override für das Embedding-Modell. Defaults: `text-embedding-3-small` (openai, b-api-openai), `e5-mistral-7b-instruct` (b-api-academiccloud). |
| `OPENAI_MODEL` | `gpt-4.1-mini` | _Legacy_, weiterhin gültig wenn `LLM_PROVIDER=openai` und `LLM_CHAT_MODEL` nicht gesetzt ist. |
| `MCP_SERVER_URL` | `https://wlo-mcp-server.vercel.app/mcp` | Default-Ziel des WLO-MCP-Clients. Einzelne Server können zusätzlich in `05-knowledge/mcp-servers.yaml` definiert werden. |
| `STUDIO_API_KEY` | _leer_ | Schützt `/api/config/*`, `/api/rag/*`, `/api/safety/*` und die geschützten `/api/sessions/*`-Routen. Leer = API offen (Dev-Default). Siehe Abschnitt 9. |
| `DATABASE_PATH` | `badboerdi.db` | Pfad zur SQLite-Datenbank (Sessions, Messages, Safety-Logs). |

## 2. Endpunkt-Inventar

Schutzstatus: **offen** = immer erreichbar · **Studio** = braucht Header `X-Studio-Key` (bzw.
`?key=`), sobald `STUDIO_API_KEY` im Backend gesetzt ist.

### Health & Root

| Methode | Pfad | Schutz | Beschreibung |
|---------|------|--------|--------------|
| `GET` | `/api/health` | offen | Health-Check mit aktivem OpenAI-Modell. |

### Chat (`/api/chat`)

| Methode | Pfad | Schutz | Beschreibung |
|---------|------|--------|--------------|
| `POST` | `/api/chat` | offen | Hauptendpoint. Erwartet `{session_id, message, environment, action?}`. Rückgabe: `content`, `cards`, `quick_replies`, `pagination`, `debug` (Triple-Schema-Trace). |
| `GET`  | `/api/chat/stream` | offen | SSE-Stream-Variante des Chat-Endpoints (experimentell). |

### Sessions (`/api/sessions`)

| Methode | Pfad | Schutz | Beschreibung |
|---------|------|--------|--------------|
| `GET`  | `/api/sessions/` | Studio | Liste der letzten 100 Sessions (Studio-Inspector). |
| `GET`  | `/api/sessions/{id}` | Studio | Session-State (Persona, State, Entities, Signal-History, Turn-Count). |
| `GET`  | `/api/sessions/{id}/messages?limit=50` | offen | History für Cross-Page-Continuity — wird vom Widget auf jeder Seite aufgerufen. |
| `GET`  | `/api/sessions/{id}/memory` | Studio | Memory-Einträge (optional gefiltert per `memory_type`). |
| `POST` | `/api/sessions/{id}/memory` | Studio | Memory-Eintrag speichern (`key`, `value`, `memory_type`). |

### Speech (`/api/speech`)

| Methode | Pfad | Schutz | Beschreibung |
|---------|------|--------|--------------|
| `POST` | `/api/speech/transcribe` | offen | Whisper STT — Audio-Upload → Text. |
| `POST` | `/api/speech/synthesize` | offen | OpenAI TTS — Text → Audio. |

### Config (`/api/config`) — Studio-Editoren

Alle Routen unter `/api/config/*` sind **Studio**-geschützt.

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `GET`    | `/api/config/files` | Liste aller Dateien im `chatbots/wlo/v1/`-Tree. |
| `GET`    | `/api/config/file?path=…` | Einzelne Datei lesen. |
| `PUT`    | `/api/config/file` | Einzelne Datei schreiben. |
| `DELETE` | `/api/config/file?path=…` | Einzelne Datei löschen. |
| `GET`    | `/api/config/export` | JSON-Export aller Konfigurationsdateien (`{path: {name, type, content}}`). |
| `GET`    | `/api/config/elements` | Aggregierter Layer-4-Elementenbaum (Personas/Intents/Entities/Slots/Signals/States/Contexts). |
| `GET`    | `/api/config/mcp-servers` | MCP-Server-Konfiguration lesen. |
| `PUT`    | `/api/config/mcp-servers` | MCP-Server-Konfiguration schreiben. |
| `POST`   | `/api/config/mcp-servers/discover` | Tools eines MCP-Servers automatisch entdecken. |
| `POST`   | `/api/config/import` | Teil-Import (JSON). |
| `GET`    | `/api/config/backup` | Komplettes `chatbots/wlo/v1`-Tree als ZIP. |
| `POST`   | `/api/config/restore[?wipe=true]` | ZIP einspielen (merge oder wipe+restore). |

### RAG (`/api/rag`) — Wissensbereiche

Alle Routen unter `/api/rag/*` sind **Studio**-geschützt.

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `POST`   | `/api/rag/ingest/file` | Datei (PDF/Markdown/…) in einen Wissensbereich hochladen. |
| `POST`   | `/api/rag/ingest/url` | URL crawlen und ingesten. |
| `POST`   | `/api/rag/ingest/text` | Freitext ingesten. |
| `POST`   | `/api/rag/query` | Semantische Suche über einen Bereich. |
| `GET`    | `/api/rag/areas` | Liste aller Wissensbereiche. |
| `GET`    | `/api/rag/area/{area}` | Details/Dokumente eines Bereichs. |
| `DELETE` | `/api/rag/area/{area}` | Bereich inkl. Embeddings löschen. |

### Safety (`/api/safety`)

Alle Routen unter `/api/safety/*` sind **Studio**-geschützt.

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `GET` | `/api/safety/logs` | Geloggte Risk-Events (siehe `safety-config.yaml → logging`). |
| `GET` | `/api/safety/stats` | Aggregierte Safety-Statistiken für das Studio-Dashboard. |

### Widget (`/widget`)

| Methode | Pfad | Schutz | Beschreibung |
|---------|------|--------|--------------|
| `GET` | `/widget/` | offen | Demo-HTML für Embedder. |
| `GET` | `/widget/boerdi-widget.js` | offen | Auslieferung des Web-Component-Bundles. |
| `GET` | `/widget/{asset_name}` | offen | Weitere Assets aus `frontend/dist/widget/browser/` (Chunks, Fonts, …). |

## 3. Konfigurationslayout — die 5 Schichten

Alle Schichten liegen unter `backend/chatbots/wlo/v1/` und werden über
`app/services/config_loader.py` geladen.

```
chatbots/wlo/v1/
├── 01-base/                      ← Schicht 1: Identität & Schutz (immer im Prompt)
│   ├── base-persona.md           ←   Wer ist BOERDi?
│   ├── guardrails.md             ←   Harte Grenzen (kommt als LETZTER Block)
│   ├── safety-config.yaml        ←   Presets off/basic/standard/strict/paranoid + Rate-Limits
│   └── device-config.yaml        ←   Geräte-/Persona-Heuristiken
├── 02-domain/                    ← Schicht 2: Domain & Regeln (immer im Prompt)
│   ├── domain-rules.md           ←   Dauerregeln
│   ├── policy.yaml               ←   Strukturelle Erlaubnisse/Verbote
│   └── wlo-plattform-wissen.md   ←   Plattform-Wissen WLO
├── 03-patterns/                  ← Schicht 3: 20 Konversations-Patterns
│   ├── pat-01-direkt-antwort.md
│   ├── pat-02-gefuehrte-klaerung.md
│   └── … pat-20-orientierungs-guide.md
├── 04-personas/                  ← Schicht 4: Dimensionen
├── 04-intents/
├── 04-entities/
├── 04-slots/
├── 04-signals/
├── 04-states/
├── 04-contexts/
└── 05-knowledge/                 ← Schicht 5: Wissen
    ├── rag-config.yaml           ←   Wissensbereiche (query_knowledge-Tools)
    └── mcp-servers.yaml          ←   Externe MCP-Server
```

Welche Datei wann in den Prompt wandert, ist im Quelltext nachvollziehbar:
`app/services/llm_service.py → generate_response()`, Variable `system_parts`.

## 4. Safety-Pipeline (Triple-Schema v2)

Die Safety läuft **vor** dem LLM-Call und kann Tools sperren oder Patterns erzwingen
(z.B. `PAT-CRISIS`).

```
Regex-Gate (immer)
   │
   ▼
OpenAI-Moderation  (mode: smart/always — in Presets festgelegt)
   │
   ▼
Legal-Classifier (gpt-4.1-mini)  (smart: nur bei Trigger-Treffer / always: jeder Turn)
   │
   ▼
Confidence-Adjustment aus Tool-Outcomes
```

Konfiguration: `chatbots/wlo/v1/01-base/safety-config.yaml`

* `security_level`: `off | basic | standard | strict | paranoid`
* `presets.*`: definieren `moderation`, `legal_classifier`, `prompt_injection`,
  optional `threshold_multiplier` und `double_check`
* `escalation.legal_thresholds.flag` / `.high`: Schwellwerte für den Legal-Classifier
* `escalation.thresholds.*`: Schwellwerte je Moderation-Kategorie
* `crisis_blocked_tools`: Tools, die bei Crisis-Pattern blockiert werden

## 5. Rate Limits & Concurrency

`safety-config.yaml → rate_limits` — Sliding-Window pro Session und pro IP, plus
optionale IP-Whitelist. Defaults für 50 parallele Nutzer:

```yaml
per_session:
  enabled: true
  requests_per_minute: 30
  requests_per_hour: 600
per_ip:
  enabled: true
  requests_per_minute: 300
  requests_per_hour: 3000
```

Pro Session-ID gibt es einen `asyncio.Lock` (`app/routers/chat.py`), sodass parallele Requests
einer Session strikt sequentiell verarbeitet werden — verschiedene Sessions laufen parallel.

## 6. Widget-Auslieferung

`app/routers/widget.py` liest das Widget-Bundle in dieser Reihenfolge:

1. **`frontend/dist/widget/browser/main.js`** — Standard im Mono-Repo (kein Kopieren nötig).
2. **`backend/widget_dist/main.js`** — Fallback für isolierte Backend-Deploys ohne Geschwister-`frontend/`-Verzeichnis. Wird vom Sync-Skript befüllt.

Build-Optionen aus dem Repo-Root:

```bash
# Variante A — Mono-Repo / lokal (Default, kein Kopieren)
./scripts/build-widget.sh        # Linux/macOS
.\scripts\build-widget.ps1       # Windows

# Variante B — Backend isoliert deployen (mit Kopie nach backend/widget_dist/)
./scripts/sync-widget-to-backend.sh
.\scripts\sync-widget-to-backend.ps1
```

Beide Skripte rufen intern `npm install` (falls nötig) und `npm run build:widget` im `frontend/`-Verzeichnis auf und prüfen anschließend, dass `main.js` existiert. Falls das Bundle in beiden Verzeichnissen fehlt, antwortet `/widget/boerdi-widget.js` mit `503` und einer expliziten Anleitung.

## 7. MCP & RAG

* **MCP**: WLO-Suche via `app/services/mcp_client.py` (Tools `search_wlo_collections`,
  `search_wlo_content`, `get_collection_contents`, `lookup_wlo_vocabulary`, …).
  Server-Konfiguration in `chatbots/wlo/v1/05-knowledge/mcp-servers.yaml`.
* **RAG**: Wissensbereiche werden im Studio hochgeladen und in
  `chatbots/wlo/v1/05-knowledge/rag-config.yaml` registriert. Das LLM bekommt sie als
  `query_knowledge(area=…)`-Tool.

## 8. Datenbank

SQLite (`badboerdi.db`) für Sessions, Messages, Safety-Logs. Init in
`app/services/database.py`. Für Produktion gegen PostgreSQL austauschbar.

## 9. Authentifizierung & Backup

Schreibende und konfigurations-nahe Endpunkte können per Umgebungsvariable geschützt werden:

```bash
export STUDIO_API_KEY=geheim123          # Linux/macOS
$env:STUDIO_API_KEY="geheim123"          # PowerShell
```

Ist `STUDIO_API_KEY` leer oder ungesetzt, bleibt die API **offen** (Dev-Default). Ist sie gesetzt,
verlangen folgende Routen den Header `X-Studio-Key: <wert>` (oder alternativ `?key=<wert>`):

* `GET/PUT /api/config/*`
* `GET/PUT /api/rag/*`
* `GET/PUT /api/safety/*`
* alle `/api/sessions/*`-Routen **außer** `GET /{id}/messages` — also `GET /sessions/`, `GET /{id}`, `GET/POST /{id}/memory`

**Bewusst offen** bleiben auch mit gesetztem Key:

* `POST /api/chat` — sonst könnte das Widget nicht chatten
* `/api/speech/*` — Whisper/TTS im Widget
* `/widget/*` — Bundle- und Demo-Auslieferung
* `GET /api/sessions/{id}/messages` — Cross-Page-History des Widgets

### Backup & Restore der Konfiguration

```bash
# Komplettes chatbots/wlo/v1-Tree als ZIP ziehen
curl -H "X-Studio-Key: $STUDIO_API_KEY" \
     -o wlo-v1-backup.zip \
     http://localhost:8000/api/config/backup

# Restore (merge über bestehende Dateien)
curl -H "X-Studio-Key: $STUDIO_API_KEY" \
     -F "file=@wlo-v1-backup.zip" \
     http://localhost:8000/api/config/restore

# Restore mit vorherigem Leeren (wipe) des Trees
curl -H "X-Studio-Key: $STUDIO_API_KEY" \
     -F "file=@wlo-v1-backup.zip" \
     "http://localhost:8000/api/config/restore?wipe=true"
```

## 10. LLM-Provider & Einschränkungen

Das Backend spricht drei OpenAI-kompatible Provider, umschaltbar per `LLM_PROVIDER`. **Default ist `openai`** — wenn die Variable leer oder nicht gesetzt ist, läuft alles wie bisher mit OpenAI nativ.

| Provider | Chat-Default | Embed-Default | Auth |
|----------|--------------|---------------|------|
| `openai` _(Standard)_ | `gpt-4.1-mini` | `text-embedding-3-small` | `OPENAI_API_KEY` |
| `b-api-openai` | `gpt-4.1-mini` | `text-embedding-3-small` | `B_API_KEY` (Header `X-API-KEY`) |
| `b-api-academiccloud` | `Qwen/Qwen3.5-122B-A10B-GPTQ-Int4` | `e5-mistral-7b-instruct` | `B_API_KEY` |

Modelle per `LLM_CHAT_MODEL` / `LLM_EMBED_MODEL` überschreibbar. Implementiert in `app/services/llm_provider.py` (eine zentrale `get_client()`-Factory, keine Code-Änderungen in den Aufrufstellen außer dem Modell-Lookup).

### Beispiel-Setups

```bash
# Default (= ohne LLM_PROVIDER):
export OPENAI_API_KEY=sk-...

# B-API → OpenAI (gleiche Modelle, aber über die WLO-Proxy-Infrastruktur)
export LLM_PROVIDER=b-api-openai
export B_API_KEY=bb6cdf84-0a9d-47f3-b673-c1b4f25b9bdc

# B-API → AcademicCloud (Open-Source-Modelle, GWDG-Hosting)
export LLM_PROVIDER=b-api-academiccloud
export B_API_KEY=bb6cdf84-0a9d-47f3-b673-c1b4f25b9bdc
# optional anderes AcademicCloud-Modell:
export LLM_CHAT_MODEL=meta-llama-3.1-8b-instruct
```

### Was bei B-API NICHT mehr funktioniert

Die B-API bietet nur `chat/completions` und `embeddings` an. Folgende Funktionen sind daran gebunden, dass `LLM_PROVIDER=openai` UND `OPENAI_API_KEY` vorhanden sind:

| Feature | Code-Anker | Verhalten ohne native OpenAI |
|---------|-----------|------------------------------|
| **Whisper STT** (`POST /api/speech/transcribe`) | `routers/speech.py` | Endpoint braucht `OPENAI_API_KEY`. Bei den B-API-Providern ist der Mikrofon-Button im Widget tot, sofern kein zusätzlicher OpenAI-Key vorliegt. |
| **TTS** (`POST /api/speech/synthesize`) | `routers/speech.py` | Wie oben — Vorlese-Funktion deaktiviert. |
| **Stage-2 Moderation** (`omni-moderation-latest`) | `services/safety_service.py::_openai_moderate` | Wird per `is_openai_native()`-Gate übersprungen. Stage 1 (Regex) und Stage 3 (Legal-Classifier) bleiben aktiv → Safety-Pipeline wirkt weiter, nur etwas weniger fein. `safety.categories` im Debug bleibt leer. |
| **RAG-Vektor-Kompatibilität** | `services/rag_service.py` | `e5-mistral-7b-instruct` (1024 dim) ≠ `text-embedding-3-small` (1536 dim). **Bestehende Embeddings sind nach einem Wechsel zu `b-api-academiccloud` unbrauchbar — alle Dokumente neu indexieren** (Studio → RAG-Panel → Reindex, oder per API). |
| **Tool-/Function-Calling** für `classify_input` | `services/llm_service.py` | Bei `b-api-openai` voll funktional. Bei `b-api-academiccloud` modellabhängig: Qwen3.5-122B & Llama-3.1-Instruct beherrschen es, kleinere AcademicCloud-Modelle (z.B. `mistral-7b`) **nicht** → Klassifikation fällt auf Defaults zurück, Pattern-Wahl wird ungenauer. |
| **JSON-Mode** (`response_format={"type":"json_object"}`) für den Legal-Classifier | `services/safety_service.py::_llm_legal_classify` | OpenAI/B-API-OpenAI: garantiert. AcademicCloud: nicht garantiert — bei Parse-Fehler greift der bestehende Fallback `risk=0`, Stage 3 ist dann faktisch wirkungslos für die betroffene Anfrage. |

**Empfehlung**

* **Volle Feature-Parität:** `openai` (Standard) oder `b-api-openai`.
* **Datenschutz / EU-Hosting / On-Prem:** `b-api-academiccloud`. Dabei beachten:
  1. Vor dem Umschalten RAG-Index neu aufbauen (oder leeren).
  2. Sprach-Features im Widget per Property `voice="false"` deaktivieren oder zusätzlich einen `OPENAI_API_KEY` setzen, damit Whisper/TTS als Hybrid weiter funktionieren.
  3. Ein tool-fähiges Modell wählen (Qwen3.5-122B Default, alternativ `meta-llama-3.1-8b-instruct`).

## 11. Debug-Output

Jede `/api/chat`-Antwort enthält ein `debug`-Objekt mit:

* `persona`, `intent`, `state`, `pattern`, `signals`, `entities`
* `phase1_eliminated`, `phase2_scores`, `phase3_modulations` (Pattern-Scoring)
* `outcomes` (Tool-Outcomes mit Status/Latenz)
* `safety` (Stages, Risk-Level, Categories, Legal-Flags, Escalated)
* `policy` (Allowed/Blocked-Tools/Disclaimers)
* `context`, `trace` (Phase-Trace mit Dauer)

Das Frontend rendert dieses Objekt im Debug-Panel; das Studio nutzt es für Sessions-Inspektion.
