# BadBoerdi Chatframework — Uebersicht

## Was ist BadBoerdi?

BadBoerdi ist ein konfigurierbares Chatbot-Framework fuer Bildungsplattformen. Der Referenz-Chatbot **BOERDi** (die blaue Eule) wird auf [WirLernenOnline.de](https://wirlernenonline.de) eingesetzt und hilft Lehrkraeften, Schueler:innen und Eltern bei der Suche nach offenen Bildungsmaterialien (OER).

Das Framework besteht aus **drei Softwarebestandteilen**, die als Docker-Container betrieben werden.

---

## 1. Backend (Python / FastAPI)

Das Backend ist das Herzstueck — es verarbeitet Chat-Nachrichten, klassifiziert Nutzeranfragen, fuehrt Sicherheitspruefungen durch und generiert Antworten.

**Kernfunktionen:**
- **Chat-Pipeline** — 7-phasige Verarbeitung jeder Nachricht (Eingabe, Klassifikation, Steuerung, Modulation, Ausfuehrung, Feedback, Observability)
- **5-Schichten-Architektur** — YAML/Markdown-basierte Chatbot-Konfiguration in `chatbots/wlo/v1/` (Identitaet, Domain, Patterns, Dimensionen, Wissen)
- **Safety-Pipeline** — 3-stufige Sicherheitspruefung (Regex, OpenAI Moderation, LLM-Rechtsklassifikator)
- **MCP-Tool-Integration** — Anbindung an externe Datenquellen (WLO edu-sharing: Sammlungen, Materialien, Themenseiten mit zielgruppenspezifischen Varianten)
- **RAG-Wissensbereiche** — Vektorbasierte Wissensdatenbank mit Always-On und On-Demand-Bereichen, inkl. Seed-System fuer initiale Wissensbasis bei Neuinstallation
- **Spekulative Vorab-Abfragen** — Parallelisierte Safety/Classify-Ausfuehrung + vorausschauende MCP-Tool-Calls fuer reduzierte Latenz
- **Multi-Provider LLM-Abstraktion** — OpenAI nativ, B-API-OpenAI, B-API-AcademicCloud
- **Session-Management** — SQLite-basiert mit Gespraechsverlauf und State-Tracking
- **Sprache** — Whisper STT + satzweise OpenAI TTS mit Pre-Fetching (nur bei OpenAI-Provider)
- **Quality-Logging** — Automatische Protokollierung jedes Turns (Pattern, Scores, Confidence, Entities, Degradation) fuer Offline-Analyse
- **Widget-Auslieferung** — Stellt das kompilierte Chat-Widget unter `/widget/` bereit
- **Config-API** — REST-Endpunkte fuer Studio-Zugriff auf alle YAML/Markdown-Konfigurationen
- **Backup/Restore** — Sicherung und Wiederherstellung der gesamten Chatbot-Konfiguration

**Technologie:** Python 3.12, FastAPI, AsyncOpenAI, SQLite + sqlite-vec, uvicorn

**Port:** 8000

---

## 2. Studio (Next.js)

Das Studio ist die Konfigurations-Oberflaeche. Hier werden alle 5 Architektur-Schichten visuell editiert — ohne YAML-Dateien manuell anfassen zu muessen.

**Kernfunktionen:**
- **Schicht 1 — Identitaet & Schutz:** Persona-Editor, Safety-Preset-Auswahl (off/basic/standard/strict/paranoid), Geraete-Konfiguration
- **Schicht 2 — Domain & Regeln:** Domain-Regel-Editor, Policy-Verwaltung (Persona/Intent-basierte Tool-Blockaden)
- **Schicht 3 — Patterns:** Visueller Pattern-Editor mit Gate-Konfiguration, Signal-Fit-Gewichten, Ton/Laenge/Detail-Defaults
- **Schicht 4 — Dimensionen:** Persona-Verwaltung, Intent-Definitionen, Entity-Slots, Signal-Modulationstabelle, State-Definitionen, Kontext-Definitionen
- **Schicht 5 — Wissen:** RAG-Wissensbereiche (Dokument-Upload per Datei/URL/Text, Mode-Toggle always/on-demand), MCP-Server-Registry mit Tool-Discovery
- **Sessions:** Gespraechsverlauf-Einsicht mit Replay
- **Safety-Logs:** Risiko-Events, Rate-Limit-Uebersicht
- **Quality-Analytics:** Quality-Logs und aggregierte Metriken (Pattern-Verteilung, Confidence, Degradation-Rate)
- **Import/Export:** Komplette Konfiguration als JSON, Backup/Restore
- **Passwortschutz:** Optionaler Login via `STUDIO_PASSWORD` (Cookie-basiert)

**Technologie:** Next.js 15, React 18, TypeScript

**Port:** 3001

---

## 3. Chatbot-Hostseite (nginx)

Eine leichtgewichtige Standalone-Webseite, die das Chat-Widget einbettet — gedacht als oeffentlicher Chatbot-Zugang ohne die WLO-Hauptseite.

**Kernfunktionen:**
- **Eigenstaendige Hostseite** mit eingebettetem `<boerdi-chat>`-Widget
- **Konfigurierbar** ueber Umgebungsvariable `BACKEND_URL` (wird beim Container-Start via Template-Rendering eingesetzt)
- **Healthcheck** unter `/healthz`

**Technologie:** nginx 1.27-alpine, HTML/CSS, sed-basiertes Template-Rendering

**Port:** 8080

---

## Architektur-Diagramm

```
Nutzer:in (Browser)
    |
    |--- :8080 ---> [Chatbot-Hostseite]  (nginx, statische HTML + Widget)
    |                    |
    |                    | <script src=":8000/widget/boerdi-widget.js">
    |                    v
    |--- :8000 ---> [Backend]            (FastAPI, Chat-API, Widget-JS)
    |                    |
    |                    |--- MCP-Server (WLO edu-sharing)
    |                    |--- OpenAI API / B-API
    |                    |--- SQLite (Sessions + RAG-Vektoren)
    |
    |--- :3001 ---> [Studio]             (Next.js, Config-UI)
                         |
                         |--- :8000/api  (Config lesen/schreiben)
```

---

## Feature-Matrix

| Feature                     | Backend | Studio | Chatbot |
|-----------------------------|:-------:|:------:|:-------:|
| Chat-Verarbeitung           |    x    |        |         |
| MCP-Tool-Aufrufe            |    x    |        |         |
| RAG-Wissensabfrage          |    x    |        |         |
| Safety-Pruefung             |    x    |        |         |
| Session-Verwaltung          |    x    |   x    |         |
| Konfig-Editor               |         |   x    |         |
| MCP-Server-Discovery        |         |   x    |         |
| Dokument-Upload (RAG)       |    x    |   x    |         |
| Widget-JS-Auslieferung      |    x    |        |         |
| Chat-Widget-Anzeige         |         |        |    x    |
| Backup/Restore              |    x    |   x    |         |
| Quality-Logging/Analytics   |    x    |   x    |         |
| Passwortschutz              |         |   x    |         |
| API-Key-Authentifizierung   |    x    |   x    |         |
| Whisper STT / OpenAI TTS    |    x    |        |         |
| Health-Endpoint             |    x    |        |    x    |
