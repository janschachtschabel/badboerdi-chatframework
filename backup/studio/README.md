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

Die Sidebar gruppiert in drei Sektionen:

- **Architektur-Schichten** — die 6 nummerierten Prompt-Schichten (Identität → Wissen) plus
  die Routing-Rules-Engine als „Steuerungsebene" (kein Prompt-Layer, aber Teil der Architektur).
- **Betrieb** — Sessions, Quality, Evaluation, Safety-Logs.
- **System** — Datenschutz, Info.

Die Übersichtsseite (`HomeOverview`) zeigt einen **Live-Status-Streifen** (Backend-Modell,
Werkseinstellungs-Alter, Routing-Engine, letzte Eval) plus Quick-Action-Buttons (📦 Snapshots,
🎯 Evaluation, ⚙️ Routing-Rules, 🎨 Canvas-Formate).

```
src/
├── app/
│   ├── page.tsx                 # 3-Sektion-Sidebar + Layer-Routing
│   └── layout.tsx
└── components/
    ├── HomeOverview.tsx         # Status-Dashboard + Architektur-Karten
    ├── InfoView.tsx             # Architektur-Referenz mit Live-System-Stand, Material-Typen-Liste, Snapshot-Doku, Widget-Embedding
    ├── ConfigTextEditor.tsx     # generischer Markdown/YAML-Editor
    ├── PatternEditor.tsx        # Schicht 3 — Konversations-Patterns
    ├── ElementEditor.tsx        # Schicht 4 — Personas/Intents/States/Signals/Entities
    ├── CanvasFormatsEditor.tsx  # Schicht 5 — typed GUI-Editor für die 18 Material-Typen
    ├── KnowledgeManager.tsx     # Schicht 6 — RAG-Wissensbereiche hochladen
    ├── RoutingRulesView.tsx     # Routing-Engine — Liste + Test-Bench + Stats
    ├── EvaluationView.tsx       # Persona-Dialog-Eval mit LLM-Judge
    ├── QualityView.tsx          # Pattern-Scoring/Confidence/Degradation
    ├── SecurityLevelPicker.tsx  # Sicherheits-Preset (Layer 1)
    ├── SafetyLogsView.tsx       # Risk-Events read-only
    ├── PrivacyView.tsx          # Logging-Toggles + Purge
    ├── SessionsView.tsx         # Live-Sessions + Debug-Trace
    └── SnapshotsModal.tsx       # User-Snapshots + Werkseinstellungs-Verwaltung
```

## 3. Welcher Editor schreibt was?

| Studio-Bereich | Schicht | Datei(en) im Backend |
|----------------|---------|----------------------|
| **1 — Identität & Schutz** | Layer 1 | `chatbots/wlo/v1/01-base/base-persona.md`, `guardrails.md`, `safety-config.yaml`, `device-config.yaml` |
| `SecurityLevelPicker` | Layer 1 | `safety-config.yaml → security_level` |
| **2 — Domain & Regeln** | Layer 2 | `02-domain/domain-rules.md`, `policy.yaml`, `wlo-plattform-wissen.md` |
| **3 — Patterns** | Layer 3 | `03-patterns/pat-01…pat-25-*.md` (27 inkl. PAT-CRISIS, PAT-REFUSE-THREAT) |
| **4 — Dimensionen** | Layer 4 | `04-personas/`, `04-intents/`, `04-entities/`, `04-slots/`, `04-signals/`, `04-states/`, `04-contexts/` |
| **5 — Canvas-Formate** | Layer 5 | `05-canvas/material-types.yaml` (GUI-Editor) + `type-aliases.yaml`, `create-triggers.yaml`, `edit-triggers.yaml`, `persona-priorities.yaml` (Roh-YAML) |
| **6 — Wissen** | Layer 6 | `05-knowledge/rag-config.yaml`, hochgeladene RAG-Quellen |
| **⚙️ Routing-Rules** | _Steuerung_ | `06-rules/routing-rules.yaml` (Pre/Post-Route Rule-Engine) |
| **Datenschutz** | — | `01-base/privacy-config.yaml` (Logging-Toggles + Purge-Endpoints) |
| **Sessions / Quality / Evaluation / Safety-Logs** | — | read-only Views auf Backend-Logs |

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
