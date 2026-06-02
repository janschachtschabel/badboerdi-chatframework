# API-Endpunkte — Public vs. Studio-Protected

> **Zielgruppe:** Personen, die das BadBoerdi-Backend über ein Swagger-Interface (oder eine ähnliche API-Doku) nach außen hin zugänglich machen wollen.
> **Stand:** Mai 2026 — basiert auf `backend/app/main.py` und den Routern in `backend/app/routers/`.

## Inhalt

1. [Überblick](#1-überblick)
2. [Public-Endpunkte (für Chat-Betrieb notwendig)](#2-public-endpunkte)
3. [Studio-Protected Endpunkte (Admin/Studio)](#3-studio-protected-endpunkte)
4. [Empfehlungen](#4-empfehlungen)
5. [TL;DR](#5-tldr)

---

## 1. Überblick

Das Backend hat zwei Klassen von Endpunkten:

- **Public** — wird vom eingebetteten Widget direkt aus dem Browser des Endnutzers aufgerufen. Diese Endpunkte **dürfen keinen Auth-Header** haben, weil das Widget keinen Zugang zum Studio-Key hat.
- **Studio-Protected** — verwaltet Konfiguration, Inhalte, Sessions und Eval-Runs. Schutz via `X-Studio-Key`-Header. Wenn die Umgebungsvariable `STUDIO_API_KEY` gesetzt ist, sind diese Endpunkte geschützt; wenn nicht, sind sie offen (das Backend warnt beim Start, siehe `main.py:36-40`).

**Routing-Setup** (siehe `backend/app/main.py:163-181`):

```python
# Public Mounts
app.include_router(chat.router,     prefix="/api/chat")
app.include_router(speech.router,   prefix="/api/speech")
app.include_router(widget.router,   prefix="/widget")
app.include_router(sessions.router, prefix="/api/sessions")
app.include_router(config.public_router, prefix="/api/config")  # nur /guide-mode

# Studio-Protected Mounts
_studio_deps = [Depends(require_studio_key)]
app.include_router(config.router,        prefix="/api/config",        dependencies=_studio_deps)
app.include_router(rag.router,           prefix="/api/rag",           dependencies=_studio_deps)
app.include_router(safety.router,        prefix="/api/safety",        dependencies=_studio_deps)
app.include_router(quality.router,       prefix="/api/quality",       dependencies=_studio_deps)
app.include_router(routing_rules.router, prefix="/api/routing-rules", dependencies=_studio_deps)
app.include_router(eval_router.router)  # bringt eigene per-route Studio-Guards mit
```

`sessions.py` und `eval.py` arbeiten mit **per-Route-Dependencies** (`dependencies=_studio` direkt am Decorator), damit innerhalb eines Routers ein einzelner Endpunkt public sein kann (z. B. History-Restore).

---

## 2. Public-Endpunkte

Diese Endpunkte werden vom Widget oder Browser direkt benutzt und **müssen** öffentlich erreichbar sein.

### Health & Meta

| Method | Path | Zweck |
|---|---|---|
| `GET` `HEAD` | `/health` | Container-Healthcheck (Docker `HEALTHCHECK`) |
| `GET` `HEAD` | `/api/health` | App-Health (gibt Provider/Model zurück) |
| `GET` `HEAD` | `/` | Redirect → `/api/health` |

### Chat (Kern)

| Method | Path | Zweck |
|---|---|---|
| `POST` | `/api/chat` | Hauptchat-Endpunkt |
| `POST` | `/api/chat/stream` | SSE-Streaming-Variante |

### Speech (STT/TTS)

| Method | Path | Zweck |
|---|---|---|
| `POST` | `/api/speech/transcribe` | Spracheingabe → Text (Whisper) |
| `POST` | `/api/speech/synthesize` | Text → Sprachausgabe |

### Widget-Assets

| Method | Path | Zweck |
|---|---|---|
| `GET` | `/widget/boerdi-widget.js` | JS-Bundle für Embed |
| `GET` | `/widget/{asset_name}` | CSS, Fonts, Icons |
| `GET` | `/widget/` | Demo-HTML |
| `GET` | `/api/static/*` | Logo (`boerdi.svg`) |

### Session-History (für Widget-Restore)

| Method | Path | Zweck |
|---|---|---|
| `GET` | `/api/sessions/{session_id}/messages` | History-Restore beim Widget-Reload (Session-ID dient als implizites Token) |

### Lotsen-Modus Allow-List

| Method | Path | Zweck |
|---|---|---|
| `GET` | `/api/config/guide-mode` | Liefert dem Widget die erlaubten Domains (Lotsen-Banner UI) |

**Summe Public:** ~13 Endpunkte

---

## 3. Studio-Protected Endpunkte

Diese Endpunkte verwalten Konfiguration, Inhalte, Sessions und Eval-Runs. Sie **dürfen nicht öffentlich erreichbar** sein, weil sie sonst Daten preisgeben oder verändern könnten.

### Sessions (Verwaltung)

| Method | Path | Zweck |
|---|---|---|
| `GET` | `/api/sessions` `/api/sessions/` | Liste aller Sessions |
| `POST` | `/api/sessions/purge` | Bulk-Löschung alter Sessions |
| `GET` | `/api/sessions/{session_id}` | Session-Details |
| `GET` | `/api/sessions/{session_id}/memory` | Memory-Slots auslesen |
| `POST` | `/api/sessions/{session_id}/memory` | Memory-Slots überschreiben |
| `DELETE` | `/api/sessions/{session_id}` | Session löschen |
| `DELETE` | `/api/sessions/{session_id}/messages` | History löschen |

### Config (Chatbot-Definition)

| Method | Path | Zweck |
|---|---|---|
| `GET PUT DELETE` | `/api/config/file` | YAML/Markdown-Config CRUD |
| `GET` | `/api/config/files` | Datei-Tree |
| `GET PUT` | `/api/config/privacy` | Datenschutz-Settings |
| `GET PUT` | `/api/config/canvas/material-types` | Canvas-Templates |
| `GET` | `/api/config/elements` | UI-Elemente |
| `GET PUT` | `/api/config/mcp-servers` | MCP-Server-Liste |
| `POST` | `/api/config/mcp-servers/discover` | MCP-Discovery |
| `GET POST` | `/api/config/backup`, `/restore` | Voll-Backup |
| `GET POST DELETE` | `/api/config/snapshots`, `/snapshots/{id}/...` | Snapshots-Management |
| `GET POST` | `/api/config/factory/...` | Factory-Reset / Save / Upload |

### RAG (Wissensbasis)

| Method | Path | Zweck |
|---|---|---|
| `POST` | `/api/rag/ingest/file`, `/ingest/url`, `/ingest/text` | Dokumente einspeisen |
| `POST` | `/api/rag/query` | Direktes RAG-Search |
| `POST` | `/api/rag/embed` | Embeddings nachziehen |
| `GET DELETE` | `/api/rag/areas`, `/area/{area}`, `/area/{area}/doc` | Areas/Docs verwalten |

### Safety / Quality

| Method | Path | Zweck |
|---|---|---|
| `GET` | `/api/safety/logs`, `/stats` | Safety-Auswertung |
| `GET` | `/api/quality/logs`, `/stats`, `/tight-races`, `/degradations`, `/empty-entities`, `/low-confidence` | Qualitäts-Monitoring |
| `DELETE POST` | `/api/quality/logs/{id}`, `/logs/clear` | Logs verwalten |

### Routing-Rules

| Method | Path | Zweck |
|---|---|---|
| `GET` | `/api/routing-rules`, `/stats`, `/{rule_id}` | Regeln einsehen |
| `POST` | `/api/routing-rules/test`, `/reload` | Regel testen / neuladen |
| `DELETE` | `/api/routing-rules/stats` | Stats zurücksetzen |

### Eval (Persona-Tests)

| Method | Path | Zweck |
|---|---|---|
| `GET` | `/api/eval/config`, `/runs`, `/trends`, `/runs/{id}`, `/analytics/pattern-usage` | Eval-Daten lesen |
| `POST` | `/api/eval/estimate`, `/runs` | Schätzung / Run starten |
| `DELETE` | `/api/eval/runs/{id}`, `/runs`, `/quality-logs` | Aufräumen |

### Debug

| Method | Path | Zweck |
|---|---|---|
| `GET` | `/api/debug/mcp-test` | MCP-Connectivity-Test |

**Summe Studio-Protected:** ~55 Endpunkte

---

## 4. Empfehlungen

### 4.1 Trennung in Swagger UI

FastAPI vergibt bereits **Tags** in `main.py` (`chat`, `speech`, `widget`, `sessions`, `config`, `rag`, `safety`, `quality`, `routing-rules`, `eval`, `health`).

Empfehlung:

- **Public-Doku**: nur die Tags `chat`, `speech`, `widget`, `health` + die zwei Spezialendpunkte (`/api/sessions/{id}/messages`, `/api/config/guide-mode`) anzeigen.
- **Admin-Doku**: alle anderen Tags. Idealerweise hinter einem Reverse-Proxy mit eigener Auth (Basic-Auth, IP-Whitelist) — die Swagger-UI selbst sollte schon nicht öffentlich erreichbar sein.
- Alternative: zwei FastAPI-Apps mountieren oder per `include_in_schema=False` für sensible Routen.

### 4.2 Auth-Setup im Swagger

Der `X-Studio-Key`-Header ist ein simpler API-Key. In Swagger als `securitySchemes: ApiKeyAuth` (header `X-Studio-Key`) registrieren — dann bekommt der User einen "Authorize"-Knopf.

> ⚠ **Achtung**: `STUDIO_API_KEY` muss in Production gesetzt sein. Backend warnt zwar beim Start, aber ohne Key sind **alle Studio-Endpunkte offen** — das ist gefährlich, sobald Swagger nach außen zeigt.

### 4.3 Rate-Limiting

Die Public-Endpunkte sind kostenrelevant (LLM-Calls):

- `POST /api/chat` & `/api/chat/stream` — pro Session/IP throtteln (z. B. 30 req/min/IP), sonst kann ein Spammer ~€0,01 pro Anfrage in deine OpenAI-Rechnung treiben.
- `POST /api/speech/*` — STT/TTS sind ebenfalls kostenintensiv (Whisper ~€0,006/min, TTS ~€0,015/1k chars). Per-Session-Limit empfohlen.
- Empfehlung: `slowapi` (FastAPI-Middleware) oder Reverse-Proxy-Limit (nginx `limit_req`).

### 4.4 CORS einschränken

Aktuell `CORS_ORIGINS=*` (siehe `docker-compose.yml:39`, `main.py:137-144`). Sobald Swagger öffentlich ist, sollte CORS auf konkrete Origin-Domains gesetzt werden (z. B. die Host-Seiten, auf denen das Widget eingebettet ist) — sonst kann beliebiger Code im Browser des Users gegen dein API laufen.

### 4.5 `/api/health`-Payload reduzieren

`GET /api/health` (`main.py:206-223`) leakt aktuell:

- `provider` (z. B. "openai" oder "b-api")
- `chat_model` (z. B. "gpt-4.1-mini")
- `embed_model`
- `verbosity`, `reasoning_effort`

Für Public-Swagger sollte das auf `{"status": "ok"}` reduziert werden — ein Angreifer muss nicht wissen, welches LLM-Modell läuft. `/health` (ohne `/api`) tut das schon richtig.

### 4.6 `/api/sessions/{id}/messages` absichern

Die Session-ID dient hier als impliziter Auth-Token. Risiko: Wenn die ID erratbar ist (z. B. inkrementell), könnte jemand fremde History lesen. Prüfen:

- Session-IDs müssen **kryptografisch zufällig** sein (UUID4 oder ähnlich) — schau im `database.py`/`session_service.py` nach `secrets.token_urlsafe(...)`.
- Optional: HMAC-Signatur über die Session-ID, damit das Widget eine ID nicht manipulieren kann.

### 4.7 `/api/debug/mcp-test` rauswerfen oder umbenennen

Der Endpunkt ist Studio-protected, aber `/debug/...` in einer öffentlichen Swagger-UI signalisiert "interessant für Pen-Tester". Entweder:

- Mit `include_in_schema=False` aus Swagger ausblenden, oder
- In `/api/admin/mcp-status` umbenennen.

### 4.8 Speech-Endpunkte: Auth-Optionalität bedenken

Aktuell sind STT/TTS komplett offen. Wenn euer Widget die einzige Quelle ist, könnte man optional einen schwachen, gerottierten Token (z. B. CSP-gebunden) erfinden — aber das ist Phase 2. Für jetzt: **mindestens Rate-Limit pro IP**.

### 4.9 Swagger-Beispiele kuratieren

Standard-Swagger zeigt für `POST /api/chat` ein gigantisches Pydantic-Schema (`ChatRequest`, `ChatResponse` mit allen `PageAction`-Varianten etc.). Empfehlung: für Public-Doku nur das Minimal-Beispiel (`message`, `session_id`, optional `chatbot_id`) als `example=` annotieren — das macht die API einsteigerfreundlicher.

### 4.10 Versionierung vorbereiten

Public-API ist für Drittnutzer interessant (Widget-Embedder). Bevor jemand produktiv anbindet, einen `/api/v1/`-Präfix einführen — sonst zwingt jeder Breaking-Change zur Code-Synchronisation. Studio-Endpunkte können unversioniert bleiben (nur internes Tooling).

---

## 5. TL;DR

> Im Swagger UI nur die Tags `chat`, `speech`, `widget`, `health` öffentlich zeigen plus `/api/sessions/{id}/messages` und `/api/config/guide-mode`. Den Rest (`config`, `rag`, `safety`, `quality`, `routing-rules`, `eval`, alle Session-Verwaltung) nur in der Admin-Doku hinter Auth. **`STUDIO_API_KEY` setzen, sonst ist alles offen.** `CORS_ORIGINS` auf konkrete Domains. Rate-Limit auf `/api/chat` und `/api/speech` einbauen. `/api/health`-Payload reduzieren.
