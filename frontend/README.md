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
│   ├── widget/                # WidgetComponent — Floating-Eule + Panel-Wrapper
│   └── services/
│       └── api.service.ts     # fetch-Wrapper, sessionId, History-Restore
├── widget-main.ts             # Bootstrap als Custom Element via @angular/elements
├── main.ts                    # Bootstrap als normale Angular-App
└── styles.scss
```

* `ChatComponent` ist ein **Standalone-Component** und wird vom Widget per
  `<badboerdi-chat>`-Selector eingebettet.
* `WidgetComponent` (Selector `boerdi-chat-widget`) wird in `widget-main.ts` über
  `createCustomElement()` zu `<boerdi-chat>`. Shadow-DOM isoliert das CSS gegen die Host-Seite.
* `angular.json` enthält ein eigenes Build-Target `build-widget` mit `index: false`,
  `outputHashing: none` und Entry `src/widget-main.ts`. Ergebnis: ein einziges `main.js`.

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
  auto-context="true">
</boerdi-chat>
```

### Properties

| Attribut | Default | Beschreibung |
|----------|---------|--------------|
| `api-url` | _proxied_ | Basis-URL des FastAPI-Backends |
| `page-context` | `""` | JSON-String, der ins `environment.page_context` einfließt (Pattern-Engine) |
| `position` | `bottom-right` | `bottom-right` · `bottom-left` · `top-right` · `top-left` |
| `initial-state` | `collapsed` | Startet als FAB oder offenes Panel |
| `primary-color` | `#1c4587` | Akzentfarbe |
| `persist-session` | `true` | Session-ID in `localStorage` halten (Cross-Page) |
| `session-key` | `boerdi_session_id` | Storage-Key |
| `greeting` | _Default-Grußtext_ | Erste Bot-Nachricht überschreiben |
| `auto-context` | `true` | URL, Query, Title, Referrer automatisch in den Page-Context packen |

### Cross-Page-Continuity

Lädt die Web-Component auf einer neuen Seite und findet sie in `localStorage`:

1. eine `session-id` → ruft `GET /api/sessions/{id}/messages` und stellt den Verlauf wieder her,
2. einen TTL-Marker `boerdi_widget_open` (≤ 30 min) → öffnet das Panel automatisch.

So fühlt sich der Bot wie ein durchlaufender Begleiter über mehrere Unterseiten hinweg an.

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

## 6. Debug-Panel

Im Chat-UI lässt sich (über das Werkzeug-Symbol) ein Debug-Panel einblenden, das den
`debug`-Block der Backend-Antwort visualisiert: Pattern-Scoring (Phase 1/2/3), Tool-Outcomes,
Safety-Stages, Policy-Decision, Trace mit Phase-Dauer. Hilfreich beim Tuning der Patterns.

## 7. Tipps

* Bei Strict-TypeScript-Templates auf `?.length` neben `.join()` achten (NG8107). Siehe
  bestehende `!.`-Assertions in `chat.component.html`.
* Wenn das Widget auf einer Drittseite **kein** Eingabefeld zeigt, ist meist `.chat-wrapper`
  mit `height: 100vh` schuld → es muss `height: 100%; min-height: 0` sein.
