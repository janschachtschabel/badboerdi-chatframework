# BadBoerdi — WLO Chatbot Plattform

> **Stand 2026-05-23 (Welle E):** Canvas-Pane entfernt — Material, Lernpfade und
> KI-Inhalte werden direkt als gerahmte Inline-Box im Chat-Verlauf gerendert.
> Lotsen-Modus ist Default an (Repo-Links statt externer URLs). Anzeige-Steuerung
> liegt zentral in der Studio-pflegbaren [`display-rules.yaml`](backend/chatbots/wlo/v1/01-base/display-rules.yaml) —
> sichtbar im Studio unter **🎨 Anzeige**. Mehrere Widget-Embed-Attribute
> sind deprecated (Details in [`docs/05-widget-javascript-api.md`](docs/05-widget-javascript-api.md)).

BadBoerdi ist eine modulare Chatbot-Plattform für [WirLernenOnline](https://wirlernenonline.de).
Das System ist über das **Schema-Tripel-Modell** (22 Elemente · 31 Tripel · **6 Prompt-Schichten** · 7
Verarbeitungsphasen) konfiguriert und besteht aus drei Komponenten:

| Komponente | Stack | Port | Zweck |
|------------|-------|------|-------|
| **`backend/`** | FastAPI · Python 3.11 · OpenAI · MCP | `8000` | Chat-API, LLM-Hint-Pattern-Routing, Safety-Pipeline, RAG, Session-Persistenz, Widget-Auslieferung |
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
| **1** | **Identität & Schutz** | `chatbots/wlo/v1/01-base/base-persona.md`, `guardrails.md`, `safety-config.yaml`, `policy.yaml`, `quality-log-config.yaml`, `device-config.yaml` | **Immer** — bei jedem Turn als erstes in den Prompt | Wer ist BOERDi, was darf er nie tun (Guardrails als _letzter_ Block, nicht überschreibbar), Sicherheits-Preset (off/basic/standard/strict/paranoid), Policy-Regeln (konditionale Tool-Sperren/Disclaimer via `policy_service.py`), Quality-Logging, Geräte-Heuristiken |
| **2** | **Domain & Regeln** | `chatbots/wlo/v1/02-domain/domain-rules.md`, `wlo-plattform-wissen.md` | **Immer** — direkt nach Schicht 1 | Plattform-Wissen (WLO-Sammlungen, Lizenzen, Zielgruppen), Dauerregeln |
| **3** | **Patterns** | `chatbots/wlo/v1/03-patterns/M*.md` (**16 Patterns**, M01–M16) | **Nach Bedarf** — das vom LLM-Hint gewählte Pattern (`pattern_engine.py → select_pattern()`, siehe 2.4) — keine Score-Engine, keine Routing-Rules mehr | Aktives Konversations-Muster mit `core_rule`, `tone`, `length`, `max_items`, `tools`, Modulationen wie `skip_intro`, `one_option`, `add_sources`, `degradation` |
| **4** | **Dimensionen** | Klassifikator-Output aus `llm_service.py → classify_input()` + `04-*/*.yaml` (Personas, Intents, States, Entities, Signals) | **Pro Turn neu** | Persona-ID, Intent-ID + Confidence, Signals, Entities, Slots, next_state — strukturierte Werte für genau diesen Turn |
| **5** | **Material-Formate** | `chatbots/wlo/v1/05-canvas/*.yaml` (material-types, type-aliases, create-triggers, edit-triggers, persona-priorities) | **Nur bei KI-Generierung (Intent I05/I06)** — liefert die Struktur-Vorgabe des Material-Typs | Material-Typen (didaktisch + analytisch), Alias-Mapping, Create-/Edit-Trigger-Phrasen, Persona-abhängige Reihenfolge |
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
    material_structure,  # Layer 5: KI-Material-Struktur (nur bei I05/I06)
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

### 2.4 Pattern-Auswahl (LLM-Hint)

Das Pattern bestimmt der **LLM-Klassifikator** (`pattern_id_hint`). Es gibt **keine** Score-/Gate-Engine und **keine** Routing-Rules mehr (in Welle E v4 / Sprint K datenbasiert als redundant entfernt — das `06-rules/`-Verzeichnis ist weg). `select_pattern()` (`pattern_engine.py`) priorisiert: **Safety-erzwungenes Pattern → LLM-Hint → Fallback (`M15`/`M03`)**. Nach der Generierung wird das Label ggf. an die real ausgeführte Aktion angeglichen (`M09` Lernpfad / `M10` KI-Material / `M03` Slot-Klärung), damit Telemetrie + Box-Routing stimmen.

### 2.5 KI-Material-Generierung (M10 / M11)

Auf Erstell-Anfragen (Intent `I05`) generiert der Bot strukturiertes Material (Arbeitsblatt, Quiz, Factsheet, Lernpfad, …) und zeigt es als **InlineDocument-Box** direkt im Chat-Verlauf — **kein** separates Canvas-Pane mehr (in Welle E entfernt). Nachbearbeitung (Intent `I06`, Pattern `M11`) verfeinert die zuletzt erzeugte Box (kürzer, Lösungen ergänzen, …). Die Material-Typen + Trigger/Aliase liegen in `chatbots/wlo/v1/05-canvas/` (Studio-Tab „Material-Formate“); der Verzeichnisname ist historisch.

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

### 2.7 Webseiten-Lotsen-Modus

Optionales Feature: wenn das Widget auf einer der konfigurierten WLO-Domains läuft, kann der Bot
den User direkt zur passenden WLO-Seite navigieren — im **selben Browser-Tab**, statt einen
neuen aufzumachen. Das ist nützlich, wenn der Widget-User auf einer Übersichtsseite sitzt und
in eine spezifische Themenseite oder ein Fachportal wechseln möchte.

**Drei Trigger pro Antwort-Turn (in dieser Reihenfolge):**

1. **Card-Buttons** — jede ausgegebene Material-/Sammlungs-/Themenseiten-Card bekommt einen
   dunkelblauen 🧭 „Bring mich hin"-Button neben den bestehenden Aktionen, sofern die Karte auf
   eine allow-listed Domain zeigt. Klick navigiert im selben Tab.
2. **Lotsen-Quick-Reply** — der Bot kann unter seiner Antwort einen einzelnen Quick-Reply-
   Button setzen, der zu einer thematisch passenden Plattform-Seite führt
   (z.B. „🧭 Mitmachen-Seite", „🧭 Themenseite Klimawandel"). Trigger ist eine Mischung aus
   Message-Regex (`mitmachen` → `/mitmachen`), LLM-Eigenproduktion (über das `respond_to_user`-
   Tool-Schema) und einem RAG-Area-Fallback (wenn `query_knowledge(area="WissenLebtOnline")`
   aufgerufen wurde, kommt `https://wissenlebtonline.de/` als Vorschlag).
3. **Banner-Dialog** — wenn der Bot ein eindeutiges Navigationsziel hat, kann er via
   `page_action: navigate` einen Banner über dem Chat-Body einblenden („Soll ich dich zu X
   bringen?" mit „Bring mich hin" / „Hier bleiben"). Banner ist orange-frei (Header-Dunkelblau).

**Zustands-Steuerung — User-Toggle:**

Der Modus wird im Widget-Header über einen 🧭-Toggle ein/aus geschaltet. Sichtbar ist der Toggle
**nur** auf allow-listed Hosts (Default-Liste in `chatbots/wlo/v1/01-base/guide-mode.yaml`):
`wirlernenonline.de`, `*.openeduhub.net`, `wissenlebtonline.de`. Auf Drittseiten (z.B.
`bildungsserver.de`) erscheint der Toggle nicht, der Lotsen-Modus ist implicit aus.

User-Wahl wird in `localStorage["boerdi.guide_mode"]` persistiert. Default ist **OFF** —
Tab-Wechsel ist eine Verhaltensänderung gegenüber „neuer Tab", deshalb opt-in. Beim Klick auf
den Toggle wechselt der State sofort, das Backend respektiert ihn beim nächsten Chat-Turn.

**Cross-Domain-Bridge:**

Klickt der User auf einen 🧭-Button und das Ziel ist eine **andere Origin** (z.B.
`wirlernenonline.de` → `redaktion.openeduhub.net`), hängt das Widget automatisch zwei
URL-Parameter an:

- `?bsid=<session-id>` — Session-Brücke (existiert seit längerem, gilt allgemein für Cross-TLD-
  Links). Bei Aufruf der Zielseite liest das dortige Widget die ID, übernimmt die Session und
  entfernt den Parameter wieder aus der URL.
- `?bgm=<0|1>` — Lotsen-Toggle-State. Auf der Zielseite wird der Wert gelesen, in
  `localStorage` übernommen und der URL-Parameter entfernt. Damit überlebt der Toggle den
  Domain-Wechsel.

Beide Mechanismen funktionieren nur, wenn der Embed auf der Zielseite die Sender-Domain
zur `trusted-domains`-Whitelist hinzugefügt hat — siehe Custom-Element-Attribute unten.

**Konfiguration** in `chatbots/wlo/v1/01-base/guide-mode.yaml`:

```yaml
guide_mode:
  default_enabled: false              # Toggle-Default. Wird nur genutzt, wenn keine
                                      # localStorage-Wahl des Users vorliegt.
  allowed_hosts:                      # Hosts, auf denen der Toggle erscheint UND zu
    - wirlernenonline.de              # denen der Bot navigieren darf. ``*.example.com``
    - "*.wirlernenonline.de"          # matcht ALLE Subdomains.
    - openeduhub.net
    - "*.openeduhub.net"
    - wissenlebtonline.de
    - "*.wissenlebtonline.de"
  url_fields_priority:                # Welche Card-URL-Felder als Guide-Ziel zulässig
    - topic_page_url                  # sind, in Reihenfolge der Bevorzugung.
    - wlo_url
    - url
    - content_url
    - preview_url
  max_guide_targets_per_turn: 0       # Max Anzahl Cards pro Antwort mit Bring-mich-hin-
                                      # Button. 0 = unbegrenzt (alle eligible Cards).
```

**Pattern-spezifische Quick-Reply-Trigger** (deterministisch, in
`backend/app/services/guide_qr_injector.py`): das Modul mappt User-Frage-Regex und RAG-Area
auf konkrete WLO-URLs. Liste pflegen wenn neue Plattform-Seiten dazukommen — derzeit:
Themenseiten-Beispiel, Fachportal-Übersicht, Mitmachen-Seite, Über-WLO, Hintergrund-WLO,
OER-Erklärung, Edu-Sharing-Verein, WissenLebtOnline-Webseite, Metaventis, WLO-Startseite.

**Backend-Endpoint** für Frontend-Init: `GET /api/config/guide-mode` liefert das parsete
yaml-Subset (allowed_hosts + default_enabled + max_guide_targets_per_turn). Das Widget
fetcht es einmal beim Init und cached intern.

---

### 2.8 Webseiten-Tour (geführte Besucherführung)

Optionales Onboarding als **Konversions-Funnel**: Der Besucher wird zielgerichtet von der
Selbstzuordnung bis zur **Anfrage/Kontakt auf `/mitmachen/`** geführt. Voller Weg ab Startseite:
**Startseite → Zielgruppenseite → Bildungsinhalte → passende Angebote → Anfrage (Mitmachen)**.

**Einstiegspunkte (Flow-Modell `flows:` in der YAML):** Die Tour kann MITTEN im Funnel starten — `detect_entry(page)` prüft beim Start die aktuelle Seite: Zielgruppenseite → direkt zu den Lösungen (**B1**), Produkt-/Angebotsseite → Lösungen mit Gruppe per Rückwärts-Lookup (**C1**), `/mitmachen/` → direkt ans Ziel (**D1/D2**, nur Prozesssicherheit), sonst voller Funnel ab Startseite (**A1–A3**).
Gestartet über den festen Startbutton **„Web-Tour starten"** (ersetzt den Vorschlag
„Erstell mir ein neues Material"; Material-Erstellung bleibt per Texteingabe erreichbar).

**Kern — Ankunfts-Erkennung:** Nach jedem „Bring mich hin"-Button lädt die WP-Seite neu. Die
Session überlebt das (localStorage / Cookie / `?bsid=`), und das Widget feuert beim Page-Load
**einen unsichtbaren „Tick"** mit der aktuellen Seite. Erkennt der Bot die erwartete Zielseite,
liefert er automatisch den nächsten Text + Button. Falsche Seite → sanfter Hinweis; Ankunft auf
`/mitmachen/` → Tour-Ende.

**Architektur — Domänwissen + Handler, KEIN Pattern:**

- **Inhalt** (Begrüßung, Schritt-Texte, Einstiegs-Texte, das dokumentierte `flows:`-Modell, Ziel-URLs,
  die 7 Besucher-Gruppen, Gruppe→Angebot-Mapping,
  Kontakt-Links) liegt in `chatbots/wlo/v1/01-base/website-tour.yaml` — **Studio-pflegbar** unter
  **Domain-Wissen → „Webseiten-Tour"**, ohne Deploy änderbar.
- **Verhalten** (State Machine, Ankunfts-Logik, Einstiegspunkt-Erkennung `detect_entry`, Gruppen-Matching) ist deterministischer Code in
  `app/services/tour_service.py` + `_handle_tour(...)` in `app/routers/chat.py`. Bewusst **kein**
  Pattern: Patterns sind Einzelturn-LLM-Routing-Einheiten — eine mehrstufige, seiten-stateful
  Führung mit fixen Texten muss verlässlich/deterministisch sein.
- Signal-Feld: `environment.tour_action` ∈ `start` | `tick`. Per-Session-State in
  `sessions.tour_state` (SQLite). Antwort-Echo: `ChatResponse.tour = {active, step, group}`.

**Deployment-Voraussetzungen:**

1. Widget **site-weit** auf den Tour-Zielseiten eingebettet — sonst feuert auf der Zielseite kein
   Tick und die Ankunfts-Erkennung greift nicht.
2. `persist-session="true"` (bzw. Cookie / `?bsid=`), damit die Tour den WP-Full-Page-Reload
   überlebt.
3. `base_host` in `website-tour.yaml` auf den laufenden Host setzen (Test: `wp-test…`,
   Prod: `https://wirlernenonline.de`).

---

## 3. Repo-Layout

```
badboerdi/
├── backend/             # FastAPI-Service
│   ├── app/
│   │   ├── routers/     # chat, sessions, safety, quality, config, rag, speech, widget
│   │   ├── services/    # llm, pattern_engine, safety, policy, rag, canvas, page_context, …
│   │   └── main.py
│   ├── chatbots/wlo/v1/ # ↳ Konfigurations-Bundle (6 Prompt-Schichten)
│   │   ├── 01-base/     # Layer 1: Persona, Guardrails, Safety, Device, Privacy
│   │   ├── 02-domain/   # Layer 2: Domain-Wissen, Policy
│   │   ├── 03-patterns/ # Layer 3: 16 Patterns (M01–M16)
│   │   ├── 04-*/        # Layer 4: 6 Personas (Tonalitäts-Frontmatter), 8 Intents, 4 States, Entities, Signals
│   │   ├── 05-canvas/   # Layer 5: Material-Typen, Aliase, Create-/Edit-Trigger, Persona-Priorität
│   │   └── 05-knowledge/# Layer 6: RAG- und MCP-Konfiguration
│   ├── snapshots/       # User-Snapshots (server-seitig, frei anlegbar/restorierbar)
│   ├── knowledge/       # factory-snapshot.zip (Werkseinstellung) + RAG-Quelldokumente
│   └── run.py
├── frontend/            # Angular-App + Web-Component-Widget
│   ├── src/app/chat/    # Chat-UI (Standalone-Component)
│   ├── src/app/widget/
│   │   ├── widget.component.ts        # <boerdi-chat>-Wrapper (Custom Element)
│   │   └── page-context-detector.ts   # URL+DOM-Heuristik für WLO-Themenseiten/Sammlungen/Inhaltsseiten
│   ├── src/widget-main.ts  # Bootstrap via @angular/elements
│   └── angular.json     # build-widget Target
├── studio/              # Next.js-Studio (Architektur-Editoren + Status-Dashboard)
│   └── src/components/  # HomeOverview (Dashboard), CanvasFormatsEditor, RoutingRulesView, …
└── scripts/
    ├── build-widget.sh                  # Standardpfad: Mono-Repo, Backend liest frontend/dist direkt
    ├── build-widget.ps1
    ├── sync-widget-to-backend.sh        # Sonderfall: Backend isoliert deployt → Kopie in backend/widget_dist/
    └── sync-widget-to-backend.ps1
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

> **Stand 2026-06-10:** Es gibt keine Feature-Umschaltung pro Embed mehr — `ai-content-enabled` wurde entfernt, KI-generierte Inhalte sind immer aktiv.
> Die früheren `cards-`/`canvas-`/`grouping-`/`quick-replies-`/`guide-mode-`-Attribute wurden
> entfernt; Treffer erscheinen als Gruppen-Boxen, der Lotsen-Modus ist dauerhaft aktiv.
> - `trusted-domains` ist jetzt **additiv** zur Backend-Allow-Liste
>   (`guide-mode.yaml` / Env `GUIDE_TRUSTED_DOMAINS`) — Stored-XSS auf der Host-Seite
>   kann die Liste nicht mehr aushebeln. Für Default-WLO-Domains kann das HTML-Attribut
>   leer bleiben.
> - `primary-color` kann durch CSS-Variable `boerdi-chat { --boerdi-primary: red; }`
>   überschrieben werden (wenn das Attribut nicht gesetzt ist).
> - Public JS-API: `el.openChatbot()` / `closeChatbot()` / `toggleChatbot()` /
>   `isChatbotOpen()` — siehe Abschnitt unten. `initial-state` ist jetzt reaktiv.

| Attribut | Default | Wirkung |
|----------|---------|---------|
| `api-url` | _Pflicht_ | Backend-Basis-URL (z.B. `https://api.example.de`). Wird zu `…/api` normalisiert. |
| `position` | `bottom-right` | FAB-Position: `bottom-right` · `bottom-left` · `top-right` · `top-left` |
| `initial-state` | `collapsed` | `collapsed` (FAB) oder `expanded` (Panel offen) |
| `primary-color` | _leer_ (→ CSS-Default `#1c4587`) | Hauptfarbe (CSS-Hex). Alternativ per CSS-Variable überschreibbar: `boerdi-chat { --boerdi-primary: red; }`. Wenn das Attribut gesetzt ist, gewinnt es gegen die CSS-Regel (Inline-Style wins). |
| `greeting` | _leer_ | Eigene Begrüßungsnachricht beim ersten Öffnen |
| `persist-session` | `true` | Session-ID in `localStorage` halten — Verlauf bleibt über Page-Reload |
| `session-key` | `boerdi_session_id` | localStorage-Schlüssel |
| `session-cookie-domain` | _leer_ | Cross-Subdomain-Session-Cookie. Setzt parallel zu localStorage ein Cookie auf dieser Domain. Beispiel: `.wirlernenonline.de` verbindet `suche.wlo.de` ↔ `wp-test.wlo.de`. Leer = origin-isoliert. |
| `session-cookie-max-age` | `2592000` (30 Tage) | Cookie-Lifetime in Sekunden. Greift nur mit `session-cookie-domain`. |
| `trusted-domains` | _leer_ | **Zusätzlich** zur Backend-Allow-Liste (siehe `trusted_domains` in `guide-mode.yaml` bzw. `GUIDE_TRUSTED_DOMAINS` Env-Var) per HTML eintragbare Hostnames für Cross-TLD-Session/Toggle-Handoff. Beim Klick auf einen Link/Button zu einer dieser Domains hängt das Widget `?bsid=<sid>&bgm=<0\|1>` an. Backend-Liste hat Vorrang als Vertrauensanker; das Attribut darf nur **ergänzend** (additiv) wirken — eine Stored-XSS auf der Host-Seite kann die Backend-Liste also nicht aushebeln. Subdomain-Match automatisch (`.example.com` matcht alle Subs). `https://`/`http://`-Präfix und Trailing-Slashes werden toleriert. |
| `auto-context` | `true` | Seitenkontext (URL, Title) automatisch ans Backend senden |
| `page-context` | _leer_ | Zusätzlicher Kontext als JSON-String oder Objekt |
| `show-debug-button` | `true` | 🔍 Debug-Toggle im Header. `false` = Button ausgeblendet (für Produktiv-Embeddings) |
| `show-language-buttons` | `true` | 🔊 Text-to-Speech und 🎤 Mic-Aufnahme. `false` = beide Buttons aus (kein Sprach-Feature) |

> **Entfernt (2026-06-10):** `ai-content-enabled` existiert nicht mehr — KI-generierte Inhalte sind immer aktiv; ein noch gesendetes Attribut wird ignoriert.

> **Lotsen-Modus** wird **nicht** über ein Custom-Element-Attribut gesteuert, sondern
> komplett serverseitig via `chatbots/wlo/v1/01-base/guide-mode.yaml` (Allow-Liste,
> Default-Toggle-State) plus per-User-Toggle im Widget-Header — siehe
> [§ 2.7 Webseiten-Lotsen-Modus](#27-webseiten-lotsen-modus). Damit der Toggle-State
> Cross-Domain überlebt, muss der Embed `trusted-domains` und (für Subdomains)
> `session-cookie-domain` setzen.

```html
<!-- Minimal-Embed: Default für Standard-Seiten -->
<boerdi-chat
  api-url="https://api.example.de"
  primary-color="#1c4587">
</boerdi-chat>

<!-- Produktiv-Embedding ohne Debug, ohne Sprache -->
<boerdi-chat
  api-url="https://api.example.de"
  primary-color="#1c4587"
  show-debug-button="false"
  show-language-buttons="false">
</boerdi-chat>

<!-- WLO-Embed mit Cross-Subdomain + Cross-TLD-Session-Brücke
     (notwendig für funktionierenden Lotsen-Modus zwischen den Domains) -->
<boerdi-chat
  api-url="https://api.wlo.de"
  trusted-domains="wirlernenonline.de,openeduhub.net,wissenlebtonline.de"
  session-cookie-domain=".wirlernenonline.de">
</boerdi-chat>

<!-- Host bringt eigene Material-Erstellung mit: KI-Generierung aus
     (Treffer bleiben als kompakte Boxen) -->
<boerdi-chat
  api-url="https://api.example.de"
>
</boerdi-chat>
```

Im Studio dokumentiert unter **System → Info → Widget-Einbettung**.

### Public JavaScript-API auf dem Custom Element

Das `<boerdi-chat>`-Element exponiert vier Methoden, mit denen die einbettende Seite
das Panel programmatisch steuern kann — ohne Shadow-DOM-Tricks:

```js
const el = document.querySelector('boerdi-chat');
el.openChatbot();    // Chat-Panel öffnen
el.closeChatbot();   // Panel schließen (FAB sichtbar)
el.toggleChatbot();  // Toggle zwischen offen/zu
el.isChatbotOpen();  // → boolean
```

Methoden sind **idempotent**: zwei aufeinanderfolgende `openChatbot()`-Calls schaden nicht.
Vor Widget-Bootup (z.B. wenn die Host-Seite das Element vor dem Bundle-Load anlegt)
geben sie `undefined` zurück und werfen nichts.

Alternativ — und für Angular-Templates oft praktischer — über reaktive Attribut-Änderungen:

```js
// equivalent zu openChatbot():
el.setAttribute('initial-state', 'expanded');
// equivalent zu closeChatbot():
el.setAttribute('initial-state', 'collapsed');
```

In Angular per `[attr.initial-state]="state()"` direkt im Template binden — das Widget
reagiert via `ngOnChanges` auf jede Änderung.
Live-Demos: `/widget/` (Default), `/widget/inline` (kompakter Inline-Modus).

#### Embed-Inputs + Outputs/Events

Das Widget hat darüber hinaus eine **umfangreiche Embed-API**: HTML-
Attribute wie die
passive Lotsen-/Telemetrie-Emission (`emit-guide-suggestion`,
`emit-routing-debug`) und die Link-Interception
(`intercept-edu-sharing-links`) — plus vier globale CustomEvents
(`badboerdi:page-action`, `badboerdi:guide-suggestion`,
`badboerdi:routing-debug`, `badboerdi:query-meta`) und die
korrespondierenden Angular-Outputs (`(pageAction)`,
`(guideSuggestion)`, `(routingDebug)`, `(queryMeta)`, `(linkClicked)`).

Vollständige Referenz inkl. Payload-Schemas, Trigger-Bedingungen und
sieben Embed-Beispielen (Default / Themenseiten / Edu-Sharing-Sidebar /
WordPress-iframe-Routing / Minimal-Bubble / Vollausstattung mit
Telemetrie / Cross-Domain-Session-Sharing):

→ **[docs/05-widget-javascript-api.md](./docs/05-widget-javascript-api.md)**

---

## Doku-Wegweiser

| Doc | Inhalt |
|-----|--------|
| [docs/02-architektur.md](./docs/02-architektur.md) | Schichten, Phasen, Config-Dateibaum |
| [docs/03-elemente.md](./docs/03-elemente.md) | Alle Dimensionen/Elemente im Detail |
| [docs/04-deployment.md](./docs/04-deployment.md) | Docker/vServer-Setup, Prod-Checkliste |
| [docs/05-widget-javascript-api.md](./docs/05-widget-javascript-api.md) | Embed-Attribute, Events, Beispiele |
| [docs/06-request-pipeline.md](./docs/06-request-pipeline.md) | **Ablauf pro Turn** (was läuft wann/parallel, optionale Pfade wie Sprach-LLM), Skalierung, Lasttest |

Das Studio bringt unter **Auswertung → Lasttest** einen Skalierbarkeits-Selbsttest mit
(gemischte Abfragen mit steigender Parallelität, Latenz-/Fehler-Kurve, CPU-/RAM-Verlauf,
Fazit „stabil bis N gleichzeitige Nutzer"). Achtung: feuert echte LLM-Requests.

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

**Standard ist `openai`** — wenn `LLM_PROVIDER` nicht gesetzt ist, läuft das System mit den oben gezeigten Defaults. Modelle lassen sich jederzeit per `LLM_CHAT_MODEL` / `LLM_EMBED_MODEL` überschreiben. `OPENAI_BASE_URL` ist optional und erlaubt OpenAI-kompatible Gegenstellen (Azure OpenAI, LiteLLM-Proxy, LocalAI, Ollama-Shim). Die Basis-URL der B-API ist über `B_API_BASE_URL` (Default `https://b-api.prod.openeduhub.net/api/v1/llm`; Staging-Variante: `https://b-api.staging.openeduhub.net/api/v1/llm`) konfigurierbar.

**B-API-Setup mit OpenAI-Side-Channel:** Wer chat + embeddings über die B-API laufen lässt, aber zusätzlich einen `OPENAI_API_KEY` einträgt, bekommt automatisch Moderation, Whisper-STT und TTS direkt über `api.openai.com` — die B-API forwarded diese drei Endpoints nicht. Ohne OpenAI-Key werden sie still übersprungen (Regex-Safety-Floor bleibt aktiv).

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
| | `B_API_BASE_URL` | `https://b-api.prod.openeduhub.net/api/v1/llm` | Basis-URL der B-API. Staging-Variante: `https://b-api.staging.openeduhub.net/api/v1/llm` |
| **GPT-5-Tuning** | `LLM_VERBOSITY` | `medium` | `low`/`medium`/`high` |
| | `LLM_REASONING_EFFORT` | `low` | `none`/`low`/`medium`/`high`/`xhigh` |
| **Embedding-Override** | `EMBED_DIM` | auto-lookup | Escape-Hatch für exotische Modelle |
| **Speech** | `STT_MODEL` | `gpt-4o-mini-transcribe` | Speech-to-Text (Fallbacks `gpt-4o-transcribe`, `whisper-1`) |
| | `TTS_MODEL` | `tts-1` | Text-to-Speech (`tts-1-hd` für Qualität) |
| **MCP** | `MCP_SERVER_URL` | `https://wlo-mcp-server.vercel.app/mcp` | Primary-MCP-Server (überschreibt zur Laufzeit die `url` des Eintrags `id: wlo-mcp` in `chatbots/wlo/v1/05-knowledge/mcp-servers.yaml`). Weitere MCP-Server lassen sich im Studio anhängen — Sessions laufen pro Server-URL getrennt. |
| **Lotsen-Modus** | `GUIDE_TRUSTED_DOMAINS` | _(aus `guide-mode.yaml`)_ | Komma-/Whitespace-getrennte Liste vertrauenswürdiger Hostnames für Cross-TLD-Session-Brücke (`?bsid=…&bgm=…`). Überschreibt die `trusted_domains`-Liste aus der YAML komplett. Frontend mergt diese Backend-Liste mit dem optionalen HTML-Attribut `trusted-domains` (Backend hat Vorrang als Vertrauensanker, HTML kann nur additiv ergänzen). Wildcards `*.example.com` matchen alle Subdomains. <br>**Default-Abdeckung** (aus `guide-mode.yaml`): `wirlernenonline.de` + `*.wirlernenonline.de` (deckt `wp-test.wirlernenonline.de`), `openeduhub.net` + `*.openeduhub.net` (deckt `repository.staging.openeduhub.net`), `openeduhub.de` + `*.openeduhub.de` (deckt `wordpress.openeduhub.de`), `wissenlebtonline.de` + `*.wissenlebtonline.de`, `localhost`/`127.0.0.1` (Ports werden beim Matching gestrippt, also auch `localhost:4200`). |
| **Text-Extraction** | `TEXT_EXTRACTION_URL` | `https://text-extraction.prod.openeduhub.net` | **Base-URL** des OEH-Volltext-Service. `/from-url` wird intern angehängt, Trailing-Slash + Legacy-Voll-URL werden toleriert. Staging-Variante: `https://text-extraction.staging.openeduhub.net` |
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
| | `RAG_RERANKER_ENABLED` | `true` | Cross-Encoder-Reranker; auf ≤ 2-GB-vServern `false` (Embedding-only) |
| **Repo** | `REPO_BASE_URL` | _Code-Default_ | edu-sharing-Repo-Basis für `wlo_url`/`preview_url` (muss zur `MCP_SERVER_URL` passen) |
| **Karten-Auswahl** | `CARD_CE_TOP_N` | `3` | Max. Karten je Box |
| | `CARD_CE_GATE_COLLECTION` | `0.0` | CE-Score-Schwelle Sammlungen/Themenseiten (höher = strenger) |
| | `CARD_CE_GATE_CONTENT` | `-1.5` | CE-Score-Schwelle Einzelinhalte |
| | `CHAT_DISABLE_SELECT_TOP_CARDS` | _aus_ | `1` überspringt die LLM-Karten-Kuratierung |

Vollständiges Beispiel (inkl. `SPEECH_FORCE_ENABLE`, `BOERDI_MAX_INGEST_MB`, `CHAT_INLINE_QUICK_REPLIES`, `CARD_PIPELINE_V2`) unter [`backend/.env.example`](backend/.env.example).

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
(YAML/MD-Dateien über die Layer-Ordner: Patterns, Personas, Intents, States, Signals,
Material-Formate, Privacy, …) und optional die SQLite-DB (Sessions, Memory,
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

Ein voller Sweep (alle 6 Personas × 8 Intents × 2 Szenarien) erzeugt 96 Turns und kostet
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
