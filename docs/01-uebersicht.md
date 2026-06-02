# BadBoerdi Chatframework — Uebersicht

## Was ist BadBoerdi?

BadBoerdi ist ein konfigurierbares Chatbot-Framework fuer Bildungsplattformen. Der Referenz-Chatbot **BOERDi** (die blaue Eule) wird auf [WirLernenOnline.de](https://wirlernenonline.de) eingesetzt und hilft Lehrkraeften, Schueler:innen und Eltern bei der Suche nach offenen Bildungsmaterialien (OER).

Das Framework besteht aus **drei Softwarebestandteilen**, die als Docker-Container betrieben werden.

---

## 1. Backend (Python / FastAPI)

Das Backend ist das Herzstueck — es verarbeitet Chat-Nachrichten, klassifiziert Nutzeranfragen, fuehrt Sicherheitspruefungen durch und generiert Antworten.

**Kernfunktionen:**
- **Chat-Pipeline** — Eingabe → Safety+Klassifikation+Memory (parallel) → Pattern-Selektion (Hint-Primary) → Phase-3-Modulation → MCP-/RAG-Reflection-Loop → Response → Quality-Log
- **Schichten-Architektur** — YAML/Markdown-basierte Chatbot-Konfiguration in `chatbots/wlo/v1/` (Identität, Domain, Patterns, Dimensionen, Wissen, Routing-Rules) — siehe [Architektur-Doc](./02-architektur.md)
- **Safety-Pipeline** — 3-stufige Sicherheitspruefung (Regex, OpenAI Moderation, LLM-Rechtsklassifikator)
- **MCP-Tool-Integration** — Anbindung an externe Datenquellen (WLO edu-sharing: Sammlungen, Materialien, Themenseiten mit zielgruppenspezifischen Varianten)
- **RAG-Wissensbereiche** — Vektorbasierte Wissensdatenbank mit Always-On und On-Demand-Bereichen, inkl. Seed-System fuer initiale Wissensbasis bei Neuinstallation
- **Spekulative Vorab-Abfragen** — Parallelisierte Safety/Classify-Ausfuehrung + vorausschauende MCP-Tool-Calls fuer reduzierte Latenz
- **Multi-Provider LLM-Abstraktion** — OpenAI nativ, B-API-OpenAI, B-API-AcademicCloud
- **Session-Management** — SQLite-basiert mit Gespraechsverlauf und State-Tracking
- **Sprache** — OpenAI STT (`gpt-4o-mini-transcribe`, Fallback `whisper-1`) + satzweise OpenAI TTS mit Pre-Fetching (nur bei OpenAI-Provider)
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
- **Schicht 1 — Identität & Schutz:** Safety-Preset-Auswahl (off/regex/standard/strict/paranoid), Geräte-Konfiguration, Tone-Modifier-Defaults, Display- und Widget-Regeln
- **Schicht 2 — Domain & Regeln:** Domain-Regel-Editor, Policy-Verwaltung (Persona/Intent-basierte Tool-Blockaden + Disclaimer)
- **Schicht 3 — Patterns:** Visueller Pattern-Editor mit 5 Tabs (Identität / Antwort-Form / Tools & Wissen / Slots & Degradation / Anweisungen). Welle E v4: Gates und Score sind aus der Engine raus — der Klassifikator-Hint wählt das Pattern.
- **Schicht 4 — Dimensionen:** Persona-Editor (Tonalitäts-Modifier + Klassifikations-Marker — kein Pattern-Mapping mehr), Intent-Definitionen mit Trigger-Verben und Diskriminatoren, Entity-Slots, State-Verlaufs-Phasen, Signal-Modulationstabelle
- **Schicht 5 — Wissen:** RAG-Wissensbereiche (Dokument-Upload per Datei/URL/Text, Mode-Toggle always/on-demand), MCP-Server-Registry mit Tool-Discovery
- **Routing-Rules:** Korrektur-Schicht für klare Edge-Cases. Eval-getriebene Lösch-Vorschläge bei redundanten Rules.
- **Sessions:** Gesprächsverlauf-Einsicht mit Replay
- **Safety-Logs:** Risiko-Events, Rate-Limit-Übersicht
- **Quality-Analytics:** Quality-Logs und aggregierte Metriken (Pattern-Verteilung, Confidence, Degradation-Rate, Pattern-Hint-vs-Final-Disagreement)
- **Evaluation:** Persona-/Intent-Eval-Runs mit Judge-LLM, Pattern-Disagreement-Analyse, Per-Turn-Detail-View
- **Import/Export:** Komplette Konfiguration als ZIP, Backup/Restore
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
| OpenAI STT / OpenAI TTS     |    x    |        |         |
| Health-Endpoint             |    x    |        |    x    |
