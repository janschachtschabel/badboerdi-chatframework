# BadBoerdi — WLO Chatbot Plattform

BadBoerdi ist eine modulare Chatbot-Plattform für [WirLernenOnline](https://wirlernenonline.de).
Das System ist über das **Schema-Tripel-Modell** (22 Elemente · 31 Tripel · **6 Prompt-Schichten** · 7
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

### Variante A — Docker (empfohlen für Ops/Prod, zero manuelle Schritte)

```bash
cp .env.example .env                 # OPENAI_API_KEY etc. eintragen (Root-Repo oder backend/)
docker compose up --build            # baut alle drei Images + startet
```

Der Backend-Build baut den RAG-Reranker in einer Multi-Stage-Pipeline automatisch
mit ein (keine torch-Laufzeit im Final-Image). Siehe Abschnitt **9. Docker-Deployment**.

### Variante B — Lokal / Dev

```bash
# 1) Backend starten
cd backend
pip install -r requirements.txt
cp .env.example .env                 # OPENAI_API_KEY etc. eintragen

# Einmalig: RAG-Reranker exportieren (ca. 1 Min, ~135 MB Modelldatei)
pip install -r requirements-setup.txt \
  --extra-index-url https://download.pytorch.org/whl/cpu
python -m scripts.setup

python run.py                        # → http://localhost:8000

# 2) Frontend (Dev-Modus mit Proxy auf :8000)
cd ../frontend
npm install
npm start                            # → http://localhost:4200

# 3) Studio (Konfigurations-UI)
cd ../studio
npm install
npm run dev                          # → http://localhost:3001

# 4) Optional: Embeddable Widget bauen + via FastAPI ausliefern
cd ../frontend
npm run build:widget                 # erzeugt dist/widget/browser/main.js
# → http://localhost:8000/widget/   (Demo-Seite)
# → http://localhost:8000/widget/boerdi-widget.js   (Bundle)
```

Bequemer Wrapper im Repo-Root:
```bash
./scripts/build-widget.sh            # Linux/macOS
./scripts/build-widget.ps1           # Windows PowerShell
```

---

## 2. Architektur — Schema-Tripel-Modell

BadBoerdi ist nicht "ein LLM mit System-Prompt", sondern ein **konfigurierbarer Verarbeitungs-
graph**. Jeder Turn läuft durch zwei orthogonale Achsen:

* **Y-Achse — 6 Prompt-Schichten**: regelt _was_ in welcher Priorität ins Kontextfenster geladen
  wird, damit nichts überflutet wird.
* **X-Achse — 7 Verarbeitungsphasen**: regelt _wann_ jedes Element im Turn-Zyklus aktiv wird.

Beide Achsen sind im Code 1:1 umgesetzt. Die Schichten sind in
`backend/app/services/llm_service.py → generate_response()` als `system_parts`-Liste
nachvollziehbar (siehe Kommentare `# Layer 1: …` bis `# Layer 6: …`).

### 2.1 Y-Achse — Die 6 Prompt-Schichten (Stand: Code)

| # | Schicht | Quelle im Repo | Wann geladen | Inhalt |
|---|---------|----------------|--------------|--------|
| **1** | **Identität & Schutz** | `chatbots/wlo/v1/01-base/base-persona.md`, `guardrails.md`, `safety-config.yaml`, `quality-log-config.yaml`, `device-config.yaml` | **Immer** — bei jedem Turn als erstes in den Prompt | Wer ist BOERDi, was darf er nie tun (Guardrails als _letzter_ Block, nicht überschreibbar), Sicherheits-Preset (off/basic/standard/strict/paranoid), Quality-Logging, Geräte-Heuristiken |
| **2** | **Domain & Regeln** | `chatbots/wlo/v1/02-domain/domain-rules.md`, `policy.yaml`, `wlo-plattform-wissen.md` | **Immer** — direkt nach Schicht 1 | Plattform-Wissen (WLO-Sammlungen, Lizenzen, Zielgruppen), Dauerregeln, Policy-Decisions (`policy_service.py`) |
| **3** | **Patterns** | `chatbots/wlo/v1/03-patterns/pat-*.md` (26 Patterns) | **Nach Bedarf** — nur das _eine_ Pattern, das der Pattern-Engine-Selector gewinnt (`pattern_engine.py → select_pattern()`) | Aktives Konversations-Muster mit `core_rule`, `tone`, `length`, `max_items`, `tools`, Modulationen wie `skip_intro`, `one_option`, `add_sources`, `degradation` |
| **4** | **Dimensionen** | Klassifikator-Output aus `llm_service.py → classify_input()` + `04-*/*.yaml` (Personas, Intents, States, Entities, Signals) | **Pro Turn neu** | Persona-ID, Intent-ID + Confidence, Signals, Entities, Slots, next_state — strukturierte Werte für genau diesen Turn |
| **5** | **Canvas-Formate** | `chatbots/wlo/v1/05-canvas/*.yaml` (material-types, type-aliases, create-triggers, edit-triggers, persona-priorities) | **Nur bei Canvas-Intents (INT-W-11, INT-W-12)** — liefert Struktur-Vorgabe des gewählten Material-Typs | 18 Material-Typen (13 didaktisch + 5 analytisch), Alias-Mapping, Create-/Edit-Trigger-Phrasen, Persona-abhängige Reihenfolge |
| **6** | **Wissen** | `chatbots/wlo/v1/05-knowledge/rag-config.yaml`, MCP-Tool-Outcomes, RAG-Memory (`rag_service.py`, `mcp_client.py`), Themenseiten-Resolver (`page_context_service.py`) | **Nur bei Bedarf** — wenn Pattern Tools ruft, RAG-Bereich aktiv ist oder `node_id`/`topic_page_slug` über `page_context` aufgelöst werden kann | Tool-Outcomes, RAG-Snippets, gemerkte Materialien aus Session-Memory, semantisch aufgelöste Themenseiten-Metadaten |

**Entlade-Reihenfolge bei Token-Knappheit**: 6 → 5 → 4 → 3. Schichten 1 und 2 werden _nie_ entladen.

So sieht die Komposition im Code aus (`generate_response`, gekürzt):

```python
system_parts = [
    base_persona,        # Layer 1: Identity
    domain_rules,        # Layer 2: Domain
    persona_prompt,      # Layer 3 (Persona-spezifischer Anteil)
    pattern_block,       # Layer 3: Pattern
    context_block,       # Layer 4: Dimensions
    # ... Modulationen (skip_intro, one_option, add_sources, degradation)
    canvas_structure,    # Layer 5: Canvas-Material-Struktur (INT-W-11/12 only)
    page_context_block,  # Layer 6: aufgelöste Themenseite (page_context_service)
    rag_context,         # Layer 6: Knowledge (optional)
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
`02-domain/`, `03-patterns/`, `05-canvas/`, `05-knowledge/` als YAML/Markdown-Dateien
hinterlegt und werden über `services/config_loader.py` eingelesen — d.h. _jede_
Konfigurationsänderung im Studio wirkt ohne Code-Deploy (mtime-gecachter YAML-Loader,
automatische Cache-Invalidierung bei Writes).

### 2.4 Routing-Rules Engine (deklarativ, Pre + Post Pattern-Selection)

Über der Pattern-Engine liegt eine **YAML-getriebene Regel-Engine** (`backend/app/services/rule_engine.py` +
`backend/chatbots/wlo/v1/06-rules/routing-rules.yaml`). Sie läuft zweimal pro Turn:

| Phase | Wann | Zweck |
|-------|------|-------|
| **Pre-Route** | _Vor_ der Pattern-Selektion | Korrigiert Persona/Intent/State des Classifiers — z.B. explizite Self-IDs („ich bin Lehrerin" → `P-W-LK`), Low-Confidence-Fallbacks, Sicherheits-Overrides |
| **Post-Route** | _Nach_ der Pattern-Selektion | Tiebreaker bei knappen Score-Differenzen, Intent-spezifische Patterns durchsetzen (PAT-22/23/24), Enforce-Routing für klare Persona-Intent-Konstellationen |

Eine Regel besteht aus `when` (Bedingungen) und `then` (Effekte) und kann **shadow** (`live: false`) für
beobachtende Roll-Outs oder **live** (`live: true`) geschaltet werden. Beispiel:

```yaml
- id: rule_recherche_personas_force_pat09
  description: "Recherche-Personas (RED/PRESSE/POL/BER) + Thema → PAT-09."
  priority: 55
  live: true
  when:
    all:
      - persona: { in: ["P-W-RED", "P-W-PRESSE", "P-W-POL", "P-BER"] }
      - intent:  { in: ["INT-W-03b", "INT-W-09"] }
      - entity.thema: { non_empty: true }
      - pattern_winner: { in: ["PAT-06", "PAT-01", "PAT-02", "PAT-10"] }
  then:
    enforced_pattern_id: "PAT-09"
```

Komparatoren: `eq, neq, in, not_in, regex, not_regex, empty, non_empty, exists, lt, gt, lte, gte` +
boolesche Kombinatoren `all, any, not`. Direkter Zugang im Studio über die Sidebar **Architektur ⚙️ Routing-Rules** —
inklusive Test-Bench (sub-ms, kein LLM-Call) und Fire-Count-Stats pro Regel.

### 2.5 Canvas-Arbeitsfläche (seit 2026-04-17)

Das Widget öffnet neben dem Chat auf breiten Displays eine **Canvas-Pane** für strukturierte
Ausgaben. Getrieben durch zwei Intents:

* **INT-W-11 · Inhalt erstellen** → PAT-21 Canvas-Create, ruft `canvas_service.generate_canvas_content()`
  mit Thema + Material-Typ auf und liefert strukturiertes Markdown + `page_action: canvas_open`.
* **INT-W-12 · Canvas-Edit** → `_handle_canvas_edit()` verfeinert den bestehenden Canvas-Inhalt
  ohne Neu-Generierung, getriggert durch Edit-Phrasen („mach es einfacher", „füge Lösungen hinzu",
  „kürzer fassen") im state-12.

**18 Material-Typen**, konfigurierbar im Studio-Layer „Canvas-Formate":

| Kategorie | Typen |
|-----------|-------|
| **Didaktisch** (13) | Automatisch, Arbeitsblatt, Infoblatt, Präsentation, Quiz, Checkliste, Glossar, Strukturübersicht, Übungsaufgaben, Lerngeschichte, Versuchsanleitung, Diskussionskarten, Rollenspielkarten |
| **Analytisch** (5) | Bericht, Factsheet, Projektsteckbrief, Pressemitteilung, Vergleich |

Analytische Personas (P-VER Verwaltung, P-W-POL Politik, P-W-PRESSE Presse, P-BER Berater,
P-W-RED Redaktion) sehen die analytischen Typen zuerst in den Quick-Replies; didaktische
Personas (Lehrkraft, Schüler:in, Eltern, anonym) die didaktischen. PAT-21 ist für alle
Personas erreichbar (`gate_personas: ["*"]`).

### 2.6 Themenseiten-Auflösung

Wenn das Widget auf einer WLO-Themenseite (`/themenseite/<slug>`), in einem Fachportal
(`/fachportal/<fach>/<slug>`), auf einem edu-sharing-Render (`/components/render/<uuid>`) oder
einer Sammlungsseite (`/sammlung/<id>`) eingebettet ist, löst das Backend die URL vor dem ersten
Turn automatisch via MCP (`get_node_details`, `search_wlo_topic_pages`) auf und cached die
Metadaten in der Session:

```
Aktuelle Themenseite
  Titel: Optik
  Fächer: Physik
  Bildungsstufen: Sekundarstufe I, Sekundarstufe II
  Schlagworte: Licht, Linse, Reflexion
  Materialtypen auf der Seite: Video, Arbeitsblatt
```

Dieser Block landet direkt im System-Prompt — der Bot kann anschließend „Worum geht es auf
dieser Seite?", „Welche Klassenstufe?" oder „Erstelle mir ein Quiz dazu" (Thema = Seiten-Titel)
ohne Rückfrage beantworten. TTL: 30 Min bei erfolgreicher Auflösung, 2 Min bei MCP-Fehler (damit
transiente Ausfälle keinen Stunden-Lock verursachen).

---

## 3. Repo-Layout

```
badboerdi/
├── backend/             # FastAPI-Service
│   ├── app/
│   │   ├── routers/     # chat, sessions, safety, quality, config, rag, speech, widget
│   │   ├── services/    # llm, pattern_engine, safety, policy, rag, canvas, page_context, …
│   │   └── main.py
│   ├── chatbots/wlo/v1/ # ↳ Konfigurations-Bundle (6 Schichten als Verzeichnisse)
│   │   ├── 01-base/     # Layer 1: Persona, Guardrails, Safety, Device
│   │   ├── 02-domain/   # Layer 2: Domain-Wissen, Policy
│   │   ├── 03-patterns/ # Layer 3: 26 Patterns (PAT-01…PAT-24, PAT-CRISIS, PAT-REFUSE-THREAT)
│   │   ├── 04-*/        # Layer 4: 9 Personas, 14 Intents, 12 States, 5 Entities, 17 Signals, Contexts
│   │   ├── 05-canvas/   # Layer 5: 18 Material-Typen, Aliase, Create-/Edit-Trigger, Persona-Priorität
│   │   └── 05-knowledge/# Layer 6: RAG- und MCP-Konfiguration
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

### Custom-Element-Attribute

Das Widget akzeptiert die folgenden Attribute auf `<boerdi-chat>`. Werte sind Strings (HTML-Attribute);
Booleans erkennen `"true"` / `"false"`.

| Attribut | Default | Wirkung |
|----------|---------|---------|
| `api-url` | _Pflicht_ | Backend-Basis-URL (z.B. `https://api.example.de`). Wird zu `…/api` normalisiert. |
| `position` | `bottom-right` | FAB-Position: `bottom-right` · `bottom-left` · `top-right` · `top-left` |
| `initial-state` | `collapsed` | `collapsed` (FAB) oder `expanded` (Panel offen) |
| `primary-color` | `#1c4587` | Hauptfarbe (CSS-Hex) |
| `greeting` | _leer_ | Eigene Begrüßungsnachricht beim ersten Öffnen |
| `persist-session` | `true` | Session-ID in `localStorage` halten — Verlauf bleibt über Page-Reload |
| `session-key` | `boerdi_session_id` | localStorage-Schlüssel |
| `auto-context` | `true` | Seitenkontext (URL, Title) automatisch ans Backend senden |
| `page-context` | _leer_ | Zusätzlicher Kontext als JSON-String oder Objekt |
| `show-debug-button` | `true` | 🔍 Debug-Toggle im Header. `false` = Button ausgeblendet (für Produktiv-Embeddings) |
| `show-language-buttons` | `true` | 🔊 Text-to-Speech und 🎤 Mic-Aufnahme. `false` = beide Buttons aus (kein Sprach-Feature) |

```html
<!-- Beispiel: Produktiv-Embedding ohne Debug, ohne Sprache -->
<boerdi-chat
  api-url="https://api.example.de"
  primary-color="#1c4587"
  show-debug-button="false"
  show-language-buttons="false">
</boerdi-chat>
```

Im Studio dokumentiert unter **System → Info → Widget-Einbettung**.

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

| Provider | `LLM_PROVIDER` | Default Chat-Modell | Default Embedding | Base-URL-Env | Auth |
|----------|----------------|---------------------|-------------------|--------------|------|
| OpenAI nativ | `openai` | `gpt-5.4-mini` | `text-embedding-3-small` | `OPENAI_BASE_URL` (optional, default SDK-URL) | `OPENAI_API_KEY` |
| B-API → OpenAI | `b-api-openai` | `gpt-4.1-mini` | `text-embedding-3-small` | `B_API_BASE_URL` | `B_API_KEY` (Header `X-API-KEY`) |
| B-API → AcademicCloud | `b-api-academiccloud` | `Qwen/Qwen3.5-122B-A10B-GPTQ-Int4` | `e5-mistral-7b-instruct` | `B_API_BASE_URL` | `B_API_KEY` |

**Standard ist `openai`** — wenn `LLM_PROVIDER` nicht gesetzt ist, läuft das System mit den oben gezeigten Defaults. Modelle lassen sich jederzeit per `LLM_CHAT_MODEL` / `LLM_EMBED_MODEL` überschreiben. `OPENAI_BASE_URL` ist optional und erlaubt OpenAI-kompatible Gegenstellen (Azure OpenAI, LiteLLM-Proxy, LocalAI, Ollama-Shim). Die Basis-URL der B-API ist über `B_API_BASE_URL` (Default `https://b-api.staging.openeduhub.net/api/v1/llm`) konfigurierbar.

### Vollständige Env-Variablen-Liste

Alle URL-/Key-/Modell-Einstellungen sind über Umgebungsvariablen steuerbar. **Alle Defaults reproduzieren das as-shipped Verhalten** — ohne `.env` läuft das System sofort los, sobald `OPENAI_API_KEY` gesetzt ist.

| Bereich | Variable | Default | Wirkung |
|---------|----------|---------|---------|
| **Provider** | `LLM_PROVIDER` | `openai` | Backend-Switch |
| **OpenAI nativ** | `OPENAI_API_KEY` | — | API-Key |
| | `OPENAI_BASE_URL` | SDK-Default (`https://api.openai.com/v1`) | OpenAI-kompatible Gegenstelle (Azure, LiteLLM, LocalAI, …) |
| | `LLM_CHAT_MODEL` | `gpt-5.4-mini` | Chat-Modell |
| | `LLM_EMBED_MODEL` | `text-embedding-3-small` | Embedding-Modell |
| | `OPENAI_MODEL` | _leer_ | Legacy-Alias für `LLM_CHAT_MODEL` |
| **B-API** | `B_API_KEY` | — | API-Key (`X-API-KEY`-Header) |
| | `B_API_BASE_URL` | `https://b-api.staging.openeduhub.net/api/v1/llm` | Basis-URL |
| **GPT-5-Tuning** | `LLM_VERBOSITY` | `medium` | `low`/`medium`/`high` |
| | `LLM_REASONING_EFFORT` | `low` | `none`/`low`/`medium`/`high`/`xhigh` |
| **Embedding-Override** | `EMBED_DIM` | auto-lookup | Escape-Hatch für exotische Modelle |
| **Speech** | `STT_MODEL` | `gpt-4o-mini-transcribe` | Speech-to-Text (Fallbacks `gpt-4o-transcribe`, `whisper-1`) |
| | `TTS_MODEL` | `tts-1` | Text-to-Speech (`tts-1-hd` für Qualität) |
| **MCP** | `MCP_SERVER_URL` | `https://wlo-mcp-server.vercel.app/mcp` | MCP-Server (Wissensquelle) |
| **RAG** | `RAG_TOP_K` | `15` | Pre-Fetch Top-K |
| | `RAG_MIN_SCORE` | `0.30` | Relevanz-Mindestwert |
| | `RAG_MAX_CHARS_PER_AREA` | `3000` | Char-Cap pro Wissensbereich (`0`=unbegrenzt) |
| **Evaluation** | `EVAL_CHAT_URL` | `http://localhost:8000/api/chat` | Ziel-Endpoint für simulierte Chat-Calls im Eval |
| | `EVAL_SIMULATOR_MODEL` | `gpt-4o-mini` | Modell für User-Simulator + Szenario-Generator |
| | `EVAL_JUDGE_MODEL` | `gpt-4o-mini` | Modell für LLM-as-Judge |
| **Datenbank** | `DATABASE_PATH` | `badboerdi.db` | SQLite-Pfad |
| **Security** | `STUDIO_API_KEY` | _leer_ | Schützt Admin-Routen |
| | `CORS_ORIGINS` | `*` | CORS-Whitelist |
| | `LOG_LEVEL` | `INFO` | Log-Level |

Vollständiges Beispiel unter [`backend/.env.example`](backend/.env.example).

#### Einschränkungen bei B-API-Providern

Die B-API stellt nur die OpenAI-kompatiblen `chat/completions`- und `embeddings`-Endpoints bereit. Folgende Funktionen sind daher **nur bei `LLM_PROVIDER=openai` verfügbar** und werden bei den beiden B-API-Providern automatisch deaktiviert oder schlagen fehl:

| Funktion | Verhalten bei B-API | Auswirkung |
|----------|---------------------|------------|
| **Sprach-Eingabe** (`POST /api/speech/transcribe`, OpenAI STT `gpt-4o-mini-transcribe`, Fallback `whisper-1`) | Endpoint existiert nicht — fällt nur, wenn `OPENAI_API_KEY` zusätzlich gesetzt ist; sonst HTTP 500. | Mikrofon-Button im Widget funktioniert nicht. |
| **Text-to-Speech** (`POST /api/speech/synthesize`, OpenAI TTS) | Wie oben — braucht `OPENAI_API_KEY` als Fallback. | Vorlese-Funktion deaktiviert. |
| **Stage 2 Moderation** (`omni-moderation-latest`) | Wird übersprungen (`is_openai_native()`-Gate). | Keine OpenAI-Kategorien im `safety.categories`-Debug-Feld. Regex-Stage (Stage 1) **und** Legal-Classifier (Stage 3) bleiben voll aktiv — die Sicherheits-Pipeline ist also weiter wirksam, nur etwas weniger fein granuliert. |
| **AcademicCloud-Embeddings für RAG** | `e5-mistral-7b-instruct` hat eine andere Vektor-Dimension als `text-embedding-3-small`. | **Bestehende RAG-Vektoren werden inkompatibel.** Nach einem Provider-Wechsel müssen alle Dokumente per `POST /api/rag/reindex` (oder über das Studio-RAG-Panel) neu eingebettet werden. Im Mischbetrieb gibt es sonst keine Treffer. |
| **JSON-Mode** (`response_format={"type":"json_object"}`) für Legal-Classifier | Wird vom AcademicCloud-Backend nicht garantiert unterstützt. | Bei `b-api-academiccloud` kann der Legal-Classifier gelegentlich nicht-JSON liefern und fällt dann auf `risk=0` zurück (bestehender Fehler-Fallback in `safety_service.py`). |
| **Tool-Calls / Function-Calling** | Bei OpenAI-Modellen über B-API voll unterstützt. Bei AcademicCloud-Modellen modellabhängig (Llama-3.1-Instruct & Qwen können es, kleinere Modelle ggf. nicht). | Wenn das Modell keine Tool-Calls beherrscht, schlägt `classify_input` fehl → Klassifikation fällt auf Defaults zurück, Pattern-Auswahl wird ungenauer. |

**Empfehlung:** Für Produktion mit voller Feature-Parität `LLM_PROVIDER=openai` (oder `b-api-openai`) verwenden. `b-api-academiccloud` ist ideal für datenschutz-sensitive Szenarien ohne Sprach-/TTS-Bedarf — vor dem Umschalten den RAG-Index neu aufbauen.



### Backup, Snapshots & Werkseinstellungen

Das System kennt **drei Sicherungs-Ebenen**, die alle den vollständigen `chatbots/wlo/v1`-Tree
(58 YAML/MD-Dateien über 13 Layer-Ordner: Patterns, Personas, Intents, States, Signals,
Canvas-Formate, Routing-Rules, Privacy, …) und optional die SQLite-DB (Sessions, Memory,
RAG-Embeddings, Quality- und Eval-Logs) umfassen:

| Ebene | Pfad | Zweck | Endpoints |
|-------|------|-------|-----------|
| **Download/Upload** | _Klient-seitig_ | Adhoc-Backup als ZIP herunter- oder hochladen — gut für Migrationen oder Off-Site-Sicherung. | `GET /api/config/backup?include_db=…`<br>`POST /api/config/restore?wipe=…&include_db=…` |
| **User-Snapshots** | `backend/snapshots/snap-*.zip` | Server-seitig gespeichert, beliebig viele, einzeln zurückspielbar. Ideal für vor-/nach-Iterations-Rollbacks ohne Up-/Download-Roundtrip. | `POST /api/config/snapshots?label=…&include_db=…`<br>`GET /api/config/snapshots`<br>`POST /api/config/snapshots/{id}/restore`<br>`DELETE /api/config/snapshots/{id}` |
| **Werkseinstellung** | `backend/knowledge/factory-snapshot.zip` | Genau eine pro Installation. Wird auf einer **frischen Installation mit leerer DB automatisch entpackt** — Neuer User braucht keine Setup-Schritte. | `GET /api/config/factory`<br>`POST /api/config/factory/save[?from_snapshot=…]`<br>`POST /api/config/factory/restore?wipe=…&include_db=…`<br>`POST /api/config/factory/upload` |

**Wichtig**: Wer einen User-Snapshot mit `include_db=false` als Werkseinstellung promotet,
hat anschließend eine Factory **ohne DB**. Bei einem späteren „Werkseinstellungen wiederherstellen"
werden dann _nur_ die Configs überschrieben, die DB bleibt unverändert. Für eine vollständige
Setup-Wiederherstellung muss der Quell-Snapshot mit `include_db=true` erstellt sein.

Im Studio sind alle drei Ebenen über das **📦-Symbol** im Header zugänglich (Snapshot anlegen,
Liste browsen, „Als Factory" promoten, „Werkseinstellungen zurücksetzen"). Details in
[`backend/README.md`](backend/README.md) und [`studio/README.md`](studio/README.md).

---

## 6. Docker-Deployment

Die drei Komponenten (Backend, Studio, Chatbot) haben je einen Dockerfile, die zentrale
`docker-compose.yml` orchestriert sie plus optionalen Watchtower für Auto-Updates.

### Start

```bash
cp .env.example .env           # API-Keys + optionale Overrides eintragen
docker compose up --build      # erster Build ca. 3-5 Min, danach Cache-Hits
```

Alle in Abschnitt 5 gelisteten Env-Variablen werden per `docker-compose.yml` durchgereicht.
`.env` im Repo-Root wird automatisch gelesen.

### Multi-Stage Backend-Build

Der Backend-Dockerfile nutzt **zwei Stages**, damit das finale Runtime-Image schlank bleibt:

| Stage | Inhalt | Bleibt im Final-Image? |
|-------|--------|------------------------|
| `reranker-builder` | python + torch + optimum + sentence-transformers → exportiert den RAG-Reranker zu ONNX int8 (135 MB) | ❌ nein |
| `base` (runtime) | python-slim + `onnxruntime` + `transformers` + App + gebackenes Modell | ✅ |

Effekt: das Runtime-Image enthält **kein torch**, kein sentence-transformers. Der
`COPY --from=reranker-builder /build/models ./models` übernimmt nur die ~135 MB ONNX-Artefakte.
BuildKit-Cache-Mount (`HF_HOME=/hf-cache`) hält das HuggingFace-Modell über Rebuilds.

### GitHub Actions

`.github/workflows/docker-publish.yml` baut alle drei Images für `linux/amd64` + `linux/arm64`
und pusht zu Docker Hub (ausgelöst bei push auf `main`/`master` oder `v*.*.*`-Tags). Secrets:
`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`. Der arm64-Build läuft unter QEMU-Emulation — Stage 1
wird dadurch ~10× langsamer (einmalig), sobald sie aus dem GHA-Layer-Cache gezogen wird
(bei unverändertem `requirements-setup.txt`), spielt das keine Rolle mehr.

### Production-Hinweise

- Volume `backend_data:/data` persistiert die SQLite-DB über Container-Restarts hinweg.
- Die Factory-Snapshot-Logik (`backend/knowledge/factory-snapshot.zip`) wird bei leerem
  Volume automatisch beim ersten Start eingespielt. Siehe `backend/knowledge/README.md`.
- Der Reranker wird zum Build-Zeitpunkt ins Image gebacken, **nicht beim Start heruntergeladen** —
  Air-Gapped-Deployments funktionieren nach Registry-Pull ohne weitere Netzwerkzugriffe.

---

## 7. Evaluation — automatisierte Persona-Dialog-Tests

Das Studio hat einen **Evaluation-Tab (🧪)**, der Gesprächs-Qualität systematisch und
reproduzierbar misst — ohne dass man von Hand testen muss.

### Was es macht

- **Lädt alle Personas und Intents** dynamisch aus der aktiven Chatbot-Config (`04-personas/`,
  `04-intents/intents.yaml`) — läuft also unverändert auch nach Konfig-Änderungen oder auf
  anderen Chatbot-Konfigs.
- **Generiert realistische Eröffnungsnachrichten** pro (Persona × Intent)-Kombination via LLM.
- **Zwei Test-Modi:**
  - *Szenarien* — 1 Turn pro Kombination, schnell, gut für Regression-Checks
  - *Dialoge* — Multi-Turn-Konversationen mit einem LLM-Nutzer-Simulator (3–10 Turns)
  - *Beides* — sequentiell hintereinander
- **LLM-as-Judge** bewertet jeden Bot-Turn auf 5 Dimensionen (0–2 Punkte): Intent-Fit,
  Persona-Tonalität, Pattern-Passung, Safety, Info-Qualität. Gesamtscore als
  Durchschnitt ∈ [0, 1].
- **Matrix-Heatmap** Persona × Intent mit Durchschnittsscores + **Pattern-Häufigkeit** pro
  Run und unabhängig über alle Sessions (aus `quality_logs`).
- **Volle Transkripte** pro Konversation inkl. gewähltes Pattern, aufgerufene Tools, Safety-
  Status, Judge-Scores pro Dimension + Freitext-Notiz.

### Architektur

- Alle simulierten Turns gehen durch den **echten `/api/chat`-Endpoint** — gleiche Safety-
  Pipeline, Pattern-Engine, RAG wie im Produktionsbetrieb.
- **Keine neue Parallel-DB**: jeder Turn landet automatisch in `quality_logs` wie
  Produktions-Traffic. Analytics funktionieren daher auch ohne aktiven Eval-Run.
- **Eval-Runs laufen im Hintergrund** (`asyncio.create_task`), Start-Endpoint kehrt sofort
  zurück. Studio pollt alle 3 s für Status-Updates.
- **Cost-Estimate vor dem Start** mit Unschärfe-Band (min/erwartet/max) — typisch
  $0.05–0.50 pro Run, je nach Größe.
- **Generisch**: keine WLO-spezifischen Hardcodings. Funktioniert für jede Chatbot-Config
  unter `chatbots/<name>/v1/`.

### Was es bewusst NICHT macht

- **Keine automatischen Config-Patches** — der Judge schreibt Notizen, kein Meta-LLM ändert
  YAML oder Pattern-Definitionen. Alle Anpassungen bleiben manuell.
- **Keine CI-Pass/Fail-Gates** basierend auf LLM-Scores — zu hohes Rauschen, zu großes Risiko
  für false-precision-Optimierung.
- **Keine Gesamt-Gesundheits-Zahl** — nur `avg_score` pro Run als Signal, keine Ampel über
  alles. Metriken sind Kartographie, keine Navigation.

### API

```bash
# Aktuelle Personas + Intents
GET /api/eval/config

# Vorschätzung (gleiche Parameter wie Start)
POST /api/eval/estimate   { "mode": "both", "persona_ids": [...], "intent_ids": [...], ... }

# Run starten (Background-Task)
POST /api/eval/runs       { "mode": "scenarios|conversations|both", ... }

# Runs listen / Detail / Löschen
GET  /api/eval/runs
GET  /api/eval/runs/{id}
DELETE /api/eval/runs/{id}

# Pattern-Usage-Analytics (wirkt auch ohne Eval-Runs)
GET  /api/eval/analytics/pattern-usage?eval_only=false
```

Alle Endpoints sind Studio-geschützt (Header `X-Studio-Key`, wenn `STUDIO_API_KEY` gesetzt).

### Skalierung

Ein voller Sweep (alle 9 Personas × 14 Intents × 2 Szenarien) erzeugt 252 Turns und kostet
typisch ~$1.30 bei `gpt-4o-mini` als Judge und `gpt-5.4-mini` als Chat-Model. Der volle
Sweep inkl. 3-Turn-Dialogen (630 Turns) liegt bei ~$4. Laufzeit ~5–15 Minuten, je nach
Tool-Call- und RAG-Retrieval-Dauer.

---

## 8. Komponenten-READMEs

* **[backend/README.md](backend/README.md)** — API-Routen, Safety-Pipeline, Pattern-Engine,
  Konfigurationsformat, Rate-Limits, Sessions, MCP & RAG.
* **[frontend/README.md](frontend/README.md)** — Chat-UI, Web-Component-Bauweise, Widget-
  Properties, Embedding-Beispiele, Cross-Page-Session-Continuity.
* **[studio/README.md](studio/README.md)** — Layer-Editoren, welcher Editor welche Datei in
  `chatbots/wlo/v1/` schreibt, Empfohlene Workflows.

---

## 9. Lizenz & Mitwirkende

Internes Projekt — siehe `LICENSE` (sofern vorhanden) bzw. den Rahmenvertrag mit
WirLernenOnline.
