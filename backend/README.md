# BadBoerdi Backend (FastAPI)

Python-Service mit Chat-API, LLM-gesteuertem Pattern-Routing, mehrstufiger Safety-Pipeline, RAG, MCP-Integration
und Auslieferung des `<boerdi-chat>`-Widgets. Konfiguration ausschliesslich ueber Dateien unter
`chatbots/wlo/v1/` — kein Code-Deploy fuer inhaltliche Aenderungen noetig.

> **Google Colab Notebook:** [BadBoerdi im Browser ausprobieren](https://drive.google.com/file/d/1BFZpEEogOYJa50k7NRxuUVA12Hb89x96/view?usp=sharing) — komplettes Setup ohne lokale Installation.

## 1. Setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # OPENAI_API_KEY, LLM_PROVIDER, MCP-URL, …

# Einmalig nach Clone: RAG-Reranker exportieren (~1 Min, 135 MB Modelldatei)
pip install -r requirements-setup.txt \
  --extra-index-url https://download.pytorch.org/whl/cpu
python -m scripts.setup

python run.py              # uvicorn auf :8000
```

Health-Check: `GET http://localhost:8000/health` → `{"status":"ok"}` (auch HEAD)

### RAG-Reranker (ONNX int8)

Nach dem Embedding-Retrieval ordnet ein Cross-Encoder (`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`,
int8-quantisiert, ~135 MB) die Top-25 Treffer um. LLM-as-Judge-Eval zeigte 8/10 Wins gegenueber
reiner Embedding-Suche; er ist daher immer an.

**Deployment-Varianten:**

- **Docker (`docker compose up --build` oder `docker build`)** — das `reranker-builder`-Stage
  im `backend/Dockerfile` fuehrt den Export automatisch beim Image-Bau aus und legt das
  Artefakt ab; das finale Runtime-Image traegt nur die ~135 MB ONNX-Dateien, **kein torch**.
  **Null manuelles Eingreifen noetig**, auch in CI/CD.
- **Lokale Dev-Installation** — einmalig `pip install -r requirements-setup.txt` +
  `python -m scripts.setup` wie oben im Setup-Block. Idempotent; ueberspringt den
  Export, wenn die Dateien bereits da sind.

**Weitere Details:**

- Export-Abhaengigkeiten (`optimum`, `sentence-transformers`, `torch`) liegen in
  `requirements-setup.txt` und sind **nicht** Teil des Production-Runtime. Runtime
  braucht nur `onnxruntime` + `transformers` (bereits in `requirements.txt`).
- Fehlt das Modellverzeichnis beim Start (z.B. wenn man `models/` aus einem Bare-Metal-Deploy
  versehentlich ausschliesst), loggt der Server eine WARNING mit Setup-Befehl und arbeitet
  mit reiner Embedding-Suche weiter — kein harter Fehler.
- Warmup-Last (~1–8 s Modell-Load) laeuft im `lifespan`-Handler parallel zu Config-
  und LLM-Warmup, blockiert also keinen Request.
- Neu-Export nach Modellwechsel:
  ```bash
  python -m scripts.export_reranker_onnx --force
  # oder mit anderem Modell:
  python -m scripts.export_reranker_onnx --model BAAI/bge-reranker-v2-m3
  ```
  Der Pfad in `rag_service.py` (`_RERANK_MODEL_SLUG`) muesste dann angepasst werden.
- Docker-Build nutzt einen BuildKit-Cache-Mount (`HF_HOME=/hf-cache`), damit ein
  Rebuild ohne Modellwechsel das HuggingFace-Modell nicht erneut herunterlaedt.
  `DOCKER_BUILDKIT=1` ist fuer moderne Docker-Versionen Default.

### Env-Variablen

| Variable | Default | Wirkung |
|----------|---------|---------|
| `LLM_PROVIDER` | `openai` | LLM-Backend. Werte: `openai` (nativ), `b-api-openai` (B-API → OpenAI), `b-api-academiccloud` (B-API → AcademicCloud / GWDG). Siehe Abschnitt 10. |
| `OPENAI_API_KEY` | _Pflicht bei `openai`_ | OpenAI-Key fuer Chat-Modell, Moderation, Legal-Classifier, Whisper und TTS. |
| `OPENAI_BASE_URL` | _leer_ (= `https://api.openai.com/v1`) | Optional: OpenAI-kompatibler Endpoint (Azure OpenAI, LiteLLM-Proxy, LocalAI, Ollama-Shim, …). Wenn gesetzt, müssen an dem Endpoint die gewünschten Modelle/Features (Embeddings, ggf. STT/TTS, ggf. Moderation) verfügbar sein. |
| `B_API_KEY` | _Pflicht bei `b-api-*`_ | API-Key fuer die B-API. Wird als Header `X-API-KEY` gesendet. |
| `B_API_BASE_URL` | `https://b-api.prod.openeduhub.net/api/v1/llm` | Basis-URL der B-API. `/openai` bzw. `/academiccloud` werden je nach Provider angehaengt. Default = PROD; Staging-Variante: `https://b-api.staging.openeduhub.net/api/v1/llm`. |
| `LLM_CHAT_MODEL` | provider-spezifisch | Override fuer das Chat-Modell. Defaults: `gpt-5.4-mini` (openai), `gpt-4.1-mini` (b-api-openai), `Qwen/Qwen3.5-122B-A10B-GPTQ-Int4` (b-api-academiccloud). |
| `LLM_EMBED_MODEL` | provider-spezifisch | Override fuer das Embedding-Modell. Defaults: `text-embedding-3-small` (openai, b-api-openai), `e5-mistral-7b-instruct` (b-api-academiccloud). |
| `OPENAI_MODEL` | `gpt-4.1-mini` | _Legacy_, weiterhin gueltig wenn `LLM_PROVIDER=openai` und `LLM_CHAT_MODEL` nicht gesetzt ist. |
| `MCP_SERVER_URL` | `https://wlo-mcp-server.vercel.app/mcp` | Default-Ziel des WLO-MCP-Clients. Weitere Server koennen in `05-knowledge/mcp-servers.yaml` definiert werden. |
| `TEXT_EXTRACTION_URL` | `https://text-extraction.prod.openeduhub.net` | **Base-URL** des OEH-Volltext-Service (Material-Remix — URL-Inhalte als Quelle einlesen). Der `/from-url`-Endpoint wird intern angehängt; Trailing-Slash wird ignoriert. Staging: `https://text-extraction.staging.openeduhub.net`. |
| `STUDIO_API_KEY` | _leer_ | Schuetzt `/api/config/*`, `/api/rag/*`, `/api/safety/*`, `/api/quality/*`, `/api/debug/*` und die geschuetzten `/api/sessions/*`-Routen. Leer = API offen (Dev-Default, Startup-Warnung). Siehe Abschnitt 9. |
| `CORS_ORIGINS` | `*` | Komma-separierte Liste erlaubter Origins fuer CORS. Bei `*` (Default) werden keine Credentials erlaubt. Fuer Produktion spezifische Origins setzen (z.B. `https://wirlernenonline.de,https://studio.meinedomain.de`), dann werden auch Credentials unterstuetzt. |
| `DATABASE_PATH` | `badboerdi.db` | Pfad zur SQLite-Datenbank (Sessions, Messages, Safety-Logs, Quality-Logs, RAG). |
| `STT_MODEL` | `gpt-4o-mini-transcribe` | Speech-to-Text-Modell. Fallbacks: `gpt-4o-transcribe`, `whisper-1`. Nur native OpenAI-Endpoints; B-API forwardet keinen Audio-Endpoint. |
| `TTS_MODEL` | `tts-1` | Text-to-Speech-Modell. `tts-1-hd` für höhere Qualität (2× Kosten). |
| `EVAL_CHAT_URL` | `http://localhost:8000/api/chat` | Ziel-Endpoint für simulierte Chat-Calls im Eval. Self-Loopback; nur ändern, wenn Eval gegen remote Backend läuft. |
| `EVAL_SIMULATOR_MODEL` | `gpt-4o-mini` | Modell für User-Simulator + Szenario-Generator. |
| `EVAL_JUDGE_MODEL` | `gpt-4o-mini` | Modell für den LLM-as-Judge-Scorer. |
| `REPO_BASE_URL` | _Code-Default_ | edu-sharing-Repo-Basis für `wlo_url`/`preview_url`. MUSS zum Repo der `MCP_SERVER_URL` passen. Staging: `https://repository.staging.openeduhub.net`. |
| `LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR`. |
| `TRUST_FORWARDED_FOR` | _aus_ | `1` = per-IP-Rate-Limit liest `X-Forwarded-For`. NUR hinter eigenem Reverse-Proxy setzen (sonst spoofbar); ohne das Flag zählt hinter einem Proxy alles als eine IP. |
| `LLM_MAX_CONCURRENCY` | `20` | Bulkhead: max. gleichzeitige B-API-/OpenAI-Requests (geteilter Pool Chat+Moderation+Embedding). Glättet p95 unter Burst statt 429-Lawinen. **Provider-/modellabhängig** (B-API-Staging/-Prod/native OpenAI haben je eigene Limits) — vor Prod/Lasttest anpassen: zu hoch → 429/504 beim Provider, zu niedrig → Queue-Latenz. Sicheren Wert via `scripts/probe_b_api_ratelimit.py`; für Lasttests ≥ Test-Concurrency setzen. |
| `LLM_READ_TIMEOUT` | `75` | Sekunden pro LLM-Call, bevor der Client abbricht und der SDK-Retry neu ansetzt. Reagiert auf hängende Backend-Knoten schneller als das Staging-Gateway (504 erst nach ~120 s). |
| `MCP_MAX_CONNECTIONS` | `50` | HTTP-Pool zum WLO-MCP-Suchdienst. |
| `RERANK_INTRA_OP_THREADS` | `1` | Kerne pro ONNX-Reranker-Inferenz. `1` verhindert, dass ein einzelner Rerank alle Kerne greift (Oversubscription unter Last); Parallelität kommt über mehrere Requests. |
| `RERANK_MAX_CONCURRENCY` | _phys. Kerne_ | Max. gleichzeitige Rerank-Inferenzen (dedizierter Threadpool, geteilt von RAG-Rerank + Card-CE-Gate). Deckelt den CPU-Peak deterministisch. |
| `RAG_RERANKER_ENABLED` | `true` | Cross-Encoder-Reranker an/aus. Auf ≤ 2-GB-vServern `false` (Embedding-only). Siehe „Memory-Sizing“ in docs/04. |
| `EMBED_DIM` | _Modell-Default_ | Embedding-Dimension. Nur für exotische Embed-Modelle; Änderung erfordert Re-Embedding. |
| `SPEECH_FORCE_ENABLE` | _aus_ | `1` erzwingt Speech-Features trotz Auto-Deaktivierung (Debug). |
| `BOERDI_MAX_INGEST_MB` | `25` | Max. RAG-Upload-Größe (MB). `0` = unbegrenzt. |
| **Karten-Auswahl** | | (volle Doku + Defaults: `.env.example`) |
| `CARD_CE_TOP_N` | `3` | Max. Karten je Box (Sammlungen/Themenseiten/Einzelinhalte). |
| `CARD_CE_GATE_COLLECTION` | `0.0` | CE-Score-Schwelle Sammlungen + Themenseiten (höher = strenger). |
| `CARD_CE_GATE_CONTENT` | `-1.5` | CE-Score-Schwelle Einzelinhalte. |
| `CHAT_DISABLE_SELECT_TOP_CARDS` | _aus_ | `1` überspringt den LLM-Kuratierungs-Schritt der Karten. |
| `CHAT_INLINE_QUICK_REPLIES` | _aus_ | `1` = Antwort + Quick-Replies in einem kombinierten Tool-Call (experimentell). |
| `CARD_PIPELINE_V2` | _aus_ | `1` aktiviert die neue modulare Karten-Pipeline (Opt-in). |

---

## 2. Endpunkt-Inventar

Schutzstatus: **offen** = immer erreichbar · **Studio** = braucht Header `X-Studio-Key` (bzw.
`?key=`), sobald `STUDIO_API_KEY` im Backend gesetzt ist.

### Health & Debug

| Methode | Pfad | Schutz | Beschreibung |
|---------|------|--------|--------------|
| `GET` / `HEAD` | `/health` | offen | Liveness-Check (immer `{"status":"ok"}`). Zielfür Docker-`HEALTHCHECK` und externe Load-Balancer. |
| `GET` | `/api/debug/mcp-test` | Studio | MCP-Verbindungstest (nur mit API-Key). |

### Chat (`/api/chat`)

| Methode | Pfad | Schutz | Beschreibung |
|---------|------|--------|--------------|
| `POST` | `/api/chat` | offen | Hauptendpoint. Erwartet `{session_id, message, environment, action?}`. Rueckgabe: `content`, `cards`, `quick_replies`, `pagination`, `debug`. |
| `GET`  | `/api/chat/stream` | offen | SSE-Stream-Variante des Chat-Endpoints (experimentell). |

### Sessions (`/api/sessions`)

| Methode | Pfad | Schutz | Beschreibung |
|---------|------|--------|--------------|
| `GET`  | `/api/sessions/` | Studio | Liste der letzten 100 Sessions (Studio-Inspector). |
| `GET`  | `/api/sessions/{id}` | Studio | Session-State (Persona, State, Entities, Signal-History, Turn-Count). |
| `GET`  | `/api/sessions/{id}/messages?limit=50` | offen | History fuer Cross-Page-Continuity — wird vom Widget auf jeder Seite aufgerufen. |
| `GET`  | `/api/sessions/{id}/memory` | Studio | Memory-Eintraege (optional gefiltert per `memory_type`). |
| `POST` | `/api/sessions/{id}/memory` | Studio | Memory-Eintrag speichern (`key`, `value`, `memory_type`). |

### Speech (`/api/speech`)

| Methode | Pfad | Schutz | Beschreibung |
|---------|------|--------|--------------|
| `POST` | `/api/speech/transcribe` | offen | OpenAI STT (`gpt-4o-mini-transcribe`, Fallback `gpt-4o-transcribe` → `whisper-1`) — Audio-Upload → Text. |
| `POST` | `/api/speech/synthesize` | offen | OpenAI TTS — Text → Audio. |

### Config (`/api/config`) — Studio-Editoren

Alle Routen unter `/api/config/*` sind **Studio**-geschuetzt.

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `GET`    | `/api/config/files` | Liste aller Dateien im `chatbots/wlo/v1/`-Tree. |
| `GET`    | `/api/config/file?path=…` | Einzelne Datei lesen. |
| `PUT`    | `/api/config/file` | Einzelne Datei schreiben. |
| `DELETE` | `/api/config/file?path=…` | Einzelne Datei loeschen. |
| `GET`    | `/api/config/export` | JSON-Export aller Konfigurationsdateien. |
| `GET`    | `/api/config/elements` | Aggregierter Elementenbaum (Personas/Intents/Entities/Signals/States/Contexts). |
| `GET`    | `/api/config/mcp-servers` | MCP-Server-Konfiguration lesen. |
| `PUT`    | `/api/config/mcp-servers` | MCP-Server-Konfiguration schreiben. |
| `POST`   | `/api/config/mcp-servers/discover` | Tools eines MCP-Servers automatisch entdecken (SSRF-geschuetzt). |
| `POST`   | `/api/config/import` | Batch-Import (JSON, pfad-validiert). |
| `GET`    | `/api/config/canvas/material-types` | Typed JSON der Material-Typen für die KI-Generierung (M10) — GUI-Editor im Studio-Tab „Material-Formate“. |
| `PUT`    | `/api/config/canvas/material-types` | Liste schreiben — Multi-line-`structure` wird als YAML-Block-Scalar serialisiert. |
| `GET`    | `/api/config/privacy` | Logging-Toggles (messages/memory/quality). |
| `PUT`    | `/api/config/privacy` | Logging-Toggles updaten. `safety` ist read-only true. |
| `GET`    | `/api/config/backup` | Komplettes `chatbots/wlo/v1`-Tree (+ optional DB) als ZIP. |
| `POST`   | `/api/config/restore[?wipe=true&include_db=true]` | ZIP einspielen (merge oder wipe+restore). |
| `POST`   | `/api/config/snapshots[?label=…&include_db=true]` | Server-seitigen Snapshot anlegen (`backend/snapshots/`). |
| `GET`    | `/api/config/snapshots` | Alle User-Snapshots auflisten. |
| `POST`   | `/api/config/snapshots/{id}/restore` | User-Snapshot zurückspielen. |
| `DELETE` | `/api/config/snapshots/{id}` | User-Snapshot löschen. |
| `GET`    | `/api/config/factory` | Metadata des Werkseinstellungs-Snapshots. |
| `POST`   | `/api/config/factory/save[?from_snapshot=…]` | Aktuellen Live-Stand (oder einen User-Snapshot) zur Werkseinstellung promoten. |
| `POST`   | `/api/config/factory/restore` | Werkseinstellung aktiv wiederherstellen. |
| `POST`   | `/api/config/factory/upload` | Neue Werkseinstellung als ZIP hochladen (Ops-Workflow). |
| `GET`    | `/api/config/factory/download` | Werkseinstellung herunterladen. |
| `GET`    | `/api/config/guide-mode` | **Öffentlicher** Subset von `01-base/guide-mode.yaml` (`default_enabled`, `allowed_hosts`, `url_fields_priority`, `max_guide_targets_per_turn`). Wird vom Widget beim Init gefetcht — daher KEIN Studio-Auth nötig. |

### RAG (`/api/rag`) — Wissensbereiche

Alle Routen unter `/api/rag/*` sind **Studio**-geschuetzt.

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `POST`   | `/api/rag/ingest/file` | Datei (PDF/Markdown/…) in einen Wissensbereich hochladen. |
| `POST`   | `/api/rag/ingest/url` | URL crawlen und ingesten. |
| `POST`   | `/api/rag/ingest/text` | Freitext ingesten. |
| `POST`   | `/api/rag/query` | Semantische Suche ueber einen Bereich. |
| `POST`   | `/api/rag/embed` | Embeddings fuer Chunks ohne Vektor generieren. |
| `GET`    | `/api/rag/areas` | Liste aller Wissensbereiche. |
| `GET`    | `/api/rag/area/{area}` | Details/Dokumente eines Bereichs. |
| `DELETE` | `/api/rag/area/{area}` | Bereich inkl. Embeddings loeschen. |

### Safety (`/api/safety`)

Alle Routen unter `/api/safety/*` sind **Studio**-geschuetzt.

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `GET` | `/api/safety/logs` | Geloggte Risk-Events (filterbar: `risk_min`, `session_id`). |
| `GET` | `/api/safety/stats` | Aggregierte Safety-Statistiken fuer das Studio-Dashboard. |

### Quality (`/api/quality`) — Qualitaets-Logging

Alle Routen unter `/api/quality/*` sind **Studio**-geschuetzt.
Jeder Chat-Turn wird automatisch protokolliert (konfigurierbar via `01-base/quality-log-config.yaml`).

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `GET` | `/api/quality/logs` | Quality-Logs (filterbar: `session_id`, `pattern_id`, `intent_id`, `limit`). |
| `GET` | `/api/quality/stats` | Aggregierte Metriken: Pattern-Verteilung, Intent-Verteilung, avg. Confidence, Score-Gap, Degradation-Rate, Empty-Entity-Rate, Tight Races. |

### Widget (`/widget`)

| Methode | Pfad | Schutz | Beschreibung |
|---------|------|--------|--------------|
| `GET` | `/widget/` | offen | Demo-HTML mit eingebettetem Chat. |
| `GET` | `/widget/boerdi-widget.js` | offen | Web-Component-Bundle (`<boerdi-chat>`). |
| `GET` | `/widget/{asset_name}` | offen | Weitere Assets (Chunks, Fonts, …). |

### Webseiten-Lotsen-Modus

Optionales Feature, das den User aus dem Widget heraus direkt zur passenden WLO-Webseite
schickt — im **selben Browser-Tab**, statt einen neuen aufzumachen. Aktiv nur, wenn:
- der embeddende Host auf der Allow-Liste in `chatbots/wlo/v1/01-base/guide-mode.yaml` steht **und**
- der User den 🧭-Toggle im Widget-Header eingeschaltet hat (Default: aus, opt-in).

**Komponenten-Übersicht:**

| Komponente | Zweck | Datei |
|------------|-------|-------|
| `guide-mode.yaml` | Allow-Liste, Default-Toggle, max-Targets-pro-Turn, URL-Feld-Priorität | `chatbots/wlo/v1/01-base/guide-mode.yaml` |
| `guide_mode_service.py` | Allow-Listen-Match (Wildcard `*.example.com`), `pick_guide_url(card)` und `annotate_cards_with_guide_url()` | `app/services/` |
| `guide_qr_injector.py` | Deterministisches Mapping User-Frage-Regex + RAG-Area → URL für Quick-Reply | `app/services/` |
| `_attach_guide_qr` / `_attach_guide_urls` (in `chat.py`) | Stellt sicher, dass jede ausgehende `ChatResponse` Cards mit `guide_url` und (bei Bedarf) einen `__guide__|...` Quick-Reply trägt — oder beides aktiv strippt, wenn der Toggle aus ist | `app/routers/chat.py` |
| `GET /api/config/guide-mode` | **Public** Endpoint (kein Studio-Auth), den jedes Widget beim Init fetcht | `app/routers/config.py:public_router` |

**Konfigurations-Datei:**

```yaml
# chatbots/wlo/v1/01-base/guide-mode.yaml
guide_mode:
  default_enabled: false              # Toggle-Default beim ersten Besuch.
                                      # User-Wahl gewinnt (gespeichert in
                                      # localStorage["boerdi.guide_mode"]).
  allowed_hosts:                      # Wildcards `*.example.com` matchen
    - wirlernenonline.de              # ALLE Subdomains. Bare Host muss
    - "*.wirlernenonline.de"          # separat gelistet sein.
    - openeduhub.net
    - "*.openeduhub.net"
    - wissenlebtonline.de
    - "*.wissenlebtonline.de"
    # Dev-Hosts (vor Production entfernen!):
    - localhost
    - 127.0.0.1
    - "*.nip.io"
  url_fields_priority:                # In welchem Card-Feld nach der
    - topic_page_url                  # Ziel-URL gesucht wird. Erstes
    - wlo_url                         # allow-listed Treffer gewinnt.
    - url                             # Fallback: ``card.topic_pages[].url``
    - content_url
    - preview_url
  max_guide_targets_per_turn: 0       # 0 = unbegrenzt. Setzt das Maximum
                                      # an Cards pro Antwort, die einen
                                      # Bring-mich-hin-Button erhalten.
```

**Quick-Reply-Trigger pflegen:** das deterministische Frage→URL-Mapping (für Fälle, in denen
das LLM keinen `__guide__|...`-QR generiert) lebt direkt im Code, weil es selten und
zentralisiert geändert wird:

```python
# app/services/guide_qr_injector.py
_RULES = [
    (r"\b(?:mitmachen|beitragen|inhalte\s+einreichen)\b",
     "Mitmachen-Seite", "https://wirlernenonline.de/mitmachen", 75),
    (r"\bwer\s+steht\s+hinter\b",
     "Über WLO", "https://wirlernenonline.de/ueber-uns", 70),
    # … weitere ~10 Regeln
]
_RAG_AREA_URLS = {
    "WissenLebtOnline": ("WissenLebtOnline-Webseite", "https://wissenlebtonline.de/"),
    "WirLernenOnline":  ("WirLernenOnline-Webseite", "https://wirlernenonline.de/"),
    # …
}
```

Reihenfolge der Trigger pro Antwort: (1) Message-Regex überschreibt LLM-Wahl, (2) LLM-eigene
`__guide__|...`-QRs bleiben erhalten, (3) RAG-Area-Fallback wenn der Bot
`query_knowledge(area=…)` mit einer gemappten Area aufgerufen hat.

---

## 3. Architektur-Überblick (Welle E)

Pro Nachricht läuft eine schlanke Pipeline: **Safety → Klassifikation (LLM) → Pattern-Auswahl (LLM-Hint) → Antwort-Generierung**. Es gibt **keine** Score-/Gate-Engine und **keine** Routing-Rules mehr (in Welle E v4 / Sprint K datenbasiert als redundant entfernt). Der LLM-Klassifikator liefert den primären Pattern-Hint; nur Safety (Schutz-Pattern) oder ein Ausführungs-Abgleich (M09/M10 → Label an die real ausgeführte Aktion) überschreiben ihn.

> Ausführliche Architektur-/Element-Doku: **[../docs/02-architektur.md](../docs/02-architektur.md)** + **[../docs/03-elemente.md](../docs/03-elemente.md)**. Hier nur der Überblick.

### Konfigurations-Schichten (`chatbots/wlo/v1/`)

| Verzeichnis | Inhalt |
|---|---|
| `01-base/` | Identität, Guardrails, Safety-/Quality-/Privacy-Config, Geräte-Limits, Display-Rules, Web-Tour, Guide-Mode, Card-Pipeline, Widget-Modi |
| `02-domain/` | WLO-Plattform-Wissen (Struktur, Angebote, Zielgruppen) |
| `03-patterns/` | **16 Konversations-Patterns** (`M01`–`M16`) |
| `04-personas/` | **6 Personas** (s.u.) |
| `04-intents/` | **8 Intents** (`I01`–`I08`) |
| `04-states/` | **4 Gesprächsphasen** (`S0`–`S3`) |
| `04-entities/`, `04-signals/` | Slots + Signale (Klassifikations-Hilfsdimensionen) |
| `05-canvas/` | Material-Typen + Trigger/Aliase für die KI-Generierung (M10/M11) — Studio-Tab „Material-Formate“ |
| `05-knowledge/` | MCP-Server-Registry + RAG-Wissensbereiche |

Alle Dateien sind ohne Code-Deploy editierbar (mtime-Cache); das Studio bietet GUI-Editoren pro Schicht.

## 4. Klassifikations-Dimensionen

Jede Nutzernachricht wird per LLM in Dimensionen zerlegt — Input für die Pattern-Auswahl.

### 4a. Personas (6)

Personas steuern nur **Tonalität/Anrede**, nicht die Pattern-Wahl.

| ID | Rolle |
|----|-------|
| `P-AND` | Andere / unbekannt (neutraler Default) |
| `P-LEH` | Lehrkraft (kollegial, siezt) |
| `P-LER` | Lernende:r (ermutigend, duzt) |
| `P-ELT` | Eltern |
| `P-ENT` | Entscheider / Verwaltung / Politik / Schulleitung (formell, evidenzbasiert) |
| `P-RED` | Redaktion / Presse |

### 4b. Intents (8)

`I01` Orientierung · `I02` Wissensfrage · `I03` Inhalte-Suchen · `I04` Lernpfad · `I05` Inhalt-Generieren · `I06` Inhalt-Nachbearbeiten · `I07` Bot-Feedback · `I08` Einreichen / Melden.

### 4c. States (4)

Gesprächsphasen `S0`–`S3` (Einstieg → Klärung → Ergebnis → Vertiefung), je mit `bot_directive` + plausiblen Übergängen (`next_likely`).

### 4d. Entities & Signale

**Entities/Slots** (z.B. `thema`, `fach`, `stufe`, `material_typ`) + **Signale** (situative Hinweise). Marker/Diskriminatoren je Dimension: [docs/03-elemente.md](../docs/03-elemente.md).

## 5. Pattern-Auswahl (LLM-Hint)

Der Klassifikator liefert pro Turn neben Persona/Intent/State auch einen **`pattern_id_hint`** (`M01`–`M16`). `select_pattern()` (`app/services/pattern_engine.py`) wählt in dieser Reihenfolge:

1. **Safety-erzwungenes Pattern** (z.B. `M01` im Schutzfall) — gewinnt immer
2. **`pattern_id_hint`** des Klassifikators — der Normalfall
3. **Fallback** (`M15` Orientierung, sonst `M03` Klärung)

Intent und Pattern-Hint entstehen im **selben** LLM-Call — sie korrelieren stark, es gibt aber keine deterministische Intent→Pattern-Tabelle. Nach der Generierung wird das Label ggf. an die tatsächlich ausgeführte Aktion angeglichen (`M09` Lernpfad / `M10` KI-Material / `M03` Slot-Klärung), damit Telemetrie + InlineDocument-Box-Routing stimmen.

Die 16 Patterns + ihre `when_to_use` / `core_rule` / `forbidden_phrases` liegen in `03-patterns/*.md` und sind im Studio editierbar.

## 6. Output-Struktur (ChatResponse)

Jede Antwort von `POST /api/chat` liefert folgende Felder:

```json
{
  "session_id": "uuid",
  "content": "Antworttext des Bots (Markdown-formatiert)",
  "cards": [
    {
      "node_id": "...",
      "title": "Materialname",
      "description": "Kurzbeschreibung",
      "disciplines": ["Mathematik"],
      "educational_contexts": ["Sekundarstufe I"],
      "keywords": ["Bruchrechnung"],
      "learning_resource_types": ["Arbeitsblatt"],
      "url": "https://...",
      "wlo_url": "https://wirlernenonline.de/...",
      "preview_url": "https://...",
      "license": "CC BY-SA 4.0",
      "publisher": "...",
      "node_type": "content | collection",
      "topic_pages": [{"url": "...", "target_group": "teacher", "label": "Lehrkraefte"}]
    }
  ],
  "follow_up": "quick_replies | inline | none",
  "quick_replies": ["Zeig mir mehr davon", "Ich will das eingrenzen", "Anderes Thema"],
  "pagination": {
    "total_count": 42,
    "skip_count": 0,
    "page_size": 5,
    "has_more": true,
    "collection_id": "...",
    "collection_title": "..."
  },
  "page_action": null,
  "debug": { "...siehe Abschnitt 11..." }
}
```

**Felder im Detail:**

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| `content` | String | Markdown-formatierte Antwort. Laenge und Ton werden durch Pattern + Signale gesteuert. |
| `cards` | Array | WLO-Materialkarten mit Metadaten, Preview-URLs und Themenseiten-Links. Leer bei reinen Textantworten. |
| `follow_up` | String | Modus der Gespraechsfortsetzung (vom Pattern bestimmt). |
| `quick_replies` | Array | 2-4 klickbare Vorschlaege aus **User-Perspektive** (z.B. „Zeig mir mehr davon", nicht „Weitere Ergebnisse anzeigen"). Mix aus Vertiefung, Richtungswechsel, Fortsetzung und offener Frage. |
| `pagination` | Object | Nur bei paginierten Ergebnissen. Ermoeglicht „Mehr laden"-Button im Widget. |
| `page_action` | Object | Optionale Aktion fuer die Host-Seite (navigate, show_collection, share_content). |
| `debug` | Object | Vollstaendiger Trace des Request-Lifecycles (siehe Abschnitt 11). |

---

## 7. MCP & RAG — Wissensquellen

### MCP-Server (externe Tools)

Aktuell 1 Server: **WLO edu-sharing** mit 10 Tools.

| Tool | Kategorie | Beschreibung |
|------|-----------|-------------|
| `search_wlo_collections` | Suche | Sammlungen nach Fach/Thema/Stufe durchsuchen |
| `search_wlo_content` | Suche | Einzelne Materialien durchsuchen |
| `search_wlo_topic_pages` | Suche | Themenseiten mit Zielgruppen-Varianten (teacher/learner/general; serverseitig gemerged) |
| `get_collection_contents` | Navigation | Inhalte einer Sammlung abrufen |
| `get_node_details` | Details | Metadaten eines einzelnen Materials abrufen (mit `outputFormat=json` strukturiert) |
| `lookup_wlo_vocabulary` | Hilfs-Tool | WLO-Fachvokabular nachschlagen (Disziplinen, Bildungsstufen, Medientypen, Lizenzen, Zielgruppen) |
| `get_subject_portals` | Navigation | Liste aller WLO-Fachportale (Top-Level-Sammlungen, alphabetisch) |
| `browse_collection_tree` | Navigation | Strukturierter Drilldown unter eine Sammlung (Tiefe 1–2, optional File-Counts) |
| `get_nodes_details` | Details | Bulk-Metadaten fuer mehrere `nodeIds` parallel |
| `wlo_health_check` | Diagnose | API-Erreichbarkeit + Latenz |

> **Migration v1 → v2:** Die ehemaligen Web-Crawler-Tools (`get_wirlernenonline_info`,
> `get_edu_sharing_network_info`, `get_edu_sharing_product_info`, `get_metaventis_info`)
> wurden im MCP-Server v2 entfernt. Plattform-/Projekt-Themen werden jetzt
> ausschliesslich vom Boerdi-RAG (4 Wissensbereiche, immer vorab durchsucht) abgedeckt.

**Tool-Abhaengigkeit:** Wenn ein Suche-Tool aktiviert ist, werden `lookup_wlo_vocabulary` und
`get_node_details` automatisch hinzugefuegt (Code-Logik in Phase 3).

Server werden in `05-knowledge/mcp-servers.yaml` registriert. Im Studio koennen neue Server
per URL hinzugefuegt werden — die verfuegbaren Tools werden automatisch per MCP-Handshake
entdeckt.

### RAG-Wissensbereiche

4 Bereiche, alle im Modus `always` (werden bei jeder Nachricht als Kontext vorab durchsucht):

| Bereich | Chunks | Inhalt |
|---------|--------|--------|
| `edu-sharing-com-webseite` | 54 | edu-sharing als Open-Source-Loesung fuer Bildungscloud und Content-Management |
| `edu-sharing-net-webseite` | 37 | edu-sharing.net e.V. — gemeinnuetziges Netzwerk fuer digitale Bildungsclouds und OER |
| `wirlernenonline.de-webseite` | 106 | WirLernenOnline — offene Bildungsplattform mit Suchmaschine und Fachportalen |
| `wissenlebtonline-webseite` | 151 | WLO-Oekosystem — KI-gestuetzte Infrastruktur fuer Bildungsinhalte |

**Always-On-Ablauf:** Vor dem LLM-Call werden alle `always`-Bereiche per Embedding-Suche
durchsucht (Top 8 Chunks, min_score 0.25). Das Ergebnis wird als synthetisches Tool-Call/Result-Paar
in die Nachrichtenhistorie injiziert. Das LLM erhaelt die Chunks als Kontext und wird angewiesen,
bereits durchsuchte Bereiche nicht nochmal per `query_knowledge` abzurufen.

Konfiguration: `05-knowledge/rag-config.yaml`. Seed-Daten: `knowledge/rag-seed.json` (siehe
Deployment-Doku Abschnitt 4).

---

## 8. Safety-Pipeline (Triple-Schema v2)

Die Safety laeuft **vor** dem LLM-Call und kann Tools sperren oder Patterns erzwingen.
Aktuell unterscheidet das Gate zwei erzwungene Patterns:

- **`PAT-CRISIS`** — Selbstbezogene Krisen (Suizid, Selbstverletzung, Tabletten-Euphemismen, Jugendschutz): empathisch, Telefonseelsorge/112.
- **`PAT-REFUSE-THREAT`** — Drohungen gegen Dritte (§241 StGB, `hate/threatening`, `harassment/threatening`): sachlich-ablehnend, optional Hinweis auf 110. **Keine** Krisen-Empathie, da der Nutzer hier nicht das Opfer ist.

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

* `security_level`: `off | regex | standard | strict | paranoid`
  * **off** — nur Crisis/PII-Regex (~1 ms)
  * **regex** — + Prompt-Injection (~2 ms)
  * **standard** (Default) — + OpenAI-Moderation parallel (~150 ms)
  * **strict** — + LLM-Legal-Classifier smart (~150-300 ms)
  * **paranoid** — Legal immer + halbierte Schwellen + Double-Check
  * Alle LLM-Stages laufen via `asyncio.gather` parallel: Latenz ≈ `max(stage_times)`
  * Alias: `basic` wird transparent auf `standard` gemappt (Backwards-Compat)
* `presets.*`: definieren `moderation`, `legal_classifier`, `prompt_injection`,
  optional `threshold_multiplier` und `double_check`
* `escalation.legal_thresholds.flag` / `.high`: Schwellwerte fuer den Legal-Classifier
* `escalation.thresholds.*`: Schwellwerte je Moderation-Kategorie
* `crisis_blocked_tools`: Tools, die bei Crisis-Pattern blockiert werden

## 9. Rate Limits & Concurrency

`safety-config.yaml → rate_limits` — Sliding-Window pro Session und pro IP, plus
optionale IP-Whitelist. Defaults fuer 50 parallele Nutzer:

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

---

## 10. Widget-Auslieferung

`app/routers/widget.py` liest das Widget-Bundle in dieser Reihenfolge:

1. **`frontend/dist/widget/browser/main.js`** — Standard im Mono-Repo (kein Kopieren noetig).
2. **`backend/widget_dist/main.js`** — Fallback fuer isolierte Backend-Deploys.

Build-Optionen aus dem Repo-Root:

```bash
# Variante A — Mono-Repo / lokal (Default, kein Kopieren)
./scripts/build-widget.sh        # Linux/macOS
.\scripts\build-widget.ps1       # Windows

# Variante B — Backend isoliert deployen (mit Kopie nach backend/widget_dist/)
./scripts/sync-widget-to-backend.sh
.\scripts\sync-widget-to-backend.ps1
```

Falls das Bundle in beiden Verzeichnissen fehlt, antwortet `/widget/boerdi-widget.js` mit `503`
und einer expliziten Anleitung.

---

## 11. Authentifizierung, Sicherheit & Backup

### API-Key-Schutz

Schreibende und konfigurations-nahe Endpunkte koennen per Umgebungsvariable geschuetzt werden:

```bash
export STUDIO_API_KEY=geheim123          # Linux/macOS
$env:STUDIO_API_KEY="geheim123"          # PowerShell
```

Ist `STUDIO_API_KEY` leer oder ungesetzt, bleibt die API **offen** (Dev-Default). Beim Start wird
eine **Warnung** geloggt, damit dieser Zustand in Produktion nicht unbemerkt bleibt. Ist sie gesetzt,
verlangen folgende Routen den Header `X-Studio-Key: <wert>` (oder alternativ `?key=<wert>`):

* `GET/PUT/DELETE /api/config/*`
* `GET/PUT /api/rag/*`
* `GET/PUT /api/safety/*`
* `GET /api/debug/mcp-test`
* alle `/api/sessions/*`-Routen **ausser** `GET /{id}/messages`

**Bewusst offen** bleiben auch mit gesetztem Key:

* `POST /api/chat` — sonst koennte das Widget nicht chatten
* `/api/speech/*` — Whisper/TTS im Widget
* `/widget/*` — Bundle- und Demo-Auslieferung
* `GET /api/sessions/{id}/messages` — Cross-Page-History des Widgets

### Sicherheitsmassnahmen

| Massnahme | Beschreibung |
|-----------|-------------|
| **Path-Traversal-Schutz** | Alle Config-Dateioperationen (lesen/schreiben/loeschen/import) validieren relative Pfade gegen `CHATBOT_DIR` via `path.resolve().relative_to()`. `../`-Escapes werden blockiert. |
| **SSRF-Schutz** | Der MCP-Server-Discovery-Endpoint (`POST /mcp-servers/discover`) blockiert private, loopback und link-local IP-Adressen. |
| **CORS-Konfiguration** | `CORS_ORIGINS=*` (Default) deaktiviert `allow_credentials`. Fuer Produktion spezifische Origins setzen. |
| **Chat-Nachrichtenlimit** | `ChatRequest.message` ist auf 10.000 Zeichen begrenzt (Pydantic-Validierung). |
| **ZIP-Restore-Schutz** | `/api/config/restore` prueft ZIP-Eintraege auf absolute Pfade und `..`-Segmente. |
| **Startup-Warnung** | Fehlt `STUDIO_API_KEY`, loggt das Backend beim Start eine deutliche Warnung. |

### Backup & Restore der Konfiguration

```bash
# Komplettes chatbots/wlo/v1-Tree als ZIP ziehen
curl -H "X-Studio-Key: $STUDIO_API_KEY" \
     -o wlo-v1-backup.zip \
     http://localhost:8000/api/config/backup

# Restore (merge ueber bestehende Dateien)
curl -H "X-Studio-Key: $STUDIO_API_KEY" \
     -F "file=@wlo-v1-backup.zip" \
     http://localhost:8000/api/config/restore

# Restore mit vorherigem Leeren (wipe) des Trees
curl -H "X-Studio-Key: $STUDIO_API_KEY" \
     -F "file=@wlo-v1-backup.zip" \
     "http://localhost:8000/api/config/restore?wipe=true"
```

---

## 12. LLM-Provider & Einschraenkungen

Das Backend spricht drei OpenAI-kompatible Provider, umschaltbar per `LLM_PROVIDER`. **Default ist `openai`** — wenn die Variable leer oder nicht gesetzt ist, laeuft alles wie bisher mit OpenAI nativ.

| Provider | Chat-Default | Embed-Default | Auth |
|----------|--------------|---------------|------|
| `openai` _(Standard)_ | `gpt-4.1-mini` | `text-embedding-3-small` | `OPENAI_API_KEY` |
| `b-api-openai` | `gpt-4.1-mini` | `text-embedding-3-small` | `B_API_KEY` (Header `X-API-KEY`) |
| `b-api-academiccloud` | `Qwen/Qwen3.5-122B-A10B-GPTQ-Int4` | `e5-mistral-7b-instruct` | `B_API_KEY` |

Modelle per `LLM_CHAT_MODEL` / `LLM_EMBED_MODEL` ueberschreibbar. Implementiert in `app/services/llm_provider.py`.

### Beispiel-Setups

```bash
# Default (= ohne LLM_PROVIDER):
export OPENAI_API_KEY=sk-...

# B-API → OpenAI (gleiche Modelle, aber ueber die WLO-Proxy-Infrastruktur)
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
| **OpenAI STT** (`gpt-4o-mini-transcribe`) | `routers/speech.py` | Mikrofon-Button im Widget tot, sofern kein zusaetzlicher OpenAI-Key vorliegt. |
| **TTS** | `routers/speech.py` | Vorlese-Funktion deaktiviert. |
| **Stage-2 Moderation** | `services/safety_service.py` | Wird uebersprungen. Stage 1 (Regex) und Stage 3 (Legal-Classifier) bleiben aktiv. |
| **RAG-Vektor-Kompatibilitaet** | `services/rag_service.py` | `e5-mistral-7b-instruct` (1024 dim) ≠ `text-embedding-3-small` (1536 dim). **Bestehende Embeddings sind nach einem Wechsel zu `b-api-academiccloud` unbrauchbar — alle Dokumente neu indexieren.** |
| **Tool-/Function-Calling** | `services/llm_service.py` | Bei `b-api-openai` voll funktional. Bei `b-api-academiccloud` modellabhaengig. |
| **JSON-Mode** | `services/safety_service.py` | OpenAI/B-API-OpenAI: garantiert. AcademicCloud: nicht garantiert. |

**Empfehlung:**
* **Volle Feature-Paritaet:** `openai` (Standard) oder `b-api-openai`.
* **Datenschutz / EU-Hosting:** `b-api-academiccloud` (mit Einschraenkungen, siehe oben).

---

## 13. Datenbank

SQLite (`badboerdi.db`) mit folgenden Tabellen:

| Tabelle | Zweck |
|---------|-------|
| `sessions` | Session-State (Persona, State, Entities, Signals, Turn-Count) |
| `messages` | Nachrichtenverlauf pro Session (inkl. `debug_json` und `cards_json`) |
| `memory` | Key-Value-Speicher pro Session (short/long) |
| `safety_logs` | Geloggte Risk-Events (Risk-Level, Stages, Legal-Flags, Escalation) |
| `quality_logs` | Qualitaets-Metriken pro Turn (Pattern, Scores, Confidence, Degradation, Entities, Tool-Outcomes) |
| `rag_chunks` | RAG-Text-Chunks mit Embeddings (sqlite-vec, 1536 Dimensionen) |
| `meta` | Key-Value fuer System-Metadaten (z.B. Seed-Version) |

Init in `app/services/database.py`. Beim ersten Start werden Seed-Chunks aus
`knowledge/rag-seed.json` importiert (versioniert, siehe Deployment-Doku).

---

## 14. Debug-Output

Jede `/api/chat`-Antwort enthaelt ein `debug`-Objekt mit:

* `persona` — z.B. `P-W-LK (Lehrkraft)` — ID mit Label in Klammern
* `intent` — z.B. `I02 (Wissensfrage)` — ID mit Label
* `state` — z.B. `state-3 (Information)` — ID mit Label
* `turn_type` — `initial`, `follow_up`, `topic_switch`, `correction`, `clarification`
* `signals` — erkannte Signale (z.B. `["zielgerichtet", "Faktenfrage"]`)
* `pattern` — z.B. `M04 (Wissens-Antwort)` — gewähltes Pattern
* `entities` — extrahierte Slots (interne `_`-Keys werden gefiltert)
* `tools_called` — tatsaechlich aufgerufene Tools (inkl. prefetch)
* `phase3_modulations` — vollstaendiger Output der Modulations-Phase:
  - `tone`, `formality`, `length`, `detail_level`, `max_items`, `card_text_mode`
  - `response_type`, `format_primary`, `format_follow_up`, `sources`
  - `tools` (Pattern-definierte Tools), `rag_areas`, `core_rule`
  - `skip_intro`, `one_option`, `add_sources` (Boolean-Flags)
  - `degradation`, `missing_slots`, `blocked_patterns`
* `outcomes` — Tool-Outcomes mit Status, Item-Count und Latenz
* `safety` — Stages, Risk-Level, Categories, Legal-Flags, Escalated
* `policy` — Allowed/Blocked-Tools/Disclaimers
* `context` — ContextSnapshot (Page, Device, Turn-Count)
* `confidence` — Finale Confidence nach allen Adjustments
* `trace` — Phase-Trace mit Dauer pro Schritt

Das Frontend rendert dieses Objekt im Debug-Panel (Toggle via 🔍 im Header);
das Studio nutzt es fuer Sessions-Inspektion. Zusaetzlich wird jeder Turn
automatisch in die `quality_logs`-Tabelle geschrieben (siehe Abschnitt 15).

---

## 15. Quality-Logging

Jeder Chat-Turn wird automatisch in `quality_logs` protokolliert (non-blocking, fire-and-forget).
Steuerung ueber `01-base/quality-log-config.yaml`:

```yaml
logging:
  enabled: true              # An/Aus (Standard: true)
  retention_days: 180
```

**Gespeicherte Metriken pro Turn:**

| Feld | Beschreibung |
|------|-------------|
| `pattern_id` | Gewaehltes Pattern |
| `phase2_winner_score` | Score des Gewinners |
| `phase2_score_gap` | Abstand zum Zweitplatzierten (niedrig = ambig) |
| `intent_id`, `persona_id` | Klassifikationsergebnis |
| `final_confidence` | Finale Confidence nach Outcome-Adjustments |
| `turn_type` | initial / follow_up / topic_switch / correction |
| `signals`, `entities` | Erkannte Signale und Slots |
| `tools_called`, `tool_outcomes` | Aufgerufene Tools mit Status |
| `response_length`, `cards_count` | Antwortlaenge und Kartenanzahl |
| `degradation`, `missing_slots` | Ob Degradation aktiv war |
| `debug_json` | Vollstaendiges Debug-Objekt fuer Deep-Dive |

**Aggregierte Statistiken** ueber `GET /api/quality/stats`:
- Pattern-Verteilung, Intent-Verteilung
- Durchschnittliche Confidence und Score-Gap
- Degradation-Rate, Empty-Entity-Rate
- Anzahl Tight Races (Score-Gap < 0.02 — Pattern-Entscheidung war knapp)

**Delete-Endpoints** (alle hinter `X-Studio-Key` gesichert):

| Methode | Pfad | Zweck |
|---------|------|-------|
| `DELETE /api/sessions/{id}` | Session komplett loeschen (Messages + Memory + Quality + Safety + Session-Row). Cascade-Counts im Response. |
| `DELETE /api/sessions/{id}/messages` | Nur Chatverlauf leeren — Session, Memory und Analytics bleiben erhalten. |
| `DELETE /api/quality/logs/{log_id}` | Einzelner Quality-Log-Eintrag. |
| `POST /api/quality/logs/clear?pattern_id=&intent_id=&session_id=` | Bulk-Delete mit Filter. Ohne Filter verlangt `?confirm=true` (Sicherheitsbremse). |

Diese Endpoints sind in der Studio-UI unter **Sessions** und **Quality** mit Confirm-Dialogen verdrahtet.

---

## 16. Evaluation — automatisierte Persona-Dialog-Tests

Eigenstaendiges Eval-Subsystem zum systematischen Testen der Gespraechsqualitaet auf Basis
der in der Konfig definierten Personas/Intents/Patterns. Im Studio unter dem Tab
**Evaluation (🧪)** erreichbar.

### Architektur-Eckdaten

- **Config-agnostisch**: Liest Personas (`load_persona_definitions()`) und Intents
  (`load_intents()`) zur Laufzeit. Funktioniert unveraendert auch auf anderen Chatbot-Konfigs
  unter `chatbots/<name>/v1/`.
- **Echte Pipeline**: Alle simulierten Turns laufen durch den realen `/api/chat`-Endpoint
  (Safety, Pattern-Engine, RAG, MCP). Keine Shortcuts.
- **Unified Logging**: Jeder Turn landet in `quality_logs` (mit `session_id = 'eval-<uuid>'`)
  neben dem Produktions-Traffic. Pattern-Usage-Analytics arbeiten auf der gleichen Tabelle.
- **Dedizierte Tabelle `eval_runs`** fuer Run-Metadaten + Full-Transkripte (JSON) + Matrix-
  Aggregat. Nicht mit `quality_logs` verwoben, damit Eval-Ergebnisse unabhaengig geloescht
  werden koennen.

### Tabelle `eval_runs`

| Feld | Beschreibung |
|------|-------------|
| `id` | `eval-<hex12>` |
| `created_at` / `completed_at` | ISO-Timestamps |
| `status` | `running` \| `done` \| `failed` |
| `mode` | `scenarios` \| `conversations` \| `both` |
| `config_slug` | Optional, z.B. `wlo/v1` — fuer Cross-Config-Tracking |
| `personas`, `intents` | JSON-Arrays der einbezogenen IDs |
| `turns_per_conv`, `judge_model`, `simulator_model` | Run-Parameter |
| `total_turns`, `avg_score` | Aggregate |
| `summary_json` | `{ matrix: persona×intent→score, pattern_usage: {pat: n}, avg_score, total_judged_turns }` |
| `conversations_json` | Array von `{ kind, persona_id, intent_id, turns: [{user, bot, debug, judge}] }` |
| `error_message` | nur bei `status=failed` |

### Endpoints (alle Studio-geschuetzt)

| Methode | Pfad | Zweck |
|---------|------|-------|
| `GET /api/eval/config` | Aktuelle Personas + Intents aus dem aktiven Config-Tree |
| `POST /api/eval/estimate` | Kosten-/Token-Schaetzung (Spanne min/erwartet/max) |
| `POST /api/eval/runs` | Run starten (Background-Task, kehrt sofort zurueck) |
| `GET /api/eval/runs` | Liste aller Runs (neueste zuerst) |
| `GET /api/eval/runs/{id}` | Detail inkl. vollstaendiger Transkripte + Matrix |
| `DELETE /api/eval/runs/{id}` | Run entfernen |
| `GET /api/eval/analytics/pattern-usage` | Pattern × Intent × Persona aus `quality_logs` — wirkt auch ohne Eval-Run |

`POST /api/eval/runs` akzeptiert:
```json
{
  "mode": "scenarios|conversations|both",
  "persona_ids": ["P-W-LK", "P-W-SL"],     // leer = alle
  "intent_ids":  ["I02", "I04"],          // leer = alle
  "scenarios_per_combo": 2,                 // nur fuer mode=scenarios/both
  "turns_per_conv": 3,                      // nur fuer mode=conversations/both
  "config_slug": ""                         // optional, fuer Cross-Config-Tracking
}
```

Response enthaelt `run_id`, `status: "running"`, `personas_used`, `intents_used` und
`warnings` (z.B. bei ungueltigen IDs — werden stillschweigend gedropt mit Warnung).

### Judge-Dimensionen

Jeder Bot-Turn wird auf 5 Dimensionen bewertet (jeweils 0/1/2 Punkte):

| Dimension | Frage |
|-----------|-------|
| `intent_fit` | Beantwortet die Antwort das Anliegen der Persona? |
| `persona_tone` | Passt der Tonfall zur Persona? |
| `pattern_match` | Passt das gewaehlte Pattern zu Intent/Situation? |
| `safety` | Keine Guardrail-Verletzungen? |
| `info_quality` | Konkret und hilfreich (kein Geschwurbel)? |

Gesamt-Score = Summe / 10 ∈ [0, 1]. Judge liefert zusaetzlich `notes` (max 200 Zeichen
Freitext-Begruendung).

### Kosten

Default-Modelle: `EVAL_SIMULATOR_MODEL = EVAL_JUDGE_MODEL = gpt-4o-mini`. Kostenschaetzung
im Studio vor dem Start sichtbar. Typische Kosten (Chat-Modell `gpt-5.4-mini`, erwartet):

| Umfang | Turns | Kosten (USD) |
|--------|-------|--------------|
| 2 Personas × 2 Intents × 1 Szenario | 4 | ~$0.02 |
| Alle 9 × 14 × 1 Szenario | 126 | ~$0.70 |
| Alle 9 × 14 + 3-Turn-Dialoge | 504 | ~$3.20 |
| Alle 9 × 14 × 2 Szenarien + 3-Turn-Dialoge | 630 | ~$3.95 |

Die Schaetzung im Studio zeigt eine **Spanne** (min/erwartet/max mit -40%/+100%), weil
Prompt-Laengen, RAG-Kontext und Tool-Calls real variieren. In der Praxis landen die Ist-
Kosten meist im unteren Drittel der Spanne (wenige RAG-Treffer, keine Tools).

### Was nicht implementiert ist

- **Keine automatischen Config-Patches.** Der Judge schreibt Notes; kein Meta-LLM
  aendert YAML.
- **Keine CI-Pass/Fail-Gates.** LLM-Judge-Scores sind zu noisy dafuer.
- **Kein Persona-Health-Ampel-Dashboard.** Metriken sind Kartographie, keine Navigation.

### Script-Variante (Legacy)

`scripts/eval_reranker.py` misst speziell Retrieval-Qualitaet (Baseline vs. Rerank,
LLM-as-Judge). Weiterhin nutzbar fuer Retrieval-Tuning, unabhaengig vom Evaluation-Subsystem.

---

## 13. KI-Material-Generierung (M10 / M11)

Auf Erstell-Anfragen (Intent `I05`) generiert der Bot strukturiertes Material (Arbeitsblatt, Quiz, Factsheet, Lernpfad, …) und zeigt es als **InlineDocument-Box** direkt im Chat-Verlauf — es gibt **kein** separates Canvas-Pane mehr (in Welle E entfernt). Nachbearbeitung (Intent `I06`, Pattern `M11`) verfeinert die zuletzt erzeugte Box (kürzer fassen, Lösungen ergänzen, …).

**Konfiguration** in `chatbots/wlo/v1/05-canvas/` (Studio-Tab **Material-Formate**, mtime-Cache → kein Restart):

| Datei | Inhalt |
|-------|--------|
| `material-types.yaml` | Material-Typen (didaktisch + analytisch), je mit `id`, `label`, `emoji`, `category`, `structure` (LLM-Vorgabe). Typed GUI-Editor via `GET/PUT /api/config/canvas/material-types`. |
| `type-aliases.yaml` | Alias-Mapping (Keyword → Typ-ID) + LRT→Typ-Mapping. |
| `create-triggers.yaml` | Erstell-Verb-Phrasen + Negativ-Liste (Such-Verben grenzen ab). |
| `edit-triggers.yaml` | Nachbearbeitungs-Verben + Explizit-Neu-Override-Phrasen. |
| `persona-priorities.yaml` | Welche Personas zuerst analytische Typen sehen (P-ENT, P-RED). |

> Der Verzeichnisname `05-canvas/` ist historisch — das frühere User-Canvas-Pane wurde durch die InlineDocument-Box im Chat ersetzt; die Material-Typen-Konfiguration darunter ist weiterhin aktiv.

## 14. Themenseiten-Resolution (page_context_service)

Wenn das Widget auf einer WLO-Seite eingebettet ist, loest das Backend die URL vor dem ersten
Turn zu semantischen Metadaten auf. Das Frontend extrahiert dabei:

| URL-Pattern | Extrahierte Keys |
|-------------|------------------|
| `/themenseite/<slug>` | `topic_page_slug`, `page_type=themenseite` |
| `/fachportal/<fach>/<slug>` | `subject_slug`, `topic_page_slug`, `page_type=fachportal` |
| `/sammlung/<id>` | `collection_id` |
| `/material/<id>` | `node_id` |
| `/components/render/<uuid>` | `node_id` (edu-sharing) |
| Query: `?node=`, `?collection=`, `?q=` | `node_id`, `collection_id`, `search_query` |
| Fallback | `document_title` (Dokumenten-Titel) |

`page_context_service.resolve_page_context()` ruft dann:
1. `get_node_details(nodeId)` wenn `node_id`/`collection_id` vorhanden
2. `search_wlo_topic_pages(query=slug)` + folgenden `get_node_details` wenn nur Slug vorhanden
3. Fallback auf `document_title` wenn MCP fehlschlaegt

Das Ergebnis landet in `session_state.entities._page_metadata` mit TTL:

| Status | TTL | Begründung |
|--------|-----|------------|
| `resolved` (Titel, Beschreibung, Faecher, Stufen, LRTs) | **30 Min** | Themenseiten aendern sich selten |
| `unresolved` (MCP-Fehler / nur Dokumenten-Titel) | **2 Min** | Transiente Ausfaelle sollen sich schnell erholen |

Der System-Prompt erhaelt statt Roh-JSON einen semantischen Block:

```
## Aktuelle Themenseite
Titel: Optik
Beschreibung: Grundlagen der Optik - Licht, Brechung, Abbildung.
Faecher: Physik
Bildungsstufen: Sekundarstufe I, Sekundarstufe II
Schlagworte: Licht, Linse, Reflexion
Materialtypen auf der Seite: Video, Arbeitsblatt

Der Nutzer ist auf dieser Seite eingebettet. Regeln:
- Bei Fragen wie 'Worum geht es hier?' → beziehe dich direkt auf Titel/Beschreibung/Stufen.
- Bei Create-Anfragen ohne eigenes Thema → nimm den Seitentitel als Thema.
- Bei 'mehr Material dazu' → Suche mit Titel/Schlagworten starten.
```

Dadurch werden Anfragen wie „Worum geht es hier?" oder „Erstelle mir ein Quiz dazu" ohne
Rueckfrage beantwortet.
