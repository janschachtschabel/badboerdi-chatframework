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
| **3** | **Patterns** | `chatbots/wlo/v1/03-patterns/pat-*.md` (23 Patterns nach Welle B/C Konsolidierung) | **Nach Bedarf** — nur das _eine_ Pattern, das der Pattern-Engine-Selector gewinnt (`pattern_engine.py → select_pattern()`), ggf. korrigiert durch die Routing-Rules-Engine (siehe 2.4) | Aktives Konversations-Muster mit `core_rule`, `tone`, `length`, `max_items`, `tools`, Modulationen wie `skip_intro`, `one_option`, `add_sources`, `degradation` |
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
      - intent:  { in: ["INT-W-03", "INT-W-09"] }
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

## 3. Repo-Layout

```
badboerdi/
├── backend/             # FastAPI-Service
│   ├── app/
│   │   ├── routers/     # chat, sessions, safety, quality, config, rag, speech, widget
│   │   ├── services/    # llm, pattern_engine, safety, policy, rag, canvas, page_context, …
│   │   └── main.py
│   ├── chatbots/wlo/v1/ # ↳ Konfigurations-Bundle (6 Prompt-Schichten + Routing-Rules)
│   │   ├── 01-base/     # Layer 1: Persona, Guardrails, Safety, Device, Privacy
│   │   ├── 02-domain/   # Layer 2: Domain-Wissen, Policy
│   │   ├── 03-patterns/ # Layer 3: 23 Patterns (PAT-01…PAT-28 mit Lücken, PAT-CRISIS, PAT-REFUSE-THREAT)
│   │   ├── 04-*/        # Layer 4: 9 Personas (mit Tonalitäts-Modifier-Frontmatter), 13 Intents, 12 States, 5 Entities, 17 Signals, Contexts
│   │   ├── 05-canvas/   # Layer 5: 18 Material-Typen, Aliase, Create-/Edit-Trigger, Persona-Priorität
│   │   ├── 05-knowledge/# Layer 6: RAG- und MCP-Konfiguration
│   │   └── 06-rules/    # Routing-Rules-Engine (deklarative Pre/Post-Route-Regeln)
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

> **Neu für Embed-Hosts (2026-05):**
> - `cards-enabled`, `canvas-enabled`, `ai-content-enabled`, `quick-replies-enabled` —
>   feature-by-feature minimaler Auftritt (siehe Tabelle unten).
> - `show-guide-button`, `guide-mode-default` — Lotsen-Toggle-Button verstecken oder
>   den Modus stillschweigend aktivieren, unabhängig voneinander.
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
| `cards-enabled` | `true` | Kachel-Anzeige. `false` rendert Treffer als dezente Inline-Markdown-Links im Bot-Text (max. N Links, Schwellen in `chatbots/wlo/v1/01-base/widget-modes.yaml`). URL-Auswahl: Lotsen-Modus → Repo-/WLO-Seite (`guide_url`), sonst → Direktlink (`wlo_url`). |
| `canvas-enabled` | `true` | Canvas-Pane (Material-Erstellung, Lernpfad-Anzeige). `false` rendert Material/Lernpfad-Markdown direkt im Chat — kein Canvas-Aufgehen, kein Split-Panel. |
| `ai-content-enabled` | `true` | KI-generierte Inhalte (Arbeitsblatt, Quiz, Lernpfad, Remix). `false` lehnt Erstell-Anfragen mit der Alt-Antwort aus `widget-modes.yaml` freundlich ab — kein LLM-Aufruf für Material-Erstellung. |
| `quick-replies-enabled` | `true` | Gesprächsvorschläge-Pillen unter Bot-Antworten. `false` blendet alle QR-Buttons komplett aus. Lotsen-Hinweise werden in jedem Modus als Inline-Link im Bot-Text gerendert, nicht als Pillen. |
| `inline-result-grouping` | `false` | Gruppierte Treffer-Darstellung. Bei `true` zeigt der Chat statt einer flachen Card-Liste **Top-3 Themenseiten + Top-3 Sammlungen + Webseiten-Inhalte** in eigenen Boxen plus einen vollflächigen Primary-Button „Alle Treffer in der Suche anzeigen" (Theme-Farbe via `primary-color`). Einzelinhalte werden nicht mehr als Kacheln gezeigt — User springt direkt in die MCP-Suchergebnisliste. Greift parallel im Canvas-Pane. |
| `show-guide-button` | `true` | Sichtbarkeit des 🧭-Lotsen-Toggle-Buttons im Header. `false` blendet den Button aus — der Lotsen-Modus selbst bleibt nutzbar (per `guide-mode-default` oder Backend-Default + Cross-TLD-`?bgm=`-Handoff). Empfohlen für Embeds, in denen der Host das Lotsen-Toggling per eigenem UI-Element steuert. |
| `guide-mode-default` | `auto` | Initial-State des Lotsen-Modus. `true`/`false` = explizit ein/aus; `auto` = wie heute (URL `?bgm` → localStorage → Backend-Default aus `guide-mode.yaml`). Wirkt nur beim allerersten Boot — späteres User-Toggle hat Vorrang und wird in localStorage persistiert. |

> **Widget-Embed-Modi** (die vier `*-enabled`-Attribute) lassen die einbettende Seite das Widget
> feature-by-feature minimaler auftreten — für Themenseiten, WordPress-Themes oder fremde
> CMS-Hosts mit eigenem Layout. Defaults bleiben `true`, Bestandsintegrationen sehen keine
> Änderung. Die Schwellen für den Inline-Link-Modus (max. Anzahl, Titel-Kürzung,
> Alt-Antwort-Text) liegen in `chatbots/wlo/v1/01-base/widget-modes.yaml` und sind über
> das Studio editierbar.

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

<!-- Schlanke Themenseite: nur Chat + Inline-Links, kein Canvas, keine Kacheln -->
<boerdi-chat
  api-url="https://api.example.de"
  cards-enabled="false"
  canvas-enabled="false">
</boerdi-chat>

<!-- Reduziert: Kacheln ja, aber keine KI-Material-Erstellung und keine Quick-Replies
     (z.B. wenn der Host bereits eigene Material-Erstellungs-Tools mitbringt) -->
<boerdi-chat
  api-url="https://api.example.de"
  ai-content-enabled="false"
  quick-replies-enabled="false">
</boerdi-chat>

<!-- Minimal-Bubble: praktisch nur Text-Chat mit Inline-Links
     (für eingebettete Hilfe-Bubbles in fremden CMS) -->
<boerdi-chat
  api-url="https://api.example.de"
  cards-enabled="false"
  canvas-enabled="false"
  ai-content-enabled="false"
  quick-replies-enabled="false">
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
Live-Demos: `/widget/` (Default mit Kacheln + Canvas), `/widget/inline` (kompakter Inline-Modus).

#### Embed-Inputs + Outputs/Events

Das Widget hat darüber hinaus eine **umfangreiche Embed-API**: HTML-
Attribute zum Steuern der Display-Modi (`cards-enabled`,
`canvas-enabled`, `ai-content-enabled`, `quick-replies-enabled`), des
Lotsen-Modus (`guide-mode-default`, `emit-guide-suggestion`,
`emit-routing-debug`) und der Link-Interception
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

Ein voller Sweep (alle 9 Personas × 13 Intents × 2 Szenarien) erzeugt 234 Turns und kostet
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
