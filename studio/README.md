# BadBoerdi Studio (Next.js 15)

Konfigurations-UI für BadBoerdi. Bietet Editoren für die fünf Konfigurations-Schichten unter
`backend/chatbots/wlo/v1/`. Schreibt direkt über die `/api/config/*`-Endpunkte des Backends.

## 1. Setup

```bash
cd studio
npm install
npm run dev          # http://localhost:3001
```

Voraussetzung: Das Backend läuft unter `http://localhost:8000` (sonst sind die Editoren leer).

## 2. Layout

```
src/
├── app/
│   ├── page.tsx           # Tab-basierte Navigation: 5 Layer + Sessions + Safety-Logs
│   └── layout.tsx
└── components/
    ├── HomeOverview.tsx
    ├── ConfigTextEditor.tsx       # generischer Markdown/YAML-Editor (Schichten 1, 2, 5)
    ├── PatternEditor.tsx          # Schicht 3 — die 20 Konversations-Patterns
    ├── ElementEditor.tsx          # Schicht 4 — Personas/Intents/Entities/Slots/…
    ├── KnowledgeManager.tsx       # Schicht 5 — RAG-Wissensbereiche hochladen
    ├── SecurityLevelPicker.tsx    # Sicherheits-Preset (Layer 1)
    ├── SafetyLogsView.tsx         # Risk-Events aus dem Backend
    └── SessionsView.tsx           # Live-Inspektion der Sessions inkl. Debug-Trace
```

## 3. Welcher Editor schreibt was?

| Studio-Bereich | Schicht | Datei(en) im Backend |
|----------------|---------|----------------------|
| **1 — Identität & Schutz** | Layer 1 | `chatbots/wlo/v1/01-base/base-persona.md`, `guardrails.md`, `safety-config.yaml`, `device-config.yaml` |
| `SecurityLevelPicker` | Layer 1 | `safety-config.yaml → security_level` |
| **2 — Domain & Regeln** | Layer 2 | `02-domain/domain-rules.md`, `policy.yaml`, `wlo-plattform-wissen.md` |
| **3 — Patterns** | Layer 3 | `03-patterns/pat-01…pat-20-*.md` |
| **4 — Dimensionen** | Layer 4 | `04-personas/`, `04-intents/`, `04-entities/`, `04-slots/`, `04-signals/`, `04-states/`, `04-contexts/` |
| **5 — Wissen** | Layer 5 | `05-knowledge/rag-config.yaml`, hochgeladene RAG-Quellen |
| **Sessions** | — | Liest `/api/sessions/*` (read-only) |
| **Safety-Logs** | — | Liest `/api/safety/logs` (read-only) |

## 4. Workflow-Empfehlungen

1. **Persona zuerst** (Layer 1) — danach reagieren alle Patterns konsistent.
2. **Domain-Regeln + Policy** (Layer 2) — was darf der Bot strukturell?
3. **Patterns iterativ** (Layer 3) — pro Pattern Score-Tuning anhand der Sessions-View.
4. **Dimensionen** (Layer 4) nur anpassen, wenn der Klassifikator falsch entscheidet.
5. **Wissen** (Layer 5) zuletzt — RAG-Bereiche und MCP-Tools sind die teuerste Schicht
   (Token-Last) und werden nur bei Bedarf in den Prompt geladen.

## 5. Env-Variablen & Backend-Verbindung

Das Studio spricht das Backend **nicht** direkt aus dem Browser an, sondern über einen
server-seitigen Proxy unter `src/app/api/[...path]/route.ts`. Dieser leitet alle `/api/*`-Calls
an das konfigurierte Backend weiter und injiziert dabei den API-Key. So sieht der Browser den
Schlüssel nie.

| Variable | Default | Wirkung |
|----------|---------|---------|
| `BACKEND_URL` | `http://localhost:8000` | Ziel des Proxys — zeigt auf das FastAPI-Backend |
| `STUDIO_API_KEY` | _leer_ | Wird vom Proxy als `X-Studio-Key`-Header gesetzt. Muss mit dem `STUDIO_API_KEY` im Backend übereinstimmen. **Server-only** — bewusst ohne `NEXT_PUBLIC_`-Prefix. |
| `STUDIO_PASSWORD` | _leer_ | Optionales Login-Gate vor dem gesamten Studio (Cookie-basiert). Leer = kein Login. |

Beispiel `studio/.env.local`:

```env
BACKEND_URL=http://localhost:8000
STUDIO_API_KEY=geheim123
STUDIO_PASSWORD=bitteaendern
```

### Backup / Restore aus dem Studio

Im Header gibt es zwei Buttons:

* **Backup** — lädt den kompletten `chatbots/wlo/v1`-Tree als ZIP herunter
  (`GET /api/config/backup`).
* **Restore** — lädt ein ZIP hoch (`POST /api/config/restore`). Vor einem destruktiven
  Restore (`?wipe=true`) wird explizit nachgefragt.

## 6. Build & Deploy

```bash
npm run build       # Next.js production build
npm start           # produktiv auf :3001
```

Das Studio ist eine reine UI über der Backend-API — es enthält keine eigene Persistenz.
