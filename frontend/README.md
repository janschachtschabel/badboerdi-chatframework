# BadBoerdi Frontend (Angular 21)

Enthält zwei Build-Targets aus _einer_ Codebasis:

1. **Standalone-App** (`npm start`) — vollwertige Chat-Oberfläche unter `http://localhost:4200`
2. **Embeddable Widget** (`npm run build:widget`) — Custom Element `<boerdi-chat>`, das auf
   beliebigen Drittseiten eingebunden werden kann

Beide nutzen dieselbe `ChatComponent` (`src/app/chat/`).

## 1. Setup

```bash
cd frontend
npm install

# Dev (mit Proxy auf das Backend :8000)
npm start                # http://localhost:4200

# Production-Build der Standalone-App
npm run build

# Embeddable Web Component
npm run build:widget     # → dist/widget/browser/main.js
```

Der Dev-Proxy ist in `proxy.conf.json` konfiguriert (`/api → http://localhost:8000`).

## 2. Architektur

```
src/
├── app/
│   ├── chat/                  # ChatComponent — UI, Audio, Pattern-Debug, Pagination
│   ├── canvas/                # CanvasComponent — Markdown/Kachel-Pane neben dem Chat
│   ├── widget/
│   │   ├── widget.component.ts        # WidgetComponent — Floating-Eule + Panel-Wrapper + Canvas-Layout
│   │   └── page-context-detector.ts   # URL+DOM-Heuristik für WLO-Themenseiten/Sammlungen/Inhaltsseiten
│   └── services/
│       └── api.service.ts     # fetch-Wrapper, sessionId, URL-Regex für page_context
├── widget-main.ts             # Bootstrap als Custom Element via @angular/elements
├── main.ts                    # Bootstrap als normale Angular-App
└── styles.scss
```

* `ChatComponent` ist ein **Standalone-Component** und wird vom Widget per
  `<badboerdi-chat>`-Selector eingebettet.
* `CanvasComponent` rendert Markdown-Ausgaben (Arbeitsblatt, Quiz, Bericht, …) mit
  Druck/Download, sowie die Material-Kachel-Grid für Such-Ergebnisse. Shown neben dem Chat auf
  Desktop (≥1200px), darunter Tab-Switcher im Header.
* `WidgetComponent` (Selector `boerdi-chat-widget`) wird in `widget-main.ts` über
  `createCustomElement()` zu `<boerdi-chat>`. Shadow-DOM isoliert das CSS gegen die Host-Seite.
* `angular.json` enthält ein eigenes Build-Target `build-widget` mit `index: false`,
  `outputHashing: none` und Entry `src/widget-main.ts`. Ergebnis: ein einziges `main.js` (~395 KB).

## 3. Embedding (Web Component)

Voraussetzung: Backend läuft und das Widget-Bundle ist gebaut (`npm run build:widget`).

```html
<script src="https://api.example.com/widget/boerdi-widget.js" defer></script>

<boerdi-chat
  api-url="https://api.example.com"
  page-context='{"thema":"eiszeit","klasse":"5"}'
  position="bottom-right"
  initial-state="collapsed"
  primary-color="#1c4587"
  persist-session="true"
  session-key="boerdi_session_id"
  greeting="Hi! Wonach suchst du heute?"
  auto-context="true"
  show-debug-button="true"
  show-language-buttons="true">
</boerdi-chat>
```

### Properties

| Attribut | Default | Beschreibung |
|----------|---------|--------------|
| `api-url` | _proxied_ | Basis-URL des FastAPI-Backends |
| `page-context` | `""` | JSON-String, der ins `environment.page_context` einfließt (Pattern-Engine, Themenseiten-Resolver). Manuelle Keys überschreiben Auto-Context. |
| `position` | `bottom-right` | `bottom-right` · `bottom-left` · `top-right` · `top-left` |
| `initial-state` | `collapsed` | Startet als FAB oder offenes Panel |
| `primary-color` | `#1c4587` | Akzentfarbe |
| `persist-session` | `true` | Session-ID in `localStorage` halten (Cross-Page) |
| `session-key` | `boerdi_session_id` | Storage-Key |
| `greeting` | _Default-Grußtext_ | Erste Bot-Nachricht überschreiben |
| `auto-context` | `true` | URL-Pattern, Meta-Tags, DOM-Inhalt und Titel automatisch in den Page-Context packen (siehe Auto-Context-Sektion unten) |
| `show-debug-button` | `true` | 🔍 Debug-Toggle im Header anzeigen. `false` = Button ausgeblendet (für Produktiv-Embeddings sinnvoll) |
| `show-language-buttons` | `true` | 🔊 Text-to-Speech und 🎤 Mic-Aufnahme anzeigen. `false` = beide Buttons aus (Embedding ohne Sprach-Feature) |

> **Boolean-Attribute akzeptieren `"true"` / `"false"` als String**, weil HTML-Attribute immer
> Strings sind. Property-Setting via JS nimmt auch echte Booleans entgegen
> (`document.querySelector('boerdi-chat').showDebugButton = false`).

### Auto-Context — Page-Context-Detector (`page-context-detector.ts`)

Wenn `auto-context="true"` ist (Default), läuft beim Widget-Start ein Multi-Stufen-Detektor.
Erkannte Felder landen in `environment.page_context` und werden vom Backend für die
Klassifikation und das System-Prompt-Layer 6 (Wissen) genutzt:

**1. URL-Pattern** (`window.location`):

| Input | Extrahierte Felder | `page_kind` |
|-------|------------------|------|
| `/components/render/<uuid>[/...]` | `node_id` | `content` |
| `?node=<uuid>` / `?node_id=<uuid>` | `node_id` | `content` |
| `?collection=<uuid>` / `?collection_id=<uuid>` | `collection_id` | `collection` |
| `/themenseite/<slug>[/...]` | `topic_page_slug` | `topic` |
| `/fachportal/<subject>[/<slug>]` | `subject_slug` (+ optional `topic_page_slug`) | `subject` |
| `?q=<term>` / `?search=` / `?query=` | `search_query` | `search` |

**2. DOM-Marker** (Opt-in für die Host-Seite — höher priorisiert als URL-Hits):

```html
<!-- Im <head> der Host-Seite -->
<meta name="boerdi:node-id"        content="d0ed50e6-a49f-4566-8f3b-c545cdf75067">
<meta name="boerdi:collection-id"  content="…">
<meta name="boerdi:topic-slug"     content="klimawandel">

<!-- Oder als data-Attr am Body -->
<body data-edu-node-id="…" data-edu-topic-slug="…">
```

**3. Visible-Text-Extraktion** (für Seiten ohne strukturierte Marker):

Bei erkanntem `page_kind ≠ search` extrahiert der Detector Titel + Meta-Description +
Hauptcontent (`<main>`, `<article>`, `[role=main]`, `#content`, `.content`, `body` —
in dieser Reihenfolge) und legt sie als `page_text` (max 3 KB) ins `page_context`.

Strippt vor der Extraktion: `<boerdi-chat>` (das Widget selbst), `<script>`, `<style>`,
`<nav>`, `<header>`, `<footer>`, `[aria-hidden="true"]`, `.visually-hidden`.

**Backend-Verarbeitung:**

- `node_id` / `collection_id` / `topic_page_slug` / `subject_slug` werden via MCP
  (`get_node_details`, `search_wlo_topic_pages`) zu semantischen Metadaten aufgelöst
  (Titel, Fach, Stufen, Keywords) — landet als „## Aktuelle Themenseite"-Block im
  System-Prompt.
- Bei MCP-Fehlschlag oder unbekannten URLs greift `page_text` als heuristischer Fallback
  („## Inhalt der aktuellen Seite (Heuristik)"-Block in `page_context_service.render_raw_for_prompt`).
- Beide Wege machen den Bot in der Lage, „Worum geht es hier?", „Mehr Material dazu",
  „Erstelle ein Quiz dazu" ohne Rückfragen zu beantworten.

### Cross-Page-Continuity

Lädt die Web-Component auf einer neuen Seite und findet sie in `localStorage`:

1. eine `session-id` → ruft `GET /api/sessions/{id}/messages` und stellt den Verlauf wieder her,
2. einen TTL-Marker `boerdi_widget_open` (≤ 30 min) → öffnet das Panel automatisch.

So fühlt sich der Bot wie ein durchlaufender Begleiter über mehrere Unterseiten hinweg an.

## 3a. Canvas-Arbeitsfläche

Das Widget expandiert auf breiten Displays (≥1200 px) um eine **Canvas-Pane** rechts neben dem
Chat. Sie zeigt entweder ein Markdown-Dokument (Arbeitsblatt, Quiz, Factsheet, Bericht, …) mit
Druck/Download oder die Material-Kachel-Grid für Such-Ergebnisse. Mobile: Tab-Switcher im
Header.

**Events vom Backend** (`ChatResponse.page_action`):

| Action | Payload | Wirkung |
|--------|---------|---------|
| `canvas_open` | `{title, material_type, material_type_label, material_type_category, markdown}` | Öffnet Canvas und lädt Markdown |
| `canvas_update` | `{markdown}` | Ersetzt aktuellen Markdown-Inhalt (Edit-Response) |
| `canvas_show_cards` | `{cards, query}` | Kachel-Ansicht für Such-Treffer |
| `canvas_close` | `{}` | Canvas schließen |

**`material_type_category`** ist `didaktisch` oder `analytisch` — das CanvasComponent zeigt
einen entsprechend farbigen Badge (grün / blau).

**Follow-Up-Edits** im Chat: schreibt der User „Mach es einfacher" / „Füge Lösungen hinzu" /
„Kürzer fassen" (Auswahl der 56 Edit-Trigger), erkennt das Backend INT-W-12 und verfeinert den
Canvas-Inhalt per `edit_canvas_content()` ohne Neu-Generierung. „Erstelle mir ein neues Quiz"
gewinnt auch in state-12 und geht auf Create.

## 4. Widget bauen & ans Backend ausliefern

```bash
npm run build:widget
```

Das Output liegt unter `dist/widget/browser/main.js`. **Es ist kein Kopier-Schritt nötig**: Der
FastAPI-Router `backend/app/routers/widget.py` liest dieses Verzeichnis zur Laufzeit und liefert
das Bundle unter `/widget/boerdi-widget.js` aus. Convenience-Skripte:

```bash
../scripts/build-widget.sh        # Linux/macOS
..\scripts\build-widget.ps1       # Windows
```

Die Skripte:

1. wechseln nach `frontend/`,
2. rufen `npm install` (falls `node_modules` fehlt) und `npm run build:widget`,
3. prüfen, dass `dist/widget/browser/main.js` existiert,
4. geben die Embed-URL aus.

### Sync-Variante für isolierte Backend-Deploys

Wenn das Backend ohne das Geschwister-`frontend/`-Verzeichnis deployed wird (z.B. Docker-Image, das nur `backend/` enthält), kopiert ein zweites Skript das gebaute Bundle nach `backend/widget_dist/main.js`. Der Widget-Router fällt automatisch auf diesen Pfad zurück, sobald `frontend/dist/...` fehlt.

```bash
../scripts/sync-widget-to-backend.sh    # Linux/macOS
..\scripts\sync-widget-to-backend.ps1   # Windows
```

Im normalen Mono-Repo-Betrieb wird **`build-widget`** verwendet — `sync-widget-to-backend` ist ausschließlich für den Sonderfall „Backend allein verpacken" gedacht.

## 5. Backend-URL zur Laufzeit setzen

Damit ein einziger Widget-Bundle gegen beliebige Backends sprechen kann (Dev, Staging, Prod),
liest das Widget beim Start `window.BOERDI_API_URL`. Ist die Variable nicht gesetzt, fällt das
Widget auf `/api` (Same-Origin zum Einbettungs-Host) zurück.

```html
<!-- VOR dem Widget-Script setzen -->
<script>
  window.BOERDI_API_URL = "https://api.example.com";
</script>
<script src="https://cdn.example.com/widget/boerdi-widget.js" defer></script>

<boerdi-chat position="bottom-right"></boerdi-chat>
```

Das Attribut `api-url` am Custom-Element hat weiterhin Vorrang, falls gesetzt.

## 6. Sprachein- und -ausgabe

* **Spracheingabe** (🎤): MediaRecorder → `POST /api/speech/transcribe` (OpenAI STT, `gpt-4o-mini-transcribe` mit Fallback auf `gpt-4o-transcribe` → `whisper-1`) → Text ins Eingabefeld
* **Sprachausgabe** (🔊): Satzweise OpenAI TTS mit Pre-Fetching — waehrend Satz N abgespielt wird, wird Satz N+1 bereits geladen. Abbruch jederzeit via Toggle. Automatik-Modus (Auto-Speak) liest jede Bot-Antwort vor.
* TTS wird nur bei `LLM_PROVIDER=openai` unterstuetzt.
* Der Lautsprecher-Button zeigt einen roten Strich (🔊 durchgestrichen) wenn deaktiviert.

## 7. Debug-Panel

Der 🔍-Button im Header schaltet das Debug-Panel ein/aus (Standard: aus, roter Strich).
Es zeigt den vollstaendigen `debug`-Block der Backend-Antwort:

* **Klassifikation:** Persona, Intent, State (jeweils mit Label in Klammern), Turn-Type
* **Pattern-Engine:** Pattern, Signale, Entities, Phase-1-Eliminierung, Phase-2-Scores
* **Phase 3 Modulation:** Ton, Formalitaet, Laenge, Detail, Max-Items, Card-Text-Mode, Response-Type, Format, Quellen, Pattern-Tools, RAG-Areas, Core-Rule, Boolean-Flags
* **Degradation:** fehlende Slots, blockierte Patterns
* **Safety:** Risk-Level, Stages, Eskalation, Legal-Flags, blockierte Tools
* **Policy:** erlaubt/blockiert, Regeln, Disclaimers
* **Outcomes:** Tool-Ergebnisse mit Status, Item-Count, Latenz
* **Confidence:** Finale Confidence nach Outcome-Adjustments
* **Context:** Seite, Geraet, Turn-Count
* **Trace:** Phasen-Laufzeiten (Safety, Classify, Pattern, Response)

## 8. Tipps

* Bei Strict-TypeScript-Templates auf `?.length` neben `.join()` achten (NG8107). Siehe
  bestehende `!.`-Assertions in `chat.component.html`.
* Wenn das Widget auf einer Drittseite **kein** Eingabefeld zeigt, ist meist `.chat-wrapper`
  mit `height: 100vh` schuld → es muss `height: 100%; min-height: 0` sein.
