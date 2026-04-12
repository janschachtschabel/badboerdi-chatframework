# BadBoerdi Backend (FastAPI)

Python-Service mit Chat-API, Pattern-Engine, mehrstufiger Safety-Pipeline, RAG, MCP-Integration
und Auslieferung des `<boerdi-chat>`-Widgets. Konfiguration ausschliesslich ueber Dateien unter
`chatbots/wlo/v1/` — kein Code-Deploy fuer inhaltliche Aenderungen noetig.

> **Google Colab Notebook:** [BadBoerdi im Browser ausprobieren](https://drive.google.com/file/d/1BFZpEEogOYJa50k7NRxuUVA12Hb89x96/view?usp=sharing) — komplettes Setup ohne lokale Installation.

## 1. Setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # OPENAI_API_KEY, LLM_PROVIDER, MCP-URL, …
python run.py              # uvicorn auf :8000
```

Health-Check: `GET http://localhost:8000/api/health`

### Env-Variablen

| Variable | Default | Wirkung |
|----------|---------|---------|
| `LLM_PROVIDER` | `openai` | LLM-Backend. Werte: `openai` (nativ), `b-api-openai` (B-API → OpenAI), `b-api-academiccloud` (B-API → AcademicCloud / GWDG). Siehe Abschnitt 10. |
| `OPENAI_API_KEY` | _Pflicht bei `openai`_ | OpenAI-Key fuer Chat-Modell, Moderation, Legal-Classifier, Whisper und TTS. |
| `B_API_KEY` | _Pflicht bei `b-api-*`_ | API-Key fuer die B-API. Wird als Header `X-API-KEY` gesendet. |
| `B_API_BASE_URL` | `https://b-api.staging.openeduhub.net/api/v1/llm` | Basis-URL der B-API. `/openai` bzw. `/academiccloud` werden je nach Provider angehaengt. |
| `LLM_CHAT_MODEL` | provider-spezifisch | Override fuer das Chat-Modell. Defaults: `gpt-4.1-mini` (openai, b-api-openai), `Qwen/Qwen3.5-122B-A10B-GPTQ-Int4` (b-api-academiccloud). |
| `LLM_EMBED_MODEL` | provider-spezifisch | Override fuer das Embedding-Modell. Defaults: `text-embedding-3-small` (openai, b-api-openai), `e5-mistral-7b-instruct` (b-api-academiccloud). |
| `OPENAI_MODEL` | `gpt-4.1-mini` | _Legacy_, weiterhin gueltig wenn `LLM_PROVIDER=openai` und `LLM_CHAT_MODEL` nicht gesetzt ist. |
| `MCP_SERVER_URL` | `https://wlo-mcp-server.vercel.app/mcp` | Default-Ziel des WLO-MCP-Clients. Weitere Server koennen in `05-knowledge/mcp-servers.yaml` definiert werden. |
| `STUDIO_API_KEY` | _leer_ | Schuetzt `/api/config/*`, `/api/rag/*`, `/api/safety/*`, `/api/quality/*`, `/api/debug/*` und die geschuetzten `/api/sessions/*`-Routen. Leer = API offen (Dev-Default, Startup-Warnung). Siehe Abschnitt 9. |
| `CORS_ORIGINS` | `*` | Komma-separierte Liste erlaubter Origins fuer CORS. Bei `*` (Default) werden keine Credentials erlaubt. Fuer Produktion spezifische Origins setzen (z.B. `https://wirlernenonline.de,https://studio.meinedomain.de`), dann werden auch Credentials unterstuetzt. |
| `DATABASE_PATH` | `badboerdi.db` | Pfad zur SQLite-Datenbank (Sessions, Messages, Safety-Logs, Quality-Logs, RAG). |

---

## 2. Endpunkt-Inventar

Schutzstatus: **offen** = immer erreichbar · **Studio** = braucht Header `X-Studio-Key` (bzw.
`?key=`), sobald `STUDIO_API_KEY` im Backend gesetzt ist.

### Health & Debug

| Methode | Pfad | Schutz | Beschreibung |
|---------|------|--------|--------------|
| `GET` | `/api/health` | offen | Health-Check mit aktivem LLM-Provider und Modell. |
| `GET` | `/api/debug/mcp-test` | Studio | MCP-Verbindungstest (nur mit API-Key). |

### Chat (`/api/chat`)

| Methode | Pfad | Schutz | Beschreibung |
|---------|------|--------|--------------|
| `POST` | `/api/chat` | offen | Hauptendpoint. Erwartet `{session_id, message, environment, action?}`. Rueckgabe: `content`, `cards`, `quick_replies`, `pagination`, `debug`. |
| `GET`  | `/api/chat/stream` | offen | SSE-Stream-Variante des Chat-Endpoints (experimentell). |

### Sessions (`/api/sessions`)

| Methode | Pfad | Schutz | Beschreibung |
|---------|------|--------|--------------|
| `GET`  | `/api/sessions/` | Studio | Liste der letzten 100 Sessions (Studio-Inspector). |
| `GET`  | `/api/sessions/{id}` | Studio | Session-State (Persona, State, Entities, Signal-History, Turn-Count). |
| `GET`  | `/api/sessions/{id}/messages?limit=50` | offen | History fuer Cross-Page-Continuity — wird vom Widget auf jeder Seite aufgerufen. |
| `GET`  | `/api/sessions/{id}/memory` | Studio | Memory-Eintraege (optional gefiltert per `memory_type`). |
| `POST` | `/api/sessions/{id}/memory` | Studio | Memory-Eintrag speichern (`key`, `value`, `memory_type`). |

### Speech (`/api/speech`)

| Methode | Pfad | Schutz | Beschreibung |
|---------|------|--------|--------------|
| `POST` | `/api/speech/transcribe` | offen | Whisper STT — Audio-Upload → Text. |
| `POST` | `/api/speech/synthesize` | offen | OpenAI TTS — Text → Audio. |

### Config (`/api/config`) — Studio-Editoren

Alle Routen unter `/api/config/*` sind **Studio**-geschuetzt.

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `GET`    | `/api/config/files` | Liste aller Dateien im `chatbots/wlo/v1/`-Tree. |
| `GET`    | `/api/config/file?path=…` | Einzelne Datei lesen. |
| `PUT`    | `/api/config/file` | Einzelne Datei schreiben. |
| `DELETE` | `/api/config/file?path=…` | Einzelne Datei loeschen. |
| `GET`    | `/api/config/export` | JSON-Export aller Konfigurationsdateien. |
| `GET`    | `/api/config/elements` | Aggregierter Elementenbaum (Personas/Intents/Entities/Signals/States/Contexts). |
| `GET`    | `/api/config/mcp-servers` | MCP-Server-Konfiguration lesen. |
| `PUT`    | `/api/config/mcp-servers` | MCP-Server-Konfiguration schreiben. |
| `POST`   | `/api/config/mcp-servers/discover` | Tools eines MCP-Servers automatisch entdecken (SSRF-geschuetzt). |
| `POST`   | `/api/config/import` | Batch-Import (JSON, pfad-validiert). |
| `GET`    | `/api/config/backup` | Komplettes `chatbots/wlo/v1`-Tree als ZIP. |
| `POST`   | `/api/config/restore[?wipe=true]` | ZIP einspielen (merge oder wipe+restore). |

### RAG (`/api/rag`) — Wissensbereiche

Alle Routen unter `/api/rag/*` sind **Studio**-geschuetzt.

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `POST`   | `/api/rag/ingest/file` | Datei (PDF/Markdown/…) in einen Wissensbereich hochladen. |
| `POST`   | `/api/rag/ingest/url` | URL crawlen und ingesten. |
| `POST`   | `/api/rag/ingest/text` | Freitext ingesten. |
| `POST`   | `/api/rag/query` | Semantische Suche ueber einen Bereich. |
| `POST`   | `/api/rag/embed` | Embeddings fuer Chunks ohne Vektor generieren. |
| `GET`    | `/api/rag/areas` | Liste aller Wissensbereiche. |
| `GET`    | `/api/rag/area/{area}` | Details/Dokumente eines Bereichs. |
| `DELETE` | `/api/rag/area/{area}` | Bereich inkl. Embeddings loeschen. |

### Safety (`/api/safety`)

Alle Routen unter `/api/safety/*` sind **Studio**-geschuetzt.

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `GET` | `/api/safety/logs` | Geloggte Risk-Events (filterbar: `risk_min`, `session_id`). |
| `GET` | `/api/safety/stats` | Aggregierte Safety-Statistiken fuer das Studio-Dashboard. |

### Quality (`/api/quality`) — Qualitaets-Logging

Alle Routen unter `/api/quality/*` sind **Studio**-geschuetzt.
Jeder Chat-Turn wird automatisch protokolliert (konfigurierbar via `01-base/quality-log-config.yaml`).

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `GET` | `/api/quality/logs` | Quality-Logs (filterbar: `session_id`, `pattern_id`, `intent_id`, `limit`). |
| `GET` | `/api/quality/stats` | Aggregierte Metriken: Pattern-Verteilung, Intent-Verteilung, avg. Confidence, Score-Gap, Degradation-Rate, Empty-Entity-Rate, Tight Races. |

### Widget (`/widget`)

| Methode | Pfad | Schutz | Beschreibung |
|---------|------|--------|--------------|
| `GET` | `/widget/` | offen | Demo-HTML mit eingebettetem Chat. |
| `GET` | `/widget/boerdi-widget.js` | offen | Web-Component-Bundle (`<boerdi-chat>`). |
| `GET` | `/widget/{asset_name}` | offen | Weitere Assets (Chunks, Fonts, …). |

---

## 3. Konfigurationslayout — die 5 Schichten

Alle Schichten liegen unter `backend/chatbots/wlo/v1/` und werden ueber
`app/services/config_loader.py` geladen.

```
chatbots/wlo/v1/
├── 01-base/                           ← Schicht 1: Identitaet & Schutz
│   ├── base-persona.md                ←   Wer ist BOERDi? (Name, Rolle, Tonalitaet)
│   ├── guardrails.md                  ←   Harte Regeln R-01 bis R-10 (LETZTER Block im Prompt)
│   ├── safety-config.yaml             ←   Presets off/basic/standard/strict/paranoid + Rate-Limits
│   ├── quality-log-config.yaml        ←   Quality-Logging: an/aus, Retention, Alert-Schwellwerte
│   └── device-config.yaml             ←   Geraete-Limits (max_items) + Persona-Anrede (Sie/du)
│
├── 02-domain/                         ← Schicht 2: Domain & Regeln
│   ├── domain-rules.md                ←   Such-Strategie, Themenseiten, RAG-Wissensquellen, Disambiguierung
│   ├── policy.yaml                    ←   Tool-Blockaden pro Persona/Intent, Disclaimer-Texte
│   └── wlo-plattform-wissen.md        ←   Faktenwissen ueber WLO (Struktur, Angebote, Zielgruppen)
│
├── 03-patterns/                       ← Schicht 3: 20 Konversations-Patterns (siehe Abschnitt 5)
│   ├── pat-01-direkt-antwort.md
│   ├── pat-02-gefuehrte-klaerung.md
│   ├── pat-03-transparenz-beweis.md
│   ├── pat-04-inspiration-opener.md
│   ├── pat-05-profi-filter.md
│   ├── pat-06-degradation-bruecke.md
│   ├── pat-07-ergebnis-kuratierung.md
│   ├── pat-08-null-treffer.md
│   ├── pat-09-redaktions-recherche.md
│   ├── pat-10-fakten-bulletin.md
│   ├── pat-11-nachfrage-schleife.md
│   ├── pat-12-ueberbrueckungs-hinweis.md
│   ├── pat-13-schritt-fuer-schritt.md
│   ├── pat-14-eltern-empfehlung.md
│   ├── pat-15-analyse-ueberblick.md
│   ├── pat-16-themen-exploration.md
│   ├── pat-17-sanfter-einstieg.md
│   ├── pat-18-unterrichts-paket.md
│   ├── pat-19-unterrichts-lernpfad.md
│   └── pat-20-orientierungs-guide.md
│
├── 04-personas/                       ← Schicht 4a: 9 Personas (je eine Markdown-Datei)
│   ├── lk.md                          ←   P-W-LK  — Lehrkraft
│   ├── sl.md                          ←   P-W-SL  — Schueler:in
│   ├── elt.md                         ←   P-ELT   — Elternteil
│   ├── pol.md                         ←   P-W-POL — Politik
│   ├── presse.md                      ←   P-W-PRESSE — Presse
│   ├── red.md                         ←   P-W-RED — Redakteur:in
│   ├── ber.md                         ←   P-BER   — Berater:in
│   ├── ver.md                         ←   P-VER   — Verwaltung
│   └── and.md                         ←   P-AND   — Allgemein (Default)
│
├── 04-intents/                        ← Schicht 4b: 11 Intents
│   └── intents.yaml
│
├── 04-entities/                       ← Schicht 4c: 5 Entities/Slots
│   └── entities.yaml
│
├── 04-signals/                        ← Schicht 4d: 17 Signale in 4 Dimensionen
│   └── signal-modulations.yaml
│
├── 04-states/                         ← Schicht 4e: 11 Gespraechszustaende
│   └── states.yaml
│
├── 04-contexts/                       ← Schicht 4f: 5 Seitenkontexte
│   └── contexts.yaml
│
└── 05-knowledge/                      ← Schicht 5: Wissen
    ├── rag-config.yaml                ←   4 RAG-Wissensbereiche (mode: always/on-demand)
    └── mcp-servers.yaml               ←   MCP-Server-Registry (1 Server, 10 Tools)
```

Welche Datei wann in den Prompt wandert, ist im Quelltext nachvollziehbar:
`app/services/llm_service.py → generate_response()`, Variable `system_parts`.

---

## 4. Input-Dimensionen (Klassifikation)

Jede Nutzernachricht wird per LLM-Klassifikation in **7 Dimensionen** zerlegt. Diese bilden den
Input fuer die Pattern-Engine (Abschnitt 5).

### 4a. Personas (9)

Jede Persona hat eine eigene Markdown-Datei mit Erkennungshinweisen, primaeren Zielen und
Anrede-Heuristiken. Die erkannte Persona bestimmt, welche Patterns in Frage kommen (Gate) und
welche Tonalitaet/Formalitaet verwendet wird.

| ID | Label | Beschreibung |
|----|-------|-------------|
| `P-W-LK` | Lehrkraft | Sucht Unterrichtsmaterial, plant Stunden, braucht Fachdidaktik |
| `P-W-SL` | Schueler:in | Sucht Lerninhalte, braucht einfache Sprache und Ermutigung |
| `P-ELT` | Elternteil | Sucht altersgerechte Inhalte fuer das Kind, braucht Orientierung |
| `P-W-POL` | Politik | Braucht Fakten und Zahlen zu WLO, keine Materialsuche |
| `P-W-PRESSE` | Presse | Braucht zitierfaehige Fakten, keine Materialsuche |
| `P-W-RED` | Redakteur:in | Recherchiert systematisch Fachgebiete, redaktioneller Fokus |
| `P-BER` | Berater:in | Bewertet Plattform-Features, braucht Ueberblicke und Vergleiche |
| `P-VER` | Verwaltung | Braucht Zahlen, Statistiken, strukturierte Uebersichten |
| `P-AND` | Allgemein | Default-Persona fuer nicht zuordenbare Nutzer:innen |

### 4b. Intents (11)

Erkannte Absicht der Nutzernachricht. Steuert Pattern-Gates und Tool-Auswahl.

| ID | Label | Beschreibung |
|----|-------|-------------|
| `INT-W-01` | WLO kennenlernen | Was ist WLO? Was bietet die Plattform? |
| `INT-W-02` | Soft Probing | Bot klaert aktiv Bedarf, Rolle oder Kontext |
| `INT-W-03a` | Themenseite entdecken | Suche nach Fachportal, Sammlung oder Themenseite |
| `INT-W-03b` | Unterrichtsmaterial suchen | Konkrete Materialsuche (Arbeitsblaetter, Aufgaben) |
| `INT-W-03c` | Lerninhalt suchen | Lerninhalte fuer Schueler:innen/Eltern (Videos, Uebungen) |
| `INT-W-04` | Feedback | Rueckmeldung zu Ergebnissen oder zum Bot |
| `INT-W-05` | Routing Redaktion | Weiterleitung an Redaktion (Luecken, Fehler, Wuensche) |
| `INT-W-06` | Faktenfragen | Faktenfragen ueber WLO, edu-sharing oder Metaventis |
| `INT-W-07` | Material herunterladen | Konkretes Material oeffnen oder herunterladen |
| `INT-W-08` | Inhalte evaluieren | Qualitaet, Lizenz oder Eignung pruefen |
| `INT-W-09` | Analyse & Reporting | Zahlen, Statistiken, Uebersichten fuer Verwaltung/Beratung |
| `INT-W-10` | Unterrichtsplanung | Strukturierte Materialzusammenstellung fuer Unterrichtseinheit |

### 4c. Entities / Slots (5)

Aus der Nachricht extrahierte Informationsfragmente. Werden ueber Turns hinweg akkumuliert.
Zwei Patterns (PAT-18, PAT-19) haben Hard Gates auf `fach` + `stufe` + `thema`.

| ID | Label | Beispiele |
|----|-------|----------|
| `fach` | Fach / Fachgebiet | Mathematik, Deutsch, Biologie, Informatik |
| `stufe` | Bildungsstufe | Grundschule, Sek I, Klasse 7, Berufliche Bildung |
| `thema` | Thema | Bruchrechnung, Fotosynthese, Lyrik der Romantik |
| `medientyp` | Medientyp | Video, Arbeitsblatt, Simulation, Podcast |
| `lizenz` | Lizenz | CC BY, CC BY-SA, CC0, Alle OER |

**Akkumulations-Regeln pro Turn-Typ:**

| Turn-Typ | Verhalten |
|-----------|-----------|
| `initial` | keep + extend |
| `follow_up` | keep + extend |
| `clarification` | keep + extend |
| `correction` | overwrite |
| `topic_switch` | reset all |

### 4d. Signale (17 in 4 Dimensionen)

Emotionale und situative Hinweise in der Nachricht. Steuern Phase 2 (Scoring) und Phase 3
(Modulation) der Pattern-Engine. Jedes Signal hat deterministische IF-THEN-Regeln fuer
Ton, Laenge und weitere Ausgabeoptionen.

| Dimension | Signal | Tone-Override | Length | Besonderheit |
|-----------|--------|---------------|--------|-------------|
| **D1 — Zeit & Druck** | `zeitdruck` | sachlich | kurz | skip_intro |
| | `ungeduldig` | sachlich | kurz | skip_intro, reduce_items |
| | `gestresst` | beruhigend | kurz | skip_intro, reduce_items |
| | `effizient` | sachlich | kurz | skip_intro |
| **D2 — Sicherheit** | `unsicher` | empathisch | mittel | one_option |
| | `ueberfordert` | empathisch | kurz | one_option |
| | `unerfahren` | niedrigschwellig | mittel | one_option |
| | `erfahren` | sachlich | kurz | skip_intro |
| | `entscheidungsbereit` | sachlich | kurz | skip_intro |
| **D3 — Haltung** | `neugierig` | spielerisch | mittel | show_more |
| | `zielgerichtet` | sachlich | kurz | — |
| | `skeptisch` | transparent | mittel | add_sources |
| | `vertrauend` | empfehlend | mittel | — |
| **D4 — Kontext** | `orientierungssuchend` | orientierend | mittel | show_overview |
| | `vergleichend` | analytisch | mittel | — |
| | `validierend` | belegend | mittel | add_sources |
| | `delegierend` | proaktiv | mittel | — |

### 4e. States (11)

Gespraechszustand, der sich ueber die Turns hinweg entwickelt. Steuert Pattern-Gates
und bestimmt den Gespraechsfortschritt.

| ID | Label | Beschreibung |
|----|-------|-------------|
| `state-1` | Orientation | Erster Kontakt, Bot klaert Bedarf |
| `state-2` | Context Building | Bot sammelt Kontext (Fach, Stufe, Thema, Medientyp) |
| `state-3` | Information | Bot liefert Informationen ueber WLO |
| `state-4` | Navigation/Discovery | Nutzer:in erkundet Themenseiten und Sammlungen |
| `state-5` | Search | Aktive Suche nach konkreten Materialien |
| `state-6` | Result Curation | Ergebnisse werden kuratiert und praesentiert |
| `state-7` | Refinement | Suchergebnisse verfeinern oder anpassen |
| `state-8` | Learning | Nutzer:in arbeitet mit gefundenen Materialien |
| `state-9` | Evaluation/Feedback | Bot fragt nach Zufriedenheit |
| `state-10` | Redaktions-Recherche | Redakteur:in recherchiert systematisch |
| `state-11` | System/Meta | Meta-Fragen zum Bot oder zur Plattform |

### 4f. Kontexte (5)

Seitenbasierte Situationen, die aus der `environment`-Information des Widgets abgeleitet werden.
Beeinflussen Pattern-Scoring (page_bonus) und Bot-Verhalten.

| ID | Label | Trigger | Verhalten |
|----|-------|---------|-----------|
| `ctx-search-page` | Suchergebnis-Seite | `/suche`, `/startseite`, `/` | Suchbegriff aufgreifen, nicht nochmal fragen |
| `ctx-collection-detail` | Sammlungs-Detail | `/sammlung/*` | Auf angezeigte Sammlung Bezug nehmen |
| `ctx-material-detail` | Material-Detail | `/material/*` | Auf angezeigtes Material Bezug nehmen |
| `ctx-mobile-quick` | Mobile Schnellinteraktion | device=mobile, <60s Session | Maximal kurze Antworten, max. 3 Karten |
| `ctx-fachportal` | Fachportal-Seite | `/fach/*` | Fach aus Pfad ableiten, nicht nochmal fragen |

---

## 5. Pattern-Engine (3-Phasen-Modell)

Die Pattern-Engine waehlt pro Nachricht deterministisch eines von 20 Patterns aus und
moduliert die Ausgabe. Implementiert in `app/services/pattern_engine.py`.

### Phase 1: Gate-Pruefung (binaere Elimination)

Jedes Pattern definiert Gates auf Persona, State und Intent. Ein Pattern wird **eliminiert** wenn:
- Die erkannte Persona nicht in `gate_personas` ist (sofern nicht `*`)
- Der aktuelle State nicht in `gate_states` ist (sofern nicht `*`)
- Der erkannte Intent nicht in `gate_intents` ist (sofern nicht `*`)
- Definierte `precondition_slots` **nicht alle** gefuellt sind (Hard Gate)

Beispiel: PAT-19 (Unterrichts-Lernpfad) hat `precondition_slots: [fach, stufe, thema]` —
fehlt auch nur ein Slot, wird das Pattern eliminiert und PAT-18 oder PAT-06 uebernimmt.

### Phase 2: Scoring (gewichtete Rangfolge)

Unter den verbleibenden Kandidaten wird per Scoring der Gewinner ermittelt:

| Faktor | Gewicht | Erklaerung |
|--------|---------|-----------|
| Signal-Fit | 30% | Wie gut passen die erkannten Signale zu `signal_high_fit` / `signal_medium_fit` / `signal_low_fit`? |
| Context-Match | 20% | Passt die aktuelle Seite zu `page_bonus`? |
| Precondition-Completeness | 30% | Wie viele der `precondition_slots` sind gefuellt? |
| Intent-Confidence | 20% | Wie sicher ist die Intent-Klassifikation? |
| Priority-Bonus | +p/10000 | Hoeherer `priority`-Wert = kleiner Bonus bei Gleichstand |

### Phase 3: Modulation (deterministische Ausgabe-Anpassung)

Das gewinnende Pattern liefert Defaults fuer Ton, Laenge, Detailgrad und weitere Optionen.
Signale ueberschreiben diese deterministisch (IF Signal X → THEN tone=Y, length=Z).
Geraet und Persona beeinflussen max_items und Formalitaet.

**Ausgabe-Konfiguration nach Phase 3:**

| Feld | Werte | Beschreibung |
|------|-------|-------------|
| `tone` | sachlich, empathisch, spielerisch, transparent, empfehlend, einladend, beruhigend, niedrigschwellig, orientierend, analytisch, belegend, proaktiv | Tonalitaet der Antwort |
| `length` | kurz, mittel, ausfuehrlich | Antwortlaenge |
| `detail_level` | minimal, standard, ausfuehrlich | Detailtiefe |
| `formality` | neutral, du, Sie | Anrede (persona-abhaengig) |
| `response_type` | answer, question, suggestion | Art der Antwort |
| `sources` | mcp, rag | Erlaubte Wissensquellen |
| `format_primary` | text, list, cards | Primaeres Ausgabeformat |
| `format_follow_up` | quick_replies, inline, none | Gespraechsfortsetzung: Buttons / Texthaken + Buttons / keine |
| `card_text_mode` | minimal, reference, highlight | Wie Text und Kacheln zusammenspielen (siehe unten) |
| `max_items` | 3–6 | Max. Ergebnis-Karten (geraete- und signalabhaengig) |
| `tools` | Liste | Erlaubte MCP-Tools fuer dieses Pattern |
| `skip_intro` | bool | Einleitung weglassen (bei Zeitdruck) |
| `one_option` | bool | Nur 1 Option zeigen (bei Unsicherheit) |
| `add_sources` | bool | Quellen/Lizenzen explizit nennen (bei Skepsis) |

### Alle 20 Patterns im Ueberblick

| ID | Label | Prio | Kernregel | Personas | States | Intents | Precond. | Sources | Follow-Up |
|----|-------|------|-----------|----------|--------|---------|----------|---------|-----------|
| PAT-01 | Direkt-Antwort | 500 | Max. 2 Saetze + Gespraechshaken | * | * | * | — | mcp | inline |
| PAT-02 | Gefuehrte Klaerung | 450 | Exakt 1 Frage/Turn, warm + ermutigend | * | * | * | — | mcp | quick_replies |
| PAT-03 | Transparenz-Beweis | 440 | Herkunft, Lizenz, Pruefdatum nennen | LK, BER, VER, RED | * | * | — | mcp | inline |
| PAT-04 | Inspiration-Opener | 420 | 2-3 Sammlungen/Themenseiten zeigen | LK, SL, ELT, AND | 1, 4 | * | — | mcp | quick_replies |
| PAT-05 | Profi-Filter | 430 | lookup_wlo_vocabulary vorab, Filteroptionen | LK, BER | 5 | * | — | mcp | inline |
| PAT-06 | Degradation-Bruecke | 600 | Breite Suche ohne fehlende Parameter + Soft Probe | * | * | * | — | mcp | quick_replies |
| PAT-07 | Ergebnis-Kuratierung | 410 | Sammlungen als Kacheln, 1 Satz Einleitung | LK, SL, BER | 6 | * | — | mcp | quick_replies |
| PAT-08 | Null-Treffer | 590 | Ehrlich zugeben, Alternativen anbieten | * | * | * | — | mcp | quick_replies |
| PAT-09 | Redaktions-Recherche | 400 | Fachgebiet erkunden, redaktionell | RED | 10 | * | — | mcp | inline |
| PAT-10 | Fakten-Bulletin | 460 | Bullet-Facts, zitierfaehig, kein Suche-Angebot | POL, PRESSE, AND, LK, BER, VER, SL, ELT | * | 01, 06, 09 | — | rag, mcp | inline |
| PAT-11 | Nachfrage-Schleife | 380 | „Hat das gepasst?" → wenn nein: sofort Fallback | * | 9 | * | — | mcp | quick_replies |
| PAT-12 | Ueberbrueckungs-Hinweis | 580 | Transparent kommunizieren, Alternative anbieten | * | * | * | — | mcp | quick_replies |
| PAT-13 | Schritt-fuer-Schritt | 400 | Medientyp → Vokabular → gefilterte Suche | SL, ELT | * | * | — | mcp | quick_replies |
| PAT-14 | Eltern-Empfehlung | 400 | Altersgruppe + Thema → 2-3 Empfehlungen, kein Fachjargon | ELT | * | * | — | mcp | quick_replies |
| PAT-15 | Analyse-Ueberblick | 400 | Strukturierte Uebersicht, Daten + Zahlen zuerst | VER, BER, AND, LK, POL, PRESSE, SL, ELT | * | 01, 06, 09 | — | rag, mcp | inline |
| PAT-16 | Themen-Exploration | 400 | Themengebiete identifizieren, Luecken erkennen | RED, BER | 4, 10 | * | — | mcp | quick_replies |
| PAT-17 | Sanfter Einstieg | 390 | WLO-Infofragen, einladend, Persona weiter klaeren | * | 1 | * | — | rag, mcp | quick_replies |
| PAT-18 | Unterrichts-Paket | 470 | Fach+Stufe+Thema → Sammlungssuche → 3-5 Treffer | LK, AND, ELT | * | * | fach, stufe, thema | mcp | quick_replies |
| PAT-19 | Unterrichts-Lernpfad | 480 | Stundenentwurf mit Lernzielen und Zeitangaben | LK | 5, 6 | * | fach, stufe, thema | mcp | quick_replies |
| PAT-20 | Orientierungs-Guide | 480 | Faehigkeiten vorstellen, Einstiegspunkte anbieten, KEIN Tool | AND, LK, SL, ELT, BER, VER | 1, 4 | 02, 01 | — | — | quick_replies |

**Legende Personas:** LK=Lehrkraft, SL=Schueler:in, ELT=Eltern, POL=Politik, PRESSE=Presse, RED=Redaktion, BER=Beratung, VER=Verwaltung, AND=Allgemein

**Priority-Hierarchie (hoeher = bevorzugt bei Gleichstand):**
- 600: PAT-06 (Degradation) — universeller Fallback
- 580–590: PAT-12 (Ueberbrueckung), PAT-08 (Null-Treffer) — Fehlerbehandlung
- 470–500: PAT-01, PAT-18, PAT-19, PAT-20 — Kern-Use-Cases
- 400–460: PAT-02 bis PAT-17 — situative Patterns
- 380–390: PAT-11, PAT-17 — niedrigste Prioritaet

### card_text_mode — Text vs. Kacheln

Steuert, wie der Antworttext mit den Material-Kacheln zusammenspielt und verhindert
doppelte Informationsdarstellung:

| Wert | Verhalten | Patterns |
|------|-----------|----------|
| `minimal` | Text ist nur eine kurze Einleitung (1-2 Saetze). Keine Materialtitel oder -beschreibungen im Text. Kacheln tragen alle Material-Details. | PAT-01, PAT-05, PAT-06, PAT-07, PAT-08, PAT-10, PAT-11, PAT-12, PAT-13, PAT-15, PAT-17, PAT-20 |
| `reference` | Text darf Materialien namentlich nennen und didaktisch einordnen (Reihenfolge, Lernziele, Zeitangaben). Beschreibungen und Metadaten kommen nur ueber die Kacheln. | PAT-18, PAT-19 |
| `highlight` | Text darf 1-2 Materialien hervorheben und kurz begruenden warum sie besonders passen. Nicht alle einzeln auflisten. | PAT-02, PAT-03, PAT-04, PAT-09, PAT-14, PAT-16 |

### format_follow_up

Steuert, wie Gespraechsfortsetzung angeboten wird:

| Wert | Verhalten |
|------|-----------|
| `quick_replies` | LLM generiert 2-4 klickbare Vorschlaege (aus User-Perspektive formuliert) |
| `inline` | LLM schreibt Gespraechshaken in den Antworttext UND generiert Quick Replies |
| `none` | Keine Vorschlaege (derzeit bei keinem Pattern verwendet) |

---

## 6. Output-Struktur (ChatResponse)

Jede Antwort von `POST /api/chat` liefert folgende Felder:

```json
{
  "session_id": "uuid",
  "content": "Antworttext des Bots (Markdown-formatiert)",
  "cards": [
    {
      "node_id": "...",
      "title": "Materialname",
      "description": "Kurzbeschreibung",
      "disciplines": ["Mathematik"],
      "educational_contexts": ["Sekundarstufe I"],
      "keywords": ["Bruchrechnung"],
      "learning_resource_types": ["Arbeitsblatt"],
      "url": "https://...",
      "wlo_url": "https://wirlernenonline.de/...",
      "preview_url": "https://...",
      "license": "CC BY-SA 4.0",
      "publisher": "...",
      "node_type": "content | collection",
      "topic_pages": [{"url": "...", "target_group": "teacher", "label": "Lehrkraefte"}]
    }
  ],
  "follow_up": "quick_replies | inline | none",
  "quick_replies": ["Zeig mir mehr davon", "Ich will das eingrenzen", "Anderes Thema"],
  "pagination": {
    "total_count": 42,
    "skip_count": 0,
    "page_size": 5,
    "has_more": true,
    "collection_id": "...",
    "collection_title": "..."
  },
  "page_action": null,
  "debug": { "...siehe Abschnitt 11..." }
}
```

**Felder im Detail:**

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| `content` | String | Markdown-formatierte Antwort. Laenge und Ton werden durch Pattern + Signale gesteuert. |
| `cards` | Array | WLO-Materialkarten mit Metadaten, Preview-URLs und Themenseiten-Links. Leer bei reinen Textantworten. |
| `follow_up` | String | Modus der Gespraechsfortsetzung (vom Pattern bestimmt). |
| `quick_replies` | Array | 2-4 klickbare Vorschlaege aus **User-Perspektive** (z.B. „Zeig mir mehr davon", nicht „Weitere Ergebnisse anzeigen"). Mix aus Vertiefung, Richtungswechsel, Fortsetzung und offener Frage. |
| `pagination` | Object | Nur bei paginierten Ergebnissen. Ermoeglicht „Mehr laden"-Button im Widget. |
| `page_action` | Object | Optionale Aktion fuer die Host-Seite (navigate, show_collection, share_content). |
| `debug` | Object | Vollstaendiger Trace des Request-Lifecycles (siehe Abschnitt 11). |

---

## 7. MCP & RAG — Wissensquellen

### MCP-Server (externe Tools)

Aktuell 1 Server: **WLO edu-sharing** mit 10 Tools.

| Tool | Kategorie | Beschreibung |
|------|-----------|-------------|
| `search_wlo_collections` | Suche | Sammlungen nach Fach/Thema/Stufe durchsuchen |
| `search_wlo_content` | Suche | Einzelne Materialien durchsuchen |
| `search_wlo_topic_pages` | Suche | Themenseiten mit Zielgruppen-Varianten (teacher/learner/general) |
| `get_collection_contents` | Navigation | Inhalte einer Sammlung abrufen |
| `get_node_details` | Details | Metadaten eines einzelnen Materials abrufen |
| `lookup_wlo_vocabulary` | Hilfs-Tool | WLO-Fachvokabular nachschlagen (Disziplinen, Bildungsstufen, Medientypen) |
| `get_wirlernenonline_info` | Info | Fakten ueber WirLernenOnline |
| `get_edu_sharing_product_info` | Info | Fakten ueber edu-sharing (Produkt) |
| `get_edu_sharing_network_info` | Info | Fakten ueber edu-sharing.net e.V. (Netzwerk) |
| `get_metaventis_info` | Info | Fakten ueber Metaventis GmbH |

**Tool-Abhaengigkeit:** Wenn ein Suche-Tool aktiviert ist, werden `lookup_wlo_vocabulary` und
`get_node_details` automatisch hinzugefuegt (Code-Logik in Phase 3).

Server werden in `05-knowledge/mcp-servers.yaml` registriert. Im Studio koennen neue Server
per URL hinzugefuegt werden — die verfuegbaren Tools werden automatisch per MCP-Handshake
entdeckt.

### RAG-Wissensbereiche

4 Bereiche, alle im Modus `always` (werden bei jeder Nachricht als Kontext vorab durchsucht):

| Bereich | Chunks | Inhalt |
|---------|--------|--------|
| `edu-sharing-com-webseite` | 54 | edu-sharing als Open-Source-Loesung fuer Bildungscloud und Content-Management |
| `edu-sharing-net-webseite` | 37 | edu-sharing.net e.V. — gemeinnuetziges Netzwerk fuer digitale Bildungsclouds und OER |
| `wirlernenonline.de-webseite` | 106 | WirLernenOnline — offene Bildungsplattform mit Suchmaschine und Fachportalen |
| `wissenlebtonline-webseite` | 151 | WLO-Oekosystem — KI-gestuetzte Infrastruktur fuer Bildungsinhalte |

**Always-On-Ablauf:** Vor dem LLM-Call werden alle `always`-Bereiche per Embedding-Suche
durchsucht (Top 8 Chunks, min_score 0.25). Das Ergebnis wird als synthetisches Tool-Call/Result-Paar
in die Nachrichtenhistorie injiziert. Das LLM erhaelt die Chunks als Kontext und wird angewiesen,
bereits durchsuchte Bereiche nicht nochmal per `query_knowledge` abzurufen.

Konfiguration: `05-knowledge/rag-config.yaml`. Seed-Daten: `knowledge/rag-seed.json` (siehe
Deployment-Doku Abschnitt 4).

---

## 8. Safety-Pipeline (Triple-Schema v2)

Die Safety laeuft **vor** dem LLM-Call und kann Tools sperren oder Patterns erzwingen
(z.B. `PAT-CRISIS`).

```
Regex-Gate (immer)
   │
   ▼
OpenAI-Moderation  (mode: smart/always — in Presets festgelegt)
   │
   ▼
Legal-Classifier (gpt-4.1-mini)  (smart: nur bei Trigger-Treffer / always: jeder Turn)
   │
   ▼
Confidence-Adjustment aus Tool-Outcomes
```

Konfiguration: `chatbots/wlo/v1/01-base/safety-config.yaml`

* `security_level`: `off | basic | standard | strict | paranoid`
* `presets.*`: definieren `moderation`, `legal_classifier`, `prompt_injection`,
  optional `threshold_multiplier` und `double_check`
* `escalation.legal_thresholds.flag` / `.high`: Schwellwerte fuer den Legal-Classifier
* `escalation.thresholds.*`: Schwellwerte je Moderation-Kategorie
* `crisis_blocked_tools`: Tools, die bei Crisis-Pattern blockiert werden

## 9. Rate Limits & Concurrency

`safety-config.yaml → rate_limits` — Sliding-Window pro Session und pro IP, plus
optionale IP-Whitelist. Defaults fuer 50 parallele Nutzer:

```yaml
per_session:
  enabled: true
  requests_per_minute: 30
  requests_per_hour: 600
per_ip:
  enabled: true
  requests_per_minute: 300
  requests_per_hour: 3000
```

Pro Session-ID gibt es einen `asyncio.Lock` (`app/routers/chat.py`), sodass parallele Requests
einer Session strikt sequentiell verarbeitet werden — verschiedene Sessions laufen parallel.

---

## 10. Widget-Auslieferung

`app/routers/widget.py` liest das Widget-Bundle in dieser Reihenfolge:

1. **`frontend/dist/widget/browser/main.js`** — Standard im Mono-Repo (kein Kopieren noetig).
2. **`backend/widget_dist/main.js`** — Fallback fuer isolierte Backend-Deploys.

Build-Optionen aus dem Repo-Root:

```bash
# Variante A — Mono-Repo / lokal (Default, kein Kopieren)
./scripts/build-widget.sh        # Linux/macOS
.\scripts\build-widget.ps1       # Windows

# Variante B — Backend isoliert deployen (mit Kopie nach backend/widget_dist/)
./scripts/sync-widget-to-backend.sh
.\scripts\sync-widget-to-backend.ps1
```

Falls das Bundle in beiden Verzeichnissen fehlt, antwortet `/widget/boerdi-widget.js` mit `503`
und einer expliziten Anleitung.

---

## 11. Authentifizierung, Sicherheit & Backup

### API-Key-Schutz

Schreibende und konfigurations-nahe Endpunkte koennen per Umgebungsvariable geschuetzt werden:

```bash
export STUDIO_API_KEY=geheim123          # Linux/macOS
$env:STUDIO_API_KEY="geheim123"          # PowerShell
```

Ist `STUDIO_API_KEY` leer oder ungesetzt, bleibt die API **offen** (Dev-Default). Beim Start wird
eine **Warnung** geloggt, damit dieser Zustand in Produktion nicht unbemerkt bleibt. Ist sie gesetzt,
verlangen folgende Routen den Header `X-Studio-Key: <wert>` (oder alternativ `?key=<wert>`):

* `GET/PUT/DELETE /api/config/*`
* `GET/PUT /api/rag/*`
* `GET/PUT /api/safety/*`
* `GET /api/debug/mcp-test`
* alle `/api/sessions/*`-Routen **ausser** `GET /{id}/messages`

**Bewusst offen** bleiben auch mit gesetztem Key:

* `POST /api/chat` — sonst koennte das Widget nicht chatten
* `/api/speech/*` — Whisper/TTS im Widget
* `/widget/*` — Bundle- und Demo-Auslieferung
* `GET /api/sessions/{id}/messages` — Cross-Page-History des Widgets

### Sicherheitsmassnahmen

| Massnahme | Beschreibung |
|-----------|-------------|
| **Path-Traversal-Schutz** | Alle Config-Dateioperationen (lesen/schreiben/loeschen/import) validieren relative Pfade gegen `CHATBOT_DIR` via `path.resolve().relative_to()`. `../`-Escapes werden blockiert. |
| **SSRF-Schutz** | Der MCP-Server-Discovery-Endpoint (`POST /mcp-servers/discover`) blockiert private, loopback und link-local IP-Adressen. |
| **CORS-Konfiguration** | `CORS_ORIGINS=*` (Default) deaktiviert `allow_credentials`. Fuer Produktion spezifische Origins setzen. |
| **Chat-Nachrichtenlimit** | `ChatRequest.message` ist auf 10.000 Zeichen begrenzt (Pydantic-Validierung). |
| **ZIP-Restore-Schutz** | `/api/config/restore` prueft ZIP-Eintraege auf absolute Pfade und `..`-Segmente. |
| **Startup-Warnung** | Fehlt `STUDIO_API_KEY`, loggt das Backend beim Start eine deutliche Warnung. |

### Backup & Restore der Konfiguration

```bash
# Komplettes chatbots/wlo/v1-Tree als ZIP ziehen
curl -H "X-Studio-Key: $STUDIO_API_KEY" \
     -o wlo-v1-backup.zip \
     http://localhost:8000/api/config/backup

# Restore (merge ueber bestehende Dateien)
curl -H "X-Studio-Key: $STUDIO_API_KEY" \
     -F "file=@wlo-v1-backup.zip" \
     http://localhost:8000/api/config/restore

# Restore mit vorherigem Leeren (wipe) des Trees
curl -H "X-Studio-Key: $STUDIO_API_KEY" \
     -F "file=@wlo-v1-backup.zip" \
     "http://localhost:8000/api/config/restore?wipe=true"
```

---

## 12. LLM-Provider & Einschraenkungen

Das Backend spricht drei OpenAI-kompatible Provider, umschaltbar per `LLM_PROVIDER`. **Default ist `openai`** — wenn die Variable leer oder nicht gesetzt ist, laeuft alles wie bisher mit OpenAI nativ.

| Provider | Chat-Default | Embed-Default | Auth |
|----------|--------------|---------------|------|
| `openai` _(Standard)_ | `gpt-4.1-mini` | `text-embedding-3-small` | `OPENAI_API_KEY` |
| `b-api-openai` | `gpt-4.1-mini` | `text-embedding-3-small` | `B_API_KEY` (Header `X-API-KEY`) |
| `b-api-academiccloud` | `Qwen/Qwen3.5-122B-A10B-GPTQ-Int4` | `e5-mistral-7b-instruct` | `B_API_KEY` |

Modelle per `LLM_CHAT_MODEL` / `LLM_EMBED_MODEL` ueberschreibbar. Implementiert in `app/services/llm_provider.py`.

### Beispiel-Setups

```bash
# Default (= ohne LLM_PROVIDER):
export OPENAI_API_KEY=sk-...

# B-API → OpenAI (gleiche Modelle, aber ueber die WLO-Proxy-Infrastruktur)
export LLM_PROVIDER=b-api-openai
export B_API_KEY=bb6cdf84-0a9d-47f3-b673-c1b4f25b9bdc

# B-API → AcademicCloud (Open-Source-Modelle, GWDG-Hosting)
export LLM_PROVIDER=b-api-academiccloud
export B_API_KEY=bb6cdf84-0a9d-47f3-b673-c1b4f25b9bdc
# optional anderes AcademicCloud-Modell:
export LLM_CHAT_MODEL=meta-llama-3.1-8b-instruct
```

### Was bei B-API NICHT mehr funktioniert

Die B-API bietet nur `chat/completions` und `embeddings` an. Folgende Funktionen sind daran gebunden, dass `LLM_PROVIDER=openai` UND `OPENAI_API_KEY` vorhanden sind:

| Feature | Code-Anker | Verhalten ohne native OpenAI |
|---------|-----------|------------------------------|
| **Whisper STT** | `routers/speech.py` | Mikrofon-Button im Widget tot, sofern kein zusaetzlicher OpenAI-Key vorliegt. |
| **TTS** | `routers/speech.py` | Vorlese-Funktion deaktiviert. |
| **Stage-2 Moderation** | `services/safety_service.py` | Wird uebersprungen. Stage 1 (Regex) und Stage 3 (Legal-Classifier) bleiben aktiv. |
| **RAG-Vektor-Kompatibilitaet** | `services/rag_service.py` | `e5-mistral-7b-instruct` (1024 dim) ≠ `text-embedding-3-small` (1536 dim). **Bestehende Embeddings sind nach einem Wechsel zu `b-api-academiccloud` unbrauchbar — alle Dokumente neu indexieren.** |
| **Tool-/Function-Calling** | `services/llm_service.py` | Bei `b-api-openai` voll funktional. Bei `b-api-academiccloud` modellabhaengig. |
| **JSON-Mode** | `services/safety_service.py` | OpenAI/B-API-OpenAI: garantiert. AcademicCloud: nicht garantiert. |

**Empfehlung:**
* **Volle Feature-Paritaet:** `openai` (Standard) oder `b-api-openai`.
* **Datenschutz / EU-Hosting:** `b-api-academiccloud` (mit Einschraenkungen, siehe oben).

---

## 13. Datenbank

SQLite (`badboerdi.db`) mit folgenden Tabellen:

| Tabelle | Zweck |
|---------|-------|
| `sessions` | Session-State (Persona, State, Entities, Signals, Turn-Count) |
| `messages` | Nachrichtenverlauf pro Session (inkl. `debug_json` und `cards_json`) |
| `memory` | Key-Value-Speicher pro Session (short/long) |
| `safety_logs` | Geloggte Risk-Events (Risk-Level, Stages, Legal-Flags, Escalation) |
| `quality_logs` | Qualitaets-Metriken pro Turn (Pattern, Scores, Confidence, Degradation, Entities, Tool-Outcomes) |
| `rag_chunks` | RAG-Text-Chunks mit Embeddings (sqlite-vec, 1536 Dimensionen) |
| `meta` | Key-Value fuer System-Metadaten (z.B. Seed-Version) |

Init in `app/services/database.py`. Beim ersten Start werden Seed-Chunks aus
`knowledge/rag-seed.json` importiert (versioniert, siehe Deployment-Doku).

---

## 14. Debug-Output

Jede `/api/chat`-Antwort enthaelt ein `debug`-Objekt mit:

* `persona` — z.B. `P-W-LK (Lehrkraft)` — ID mit Label in Klammern
* `intent` — z.B. `INT-W-06 (Faktenfragen)` — ID mit Label
* `state` — z.B. `state-3 (Information)` — ID mit Label
* `turn_type` — `initial`, `follow_up`, `topic_switch`, `correction`, `clarification`
* `signals` — erkannte Signale (z.B. `["zielgerichtet", "Faktenfrage"]`)
* `pattern` — z.B. `PAT-10 (Fakten-Bulletin)` — Gewinner-Pattern
* `entities` — extrahierte Slots (interne `_`-Keys werden gefiltert)
* `tools_called` — tatsaechlich aufgerufene Tools (inkl. prefetch)
* `phase1_eliminated` — durch Gate eliminierte Patterns
* `phase2_scores` — Score pro Kandidat-Pattern
* `phase3_modulations` — vollstaendiger Output der Modulations-Phase:
  - `tone`, `formality`, `length`, `detail_level`, `max_items`, `card_text_mode`
  - `response_type`, `format_primary`, `format_follow_up`, `sources`
  - `tools` (Pattern-definierte Tools), `rag_areas`, `core_rule`
  - `skip_intro`, `one_option`, `add_sources` (Boolean-Flags)
  - `degradation`, `missing_slots`, `blocked_patterns`
* `outcomes` — Tool-Outcomes mit Status, Item-Count und Latenz
* `safety` — Stages, Risk-Level, Categories, Legal-Flags, Escalated
* `policy` — Allowed/Blocked-Tools/Disclaimers
* `context` — ContextSnapshot (Page, Device, Turn-Count)
* `confidence` — Finale Confidence nach allen Adjustments
* `trace` — Phase-Trace mit Dauer pro Schritt

Das Frontend rendert dieses Objekt im Debug-Panel (Toggle via 🔍 im Header);
das Studio nutzt es fuer Sessions-Inspektion. Zusaetzlich wird jeder Turn
automatisch in die `quality_logs`-Tabelle geschrieben (siehe Abschnitt 15).

---

## 15. Quality-Logging

Jeder Chat-Turn wird automatisch in `quality_logs` protokolliert (non-blocking, fire-and-forget).
Steuerung ueber `01-base/quality-log-config.yaml`:

```yaml
logging:
  enabled: true              # An/Aus (Standard: true)
  retention_days: 180
```

**Gespeicherte Metriken pro Turn:**

| Feld | Beschreibung |
|------|-------------|
| `pattern_id` | Gewaehltes Pattern |
| `phase2_winner_score` | Score des Gewinners |
| `phase2_score_gap` | Abstand zum Zweitplatzierten (niedrig = ambig) |
| `intent_id`, `persona_id` | Klassifikationsergebnis |
| `final_confidence` | Finale Confidence nach Outcome-Adjustments |
| `turn_type` | initial / follow_up / topic_switch / correction |
| `signals`, `entities` | Erkannte Signale und Slots |
| `tools_called`, `tool_outcomes` | Aufgerufene Tools mit Status |
| `response_length`, `cards_count` | Antwortlaenge und Kartenanzahl |
| `degradation`, `missing_slots` | Ob Degradation aktiv war |
| `debug_json` | Vollstaendiges Debug-Objekt fuer Deep-Dive |

**Aggregierte Statistiken** ueber `GET /api/quality/stats`:
- Pattern-Verteilung, Intent-Verteilung
- Durchschnittliche Confidence und Score-Gap
- Degradation-Rate, Empty-Entity-Rate
- Anzahl Tight Races (Score-Gap < 0.02 — Pattern-Entscheidung war knapp)
