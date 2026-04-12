# BadBoerdi — WLO Chatbot Plattform

BadBoerdi ist eine modulare Chatbot-Plattform für [WirLernenOnline](https://wirlernenonline.de).
Das System ist über das **Schema-Tripel-Modell** (22 Elemente · 31 Tripel · 5 Prompt-Schichten · 7
Verarbeitungsphasen) konfiguriert und besteht aus drei Komponenten:

| Komponente | Stack | Port | Zweck |
|------------|-------|------|-------|
| **`backend/`** | FastAPI · Python 3.11 · OpenAI · MCP | `8000` | Chat-API, Pattern-Engine, Safety-Pipeline, RAG, Session-Persistenz, Widget-Auslieferung |
| **`frontend/`** | Angular 21 · Web Components | `4200` | Chat-UI, einbettbares `<boerdi-chat>`-Widget |
| **`studio/`** | Next.js 15 · React 18 | `3001` | Konfigurations-UI für Persona, Patterns, Safety, Knowledge |

```
   ┌──────────────┐         ┌──────────────┐         ┌─────────────┐
   │   Studio     │  edits  │   Backend    │  reads  │  chatbots/  │
   │   :3001      │ ──────► │    :8000     │ ──────► │  wlo/v1/*   │
   └──────────────┘         └──────┬───────┘         └─────────────┘
                                   │
                                   │ POST /api/chat
                                   ▼
                            ┌──────────────┐
                            │   Frontend   │
                            │    :4200     │
                            │  (oder als)  │
                            │ <boerdi-chat>│
                            └──────────────┘
```

---

## 1. Quickstart

```bash
# 1) Backend starten
cd backend
pip install -r requirements.txt
cp .env.example .env   # OPENAI_API_KEY etc. eintragen
python run.py          # → http://localhost:8000

# 2) Frontend (Dev-Modus mit Proxy auf :8000)
cd ../frontend
npm install
npm start              # → http://localhost:4200

# 3) Studio (Konfigurations-UI)
cd ../studio
npm install
npm run dev            # → http://localhost:3001

# 4) Optional: Embeddable Widget bauen + via FastAPI ausliefern
cd ../frontend
npm run build:widget   # erzeugt dist/widget/browser/main.js
# → http://localhost:8000/widget/   (Demo-Seite)
# → http://localhost:8000/widget/boerdi-widget.js   (Bundle)
```

Bequemer Wrapper im Repo-Root:
```bash
./scripts/build-widget.sh        # Linux/macOS
./scripts/build-widget.ps1       # Windows PowerShell
```

---

## 2. Architektur — Schema-Tripel-Modell

BadBoerdi ist nicht "ein LLM mit System-Prompt", sondern ein **konfigurierbarer Verarbeitungs-
graph**. Jeder Turn läuft durch zwei orthogonale Achsen:

* **Y-Achse — 5 Prompt-Schichten**: regelt _was_ in welcher Priorität ins Kontextfenster geladen
  wird, damit nichts überflutet wird.
* **X-Achse — 7 Verarbeitungsphasen**: regelt _wann_ jedes Element im Turn-Zyklus aktiv wird.

Beide Achsen sind im Code 1:1 umgesetzt. Die Schichten sind in
`backend/app/services/llm_service.py → generate_response()` als `system_parts`-Liste
nachvollziehbar (siehe Kommentare `# Layer 1: …` bis `# Layer 5: …`).

### 2.1 Y-Achse — Die 5 Prompt-Schichten (Stand: Code)

| # | Schicht | Quelle im Repo | Wann geladen | Inhalt |
|---|---------|----------------|--------------|--------|
| **1** | **Identität & Schutz** | `chatbots/wlo/v1/01-base/base-persona.md`, `guardrails.md`, `safety-config.yaml`, `quality-log-config.yaml`, `device-config.yaml` | **Immer** — bei jedem Turn als erstes in den Prompt | Wer ist BOERDi, was darf er nie tun (Guardrails als _letzter_ Block, nicht überschreibbar), Sicherheits-Preset (off/basic/standard/strict/paranoid), Quality-Logging, Geräte-Heuristiken |
| **2** | **Domain & Regeln** | `chatbots/wlo/v1/02-domain/domain-rules.md`, `policy.yaml`, `wlo-plattform-wissen.md` | **Immer** — direkt nach Schicht 1 | Plattform-Wissen (WLO-Sammlungen, Lizenzen, Zielgruppen), Dauerregeln, Policy-Decisions (`policy_service.py`) |
| **3** | **Patterns** | `chatbots/wlo/v1/03-patterns/pat-01-…pat-20-*.md` | **Nach Bedarf** — nur das _eine_ Pattern, das der Pattern-Engine-Selector gewinnt (`pattern_engine.py → select_pattern()`) | Aktives Konversations-Muster mit `core_rule`, `tone`, `length`, `max_items`, `tools`, Modulationen wie `skip_intro`, `one_option`, `add_sources`, `degradation` |
| **4** | **Dimensionen** | Klassifikator-Output aus `llm_service.py → classify_input()` | **Pro Turn neu** | Persona-ID, Intent-ID + Confidence, Signals, Entities, Slots, next_state — strukturierte Werte für genau diesen Turn |
| **5** | **Wissen** | `chatbots/wlo/v1/05-knowledge/rag-config.yaml`, MCP-Tool-Outcomes, RAG-Memory (`rag_service.py`, `mcp_client.py`) | **Nur bei Bedarf** — wenn Pattern Tools ruft oder RAG-Bereich aktiv ist | Tool-Outcomes (Sammlungen, Materialien), RAG-Snippets, vorher gezeigte Sammlungen/Materialien aus dem Session-Memory |

**Entlade-Reihenfolge bei Token-Knappheit**: 5 → 4 → 3. Schichten 1 und 2 werden _nie_ entladen.

So sieht die Komposition im Code aus (`generate_response`, gekürzt):

```python
system_parts = [
    base_persona,        # Layer 1: Identity
    domain_rules,        # Layer 2: Domain
    persona_prompt,      # Layer 3 (Persona-spezifischer Anteil)
    pattern_block,       # Layer 3: Pattern
    context_block,       # Layer 4: Dimensions
    # ... Modulationen (skip_intro, one_option, add_sources, degradation)
    rag_context,         # Layer 5: Knowledge (optional)
    guardrails,          # Layer 1: Schutz — IMMER zuletzt, nicht überschreibbar
]
```

### 2.2 X-Achse — Die 7 Verarbeitungsphasen

Die Phasen entsprechen dem `_chat_impl()`-Flow in `backend/app/routers/chat.py`:

| Phase | Name | Code-Anker | Beschreibung |
|-------|------|-----------|--------------|
| **A** | Input | `ChatRequest`, `Environment`, `context_service.update_context()` | Rohdaten + Seitenkontext → Entity, Signal, Context |
| **B** | Interpretation | `llm_service.classify_input()` (Tool-Call `classify_input`) | Persona, Intent, Confidence, Slots, next_state |
| **C** | Steuerung | `safety_service.assess_safety()`, `policy_service.evaluate()`, `pattern_engine.select_pattern()` | Safety/Policy/Confidence/State priorisieren Pattern; Safety hat Vetorecht |
| **D** | Bypass | Im Pattern-Output: `signal → tone/length`, `device → max_items`, `safety → blocked_tools` | Direkte Wirkungen, die Pattern-Defaults übersteuern |
| **E** | Execution | `llm_service.generate_response()` + `mcp_client.call_mcp_tool()` → `outcome_service` | Pattern ruft Tools, Outcomes werden zu Content; Schicht 5 wird befüllt |
| **F** | Feedback | `database.save_message()`, `context_service`, Memory-Felder `_last_collections`, `_last_contents` | Content + Outcome aktualisieren State und Session-Memory |
| **G** | Observability | `trace_service`, `DebugInfo` im Response | Vollständiger Score-Log + Phase-Trace im `debug.trace`-Feld der API-Antwort |

Jede Phase ist im Backend isoliert testbar (siehe `backend/app/services/`).

### 2.3 Die 22 Elemente

Persona · Policy · Safety · Guardrails · Environment · Context · Memory · Pattern · Intent ·
Entity · Slot · Signal · State · Confidence · Tool · Outcome · Content · Style · Format ·
Trace · Turn · UserFeedback. Sie sind in `backend/chatbots/wlo/v1/04-*` und `01-base/`,
`02-domain/`, `03-patterns/`, `05-knowledge/` als YAML/Markdown-Dateien hinterlegt und werden
über `services/config_loader.py` eingelesen — d.h. _jede_ Konfigurationsänderung im Studio wirkt
ohne Code-Deploy.

---

## 3. Repo-Layout

```
badboerdi/
├── backend/             # FastAPI-Service
│   ├── app/
│   │   ├── routers/     # chat, sessions, safety, quality, config, rag, speech, widget
│   │   ├── services/    # llm, pattern_engine, safety, policy, rag, rate_limiter, trace, …
│   │   └── main.py
│   ├── chatbots/wlo/v1/ # ↳ Konfigurations-Bundle (5 Schichten als Verzeichnisse)
│   │   ├── 01-base/     # Layer 1: Persona, Guardrails, Safety, Device
│   │   ├── 02-domain/   # Layer 2: Domain-Wissen, Policy
│   │   ├── 03-patterns/ # Layer 3: 20 Patterns
│   │   ├── 04-*/        # Layer 4: Personas, Intents, Entities, Slots, Signals, States, Contexts
│   │   └── 05-knowledge/# Layer 5: RAG- und MCP-Konfiguration
│   └── run.py
├── frontend/            # Angular-App + Web-Component-Widget
│   ├── src/app/chat/    # Chat-UI (Standalone-Component)
│   ├── src/app/widget/  # <boerdi-chat>-Wrapper für die Web-Component
│   ├── src/widget-main.ts  # Bootstrap via @angular/elements
│   └── angular.json     # build-widget Target
├── studio/              # Next.js-Studio (Layer-Editoren)
│   └── src/components/  # ConfigTextEditor, PatternEditor, SecurityLevelPicker, …
└── scripts/
    ├── build-widget.sh
    └── build-widget.ps1
```

---

## 4. Widget-Build & Auslieferung

Das Widget wird von Angular als **Custom Element** (`<boerdi-chat>`) gebaut und vom FastAPI-
Backend direkt aus `frontend/dist/widget/browser/` ausgeliefert. Es ist **keine Kopie nötig** —
der Router (`backend/app/routers/widget.py`) liest das Build-Output zur Laufzeit:

```
frontend/dist/widget/browser/main.js
              │
              ▼
backend/app/routers/widget.py
              │
              ▼
GET /widget/boerdi-widget.js   ←  Embedder-URL
GET /widget/                   ←  Demo-HTML
```

### Build-Skripte unter `scripts/`

| Skript | Zweck | Wann verwenden |
|--------|-------|----------------|
| `build-widget.sh` / `build-widget.ps1` | `npm run build:widget` ausführen, Bundle-Größe verifizieren. | **Standardfall**: Mono-Repo / lokal / VM-Deploy. Backend liest `frontend/dist/widget/browser/main.js` direkt — keine Kopie nötig. |
| `sync-widget-to-backend.sh` / `sync-widget-to-backend.ps1` | Bauen **+ kopieren** nach `backend/widget_dist/main.js`. | Nur wenn das Backend isoliert deployed wird (Container/Serverless ohne Geschwister-`frontend/`-Verzeichnis). Der Widget-Router fällt automatisch auf diese Kopie zurück. |

```bash
# Linux/macOS
./scripts/build-widget.sh                # → frontend/dist/widget/browser/main.js
./scripts/sync-widget-to-backend.sh      # → backend/widget_dist/main.js (zusätzlich)

# Windows PowerShell
.\scripts\build-widget.ps1
.\scripts\sync-widget-to-backend.ps1
```

Die Convenience-Skripte unter `scripts/` rufen `npm run build:widget` aus dem `frontend/`-
Verzeichnis auf und prüfen anschließend, dass `main.js` existiert. Mehr in
[`backend/README.md`](backend/README.md) und [`frontend/README.md`](frontend/README.md).

---

## 5. Sicherheit & Konfiguration

Alle Deployment-relevanten Schalter laufen über vier Umgebungsvariablen plus eine Runtime-Variable
im Browser:

| Variable | Komponente | Default | Wirkung |
|----------|------------|---------|---------|
| `STUDIO_API_KEY` | Backend | _leer_ | Leer = API offen. Sonst Pflicht-Header `X-Studio-Key` auf `/api/config/*`, `/api/rag/*`, `/api/safety/*`, `/api/quality/*` und schreibenden `/api/sessions/*`. `/api/chat`, `/api/speech`, `/widget/*` und `GET /api/sessions/{id}/messages` bleiben bewusst offen. |
| `STUDIO_API_KEY` | Studio (`.env.local`) | _leer_ | Wird vom Studio-Proxy (`src/app/api/[...path]/route.ts`) server-seitig als `X-Studio-Key` an das Backend injiziert. Muss zum Backend-Wert passen. Kein `NEXT_PUBLIC_`-Prefix — der Browser sieht den Key nie. |
| `STUDIO_PASSWORD` | Studio | _leer_ | Optionales Cookie-basiertes Login-Gate vor dem Studio. |
| `BACKEND_URL` | Studio | `http://localhost:8000` | Proxy-Ziel des Studios. Zeigt auf das FastAPI-Backend. |
| `window.BOERDI_API_URL` | Frontend-Widget (Runtime) | _unset → `/api`_ | Backend-Basis-URL für das eingebettete Widget. Vor dem `<script src="…/boerdi-widget.js">` im Host-HTML setzen. |

### LLM-Provider

Das Backend spricht drei OpenAI-kompatible Provider, umschaltbar per `LLM_PROVIDER`:

| Provider | `LLM_PROVIDER` | Default Chat-Modell | Default Embedding | Auth |
|----------|----------------|---------------------|-------------------|------|
| OpenAI nativ | `openai` | `gpt-4.1-mini` | `text-embedding-3-small` | `OPENAI_API_KEY` |
| B-API → OpenAI | `b-api-openai` | `gpt-4.1-mini` | `text-embedding-3-small` | `B_API_KEY` (Header `X-API-KEY`) |
| B-API → AcademicCloud | `b-api-academiccloud` | `Qwen/Qwen3.5-122B-A10B-GPTQ-Int4` | `e5-mistral-7b-instruct` | `B_API_KEY` |

**Standard ist `openai`** — wenn `LLM_PROVIDER` nicht gesetzt ist, läuft das System wie bisher. Modelle lassen sich jederzeit per `LLM_CHAT_MODEL` / `LLM_EMBED_MODEL` überschreiben. Die Basis-URL der B-API ist über `B_API_BASE_URL` (Default `https://b-api.staging.openeduhub.net/api/v1/llm`) konfigurierbar.

#### Einschränkungen bei B-API-Providern

Die B-API stellt nur die OpenAI-kompatiblen `chat/completions`- und `embeddings`-Endpoints bereit. Folgende Funktionen sind daher **nur bei `LLM_PROVIDER=openai` verfügbar** und werden bei den beiden B-API-Providern automatisch deaktiviert oder schlagen fehl:

| Funktion | Verhalten bei B-API | Auswirkung |
|----------|---------------------|------------|
| **Sprach-Eingabe** (`POST /api/speech/transcribe`, Whisper) | Endpoint existiert nicht — fällt nur, wenn `OPENAI_API_KEY` zusätzlich gesetzt ist; sonst HTTP 500. | Mikrofon-Button im Widget funktioniert nicht. |
| **Text-to-Speech** (`POST /api/speech/synthesize`, OpenAI TTS) | Wie oben — braucht `OPENAI_API_KEY` als Fallback. | Vorlese-Funktion deaktiviert. |
| **Stage 2 Moderation** (`omni-moderation-latest`) | Wird übersprungen (`is_openai_native()`-Gate). | Keine OpenAI-Kategorien im `safety.categories`-Debug-Feld. Regex-Stage (Stage 1) **und** Legal-Classifier (Stage 3) bleiben voll aktiv — die Sicherheits-Pipeline ist also weiter wirksam, nur etwas weniger fein granuliert. |
| **AcademicCloud-Embeddings für RAG** | `e5-mistral-7b-instruct` hat eine andere Vektor-Dimension als `text-embedding-3-small`. | **Bestehende RAG-Vektoren werden inkompatibel.** Nach einem Provider-Wechsel müssen alle Dokumente per `POST /api/rag/reindex` (oder über das Studio-RAG-Panel) neu eingebettet werden. Im Mischbetrieb gibt es sonst keine Treffer. |
| **JSON-Mode** (`response_format={"type":"json_object"}`) für Legal-Classifier | Wird vom AcademicCloud-Backend nicht garantiert unterstützt. | Bei `b-api-academiccloud` kann der Legal-Classifier gelegentlich nicht-JSON liefern und fällt dann auf `risk=0` zurück (bestehender Fehler-Fallback in `safety_service.py`). |
| **Tool-Calls / Function-Calling** | Bei OpenAI-Modellen über B-API voll unterstützt. Bei AcademicCloud-Modellen modellabhängig (Llama-3.1-Instruct & Qwen können es, kleinere Modelle ggf. nicht). | Wenn das Modell keine Tool-Calls beherrscht, schlägt `classify_input` fehl → Klassifikation fällt auf Defaults zurück, Pattern-Auswahl wird ungenauer. |

**Empfehlung:** Für Produktion mit voller Feature-Parität `LLM_PROVIDER=openai` (oder `b-api-openai`) verwenden. `b-api-academiccloud` ist ideal für datenschutz-sensitive Szenarien ohne Sprach-/TTS-Bedarf — vor dem Umschalten den RAG-Index neu aufbauen.



### Backup & Restore

Der komplette `chatbots/wlo/v1`-Tree lässt sich als ZIP sichern und zurückspielen — entweder
direkt per Backend-API (`GET /api/config/backup`, `POST /api/config/restore?wipe=…`) oder
bequem über die **Backup / Restore**-Buttons im Studio-Header. Details in
[`backend/README.md`](backend/README.md) und [`studio/README.md`](studio/README.md).

---

## 6. Komponenten-READMEs

* **[backend/README.md](backend/README.md)** — API-Routen, Safety-Pipeline, Pattern-Engine,
  Konfigurationsformat, Rate-Limits, Sessions, MCP & RAG.
* **[frontend/README.md](frontend/README.md)** — Chat-UI, Web-Component-Bauweise, Widget-
  Properties, Embedding-Beispiele, Cross-Page-Session-Continuity.
* **[studio/README.md](studio/README.md)** — Layer-Editoren, welcher Editor welche Datei in
  `chatbots/wlo/v1/` schreibt, Empfohlene Workflows.

---

## 7. Lizenz & Mitwirkende

Internes Projekt — siehe `LICENSE` (sofern vorhanden) bzw. den Rahmenvertrag mit
WirLernenOnline.
