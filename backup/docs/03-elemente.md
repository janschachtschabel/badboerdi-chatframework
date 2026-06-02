# Elemente und ihre Wechselwirkungen

## Uebersicht

Das BadBoerdi-Framework arbeitet mit **7 Kernelementen** (aktiv bei jeder Nachricht) und **4 Laufzeit-Elementen** (dynamisch erzeugt). Zusammen bilden sie das **Triple-Schema v2** — ein deterministisches Steuerungssystem, das den LLM-Prompt nicht nur inhaltlich, sondern auch stilistisch und strukturell formt.

---

## Die 7 Kernelemente

### 1. Persona

**Datei:** `04-personas/*.md` (9 Stueck)

| ID | Label | Anrede |
|----|-------|--------|
| P-W-LK | Lehrkraft | wie_user (Sie Standard) |
| P-W-SL | Schüler:in | duzen (Override aktiv) |
| P-ELT | Eltern | wie_user (Sie Standard) |
| P-W-POL | Politiker:in | siezen (Override aktiv) |
| P-W-PRESSE | Presse/Journalist:in | siezen (Override aktiv) |
| P-W-RED | Redaktion | wie_user (Sie Standard) |
| P-BER | Berater:in | wie_user (Sie Standard) |
| P-VER | Verwaltung | siezen (Override aktiv) |
| P-AND | Sonstige/Unbekannt | duzen (BOERDi-Default) |

**Tonalität-Steuerung (Welle B.3):** Jede Persona hat im Frontmatter
(z.B. `04-personas/lk.md`) fünf Modifier-Felder: `tone`, `length_bias`,
`formality`, `card_text_mode`, `override`. Diese werden von der
Pattern-Engine in Phase 3 angewendet. Studio-Pflege im Persona-Editor
über das Form-UI über dem Markdown-Editor.

**Wirkung:**
- Bestimmt Anrede (Sie/du/neutral) aus `device-config.yaml`
- Filtert Pattern-Gates (`gate_personas`)
- Aktiviert Policy-Regeln (z.B. Presse-Disclaimer, Tool-Blockaden)
- Steuert persona-spezifischen Prompt-Abschnitt (z.B. Lehrkraft bekommt didaktische Tipps)

---

### 2. Intent

**Datei:** `04-intents/intents.yaml` (13 Stück, Stand Welle C Sprint 4)

| ID | Label | Typische Aktion |
|----|-------|-----------------|
| INT-W-01 | WLO kennenlernen | Plattform-Info aus RAG |
| INT-W-02 | Erst-Orientierung ohne Anliegen | Bot fragt nach Bedarf (PAT-20) |
| INT-W-03 | Inhalte abrufen | universell für Themenseiten/Sammlungen/Einzelinhalte — Pattern wählt Tool: `search_wlo_topic_pages` / `search_wlo_collections` / `search_wlo_content` |
| INT-W-04 | Feedback | Kein Tool, Dank/Weiterleitung |
| INT-W-05 | Routing Redaktion | Weiterleitung an Redaktion |
| INT-W-06 | Faktenfragen | MCP-Info-Tools (WLO, edu-sharing) |
| INT-W-08 | Inhalte evaluieren | `get_node_details` + RAG |
| INT-W-09 | Analyse & Reporting | `search_wlo_collections` + Statistik |
| INT-W-10 | Unterrichtsplanung | `search_wlo_collections` + `search_wlo_content` (mehrstufiger Lernpfad) |
| INT-W-11 | Inhalt erstellen | Canvas-Create (PAT-21) |
| INT-W-12 | Canvas-Edit | Verfeinerung bestehender Canvas-Inhalte |
| INT-W-13 | Fachportal-Übersicht | `get_subject_portals` (Plural-Frage) |
| INT-W-14 | Themen-Drilldown | `browse_collection_tree` (in EINE Sammlung tiefer) |

**Historische Hinweise (Welle C Sprint 4, 2026-05-15):**
- **INT-W-03a/03b/03c** (Themenseite/Material/Lerninhalt) wurden in **INT-W-03 "Inhalte abrufen"** konsolidiert. Pattern-Wahl (PAT-28 / PAT-07 / PAT-14 / PAT-09) erfolgt deterministisch über Anker-Wörter + Persona.
- **INT-W-07 "Material herunterladen"** wurde gelöscht: technisch identisch mit INT-W-03 (Bot sucht im Repo, gibt Link — kein eigener File-Download).

**Wirkung:**
- Bestimmt, welche MCP-Tools der LLM bevorzugt aufruft
- Filtert Pattern-Gates (`gate_intents`)
- Löst spekulative Vorab-Abfragen aus (INT-W-03 und INT-W-10)
- Steuert Entity-Akkumulation (welche Slots werden erwartet?)

---

### 3. Signal

**Datei:** `04-signals/signal-modulations.yaml` (17 Signale in 4 Dimensionen)

| Dimension | Signale |
|-----------|---------|
| D1 — Zeit & Druck | zeitdruck, ungeduldig, gestresst, effizient |
| D2 — Sicherheit | unsicher, ueberfordert, unerfahren, erfahren, entscheidungsbereit |
| D3 — Haltung | neugierig, zielgerichtet, skeptisch, vertrauend |
| D4 — Kontext | orientierungssuchend, vergleichend, validierend, delegierend |

**Wirkung (deterministische IF-THEN-Regeln):**

| Signal | Ton | Laenge | skip_intro | one_option | Sonstiges |
|--------|-----|--------|------------|------------|-----------|
| zeitdruck | sachlich | kurz | ja | | |
| ungeduldig | sachlich | kurz | ja | | reduziert max_items |
| gestresst | beruhigend | kurz | ja | | reduziert max_items |
| unsicher | empathisch | mittel | | ja | |
| ueberfordert | empathisch | kurz | | ja | |
| unerfahren | niedrigschwellig | mittel | | ja | |
| neugierig | spielerisch | mittel | | | show_more |
| skeptisch | transparent | mittel | | | add_sources |
| orientierungssuchend | orientierend | mittel | | | show_overview |
| validierend | belegend | mittel | | | add_sources |

**Kombinationsregeln:**
- Mehrere Signale koennen gleichzeitig aktiv sein
- Bei Konflikten gilt: kuerzere Laenge gewinnt, restriktiveres Verhalten gewinnt
- `reduce_items_signals` (ungeduldig, gestresst) halbieren die Kartenanzahl

---

### 4. Entity (Slot)

**Datei:** `04-entities/entities.yaml` (5 Slots)

| ID | Label | Beispiel |
|----|-------|---------|
| fach | Fach/Fachgebiet | Mathematik, Biologie, Informatik |
| stufe | Bildungsstufe | Grundschule, Sek I, Klasse 7 |
| thema | Thema | Bruchrechnung, Fotosynthese |
| medientyp | Medientyp | Video, Arbeitsblatt, Simulation |
| lizenz | Lizenz | CC BY, CC BY-SA, CC0 |

**Wirkung:**
- Entities werden als **Such-Parameter** an MCP-Tools weitergegeben
- Sie werden **ueber Turns akkumuliert** (Entity-Memory)
- Akkumulationsregeln:
  - `initial` / `follow_up` / `clarification` → bestehende Werte behalten + neue ergaenzen
  - `correction` → vorhandene Werte ueberschreiben
  - `topic_switch` → alle Slots zuruecksetzen
- Spekulative Vorab-Abfragen nutzen extrahierte Entities (`thema` > `fach` > `query`) als Suchbegriff

---

### 5. State (Gespraechszustand)

**Datei:** `04-states/states.yaml` (11 Zustaende nach Welle C Sprint 6 — state-10 entfernt)

```
state-1  Orientierung          → Erster Kontakt, Bot sondiert offen
state-2  Slot-Erfassung        → Bot fragt nach fehlendem Slot (1 Frage)
state-3  Information           → Bot beantwortet Fakten/Konzept-Frage
state-4  Erkundung             → Themenseiten/Sammlungen browsen
state-5  Suche                 → Aktive Materialsuche (Tool-Call)
state-6  Ergebnis-Kuratierung  → Bot bestätigt + fragt nach Pass
state-7  Verfeinerung          → Bot adjustiert Filter
state-8  Lernen & Arbeiten     → Bot hilft bei Anwendung
state-9  Bewertung & Feedback  → Bot paraphrasiert + probt
state-11 System & Meta         → Bot erklärt sich/Plattform
state-12 Canvas-Arbeit         → Bot editiert Canvas iterativ
```

**Welle C Sprint 6 (2026-05-16) — State als Conversation Flow Machine:**

States modellieren jetzt **Gesprächs-Verlaufs-Phasen** (nicht zweite Klassifikations-Achse zum Intent). Pattern wählt WAS gesagt wird + welche Tools, State sagt in welchem Verlaufs-Schritt das einzahlt.

Jeder State hat:
- `role` — welche Rolle nimmt der Bot in dieser Phase
- `bot_directive` — konkrete Handlungs-Anweisung, wird in den Response-Prompt eingebaut
- `next_likely` — plausible Nachfolge-States (für Plausibilitäts-Validator)

**Wirkung:**
- `bot_directive` steuert die LLM-Antwort-Generierung (was als Verlaufs-Schritt jetzt drankommt)
- `next_likely` validiert implausible Übergänge (z.B. state-12 → state-3 ohne Reset)
- Quick-Reply-Generator nutzt State für phase-spezifische QRs
- Pattern-Gates (`gate_states`) bleiben bestehen, sind aber meist `*` (State ist kein Pattern-Selektor)

---

### 6. Pattern (Gespraechsmuster)

**Datei:** `03-patterns/*.md` (23 Patterns)

**Pattern-Engine (3 Phasen):**
1. **Gate-Pruefung** — Passt Persona, State, Intent? UND: Sind alle `precondition_slots` gefuellt? (`precondition_slots` ist ein **Hard Gate** — fehlt ein geforderter Slot, wird das Pattern eliminiert, nicht nur schlechter bewertet)
2. **Scoring** — Signal-Fit-Gewichte + Page-Bonus + Entity-Vollstaendigkeit → gewichteter Score
3. **Modulation** — Signale ueberschreiben Defaults (Ton, Laenge, skip_intro)

| ID | Label | Typischer Einsatz |
|----|-------|--------------------|
| PAT-01 | Direkt-Antwort | Schnelle, knappe Antworten |
| PAT-02 | Gefuehrte Klaerung | Bot stellt Rueckfrage |
| PAT-03 | Transparenz-Beweis | Quellenangaben betont |
| PAT-04 | Inspiration-Opener | Explorativer Einstieg |
| PAT-05 | Profi-Filter | Erfahrene Nutzer, praezise Filterung |
| PAT-06 | Degradation-Bruecke | Fallback bei fehlenden Daten |
| PAT-07 | Ergebnis-Kuratierung | Kartenbasierte Ergebnisliste |
| PAT-08 | Null-Treffer | Kein Ergebnis → alternative Vorschlaege |
| PAT-09 | Redaktions-Recherche | Systematische Fachrecherche (nur RED) |
| PAT-10 | Fakten-Bulletin | Kurze Faktenantwort |
| PAT-14 | Lerner-Empfehlung | Speziell für Schüler:innen/Eltern (Welle B.2: Merge aus PAT-13 + PAT-14) |
| PAT-18 | Unterrichts-Paket | Materialzusammenstellung (precondition: thema) |
| PAT-19 | Unterrichts-Lernpfad | Strukturierter Lernpfad (precondition: thema) |
| PAT-20 | Orientierungs-Guide | "Was kann ich hier" mit konkreten Beispielen (kein MCP) |
| PAT-21 | Canvas-Create | Neues Material KI-generiert im Canvas (precondition: thema+material_typ, INT-W-11) |
| PAT-22 | Feedback-Echo | Nutzer-Feedback bestätigen + Folge-Angebot (INT-W-04) |
| PAT-23 | Redaktions-Routing | Lücken/Fehler an Redaktion weiterleiten (INT-W-05) |
| PAT-25 | Canvas-Edit-Dialog | Verfeinerung bestehender Canvas-Inhalte (INT-W-12) |
| PAT-26 | Fachportale-Übersicht | get_subject_portals — alle Fächer (INT-W-13) |
| PAT-27 | Themen-Drilldown | browse_collection_tree in EINE Sammlung (INT-W-14) |
| PAT-28 | Themenseiten-Suche | search_wlo_topic_pages bei "Themenseite zu X" (INT-W-03) |
| PAT-CRISIS | Crisis-Empathie | Notfall-Pattern: Bei Krisen-Signalen sofort deeskalieren |
| PAT-REFUSE-THREAT | Refuse-Threat | Abweisung von Bedrohungs-/Policy-Verletzungen |

**Welle B/C Konsolidierungen** (gestrichen oder gemerged):
- PAT-11 (Nachfrage-Schleife) → gestrichen (tot: state-9-only, nie erreicht)
- PAT-12 (Überbrückungs-Hinweis) → gestrichen (kein Trigger)
- PAT-13 (Schritt-für-Schritt) → in PAT-14 gemerged (Lerner-Empfehlung)
- PAT-15 (Analyse-Überblick) → in PAT-10 gemerged (Fakten-Bulletin)
- PAT-16 (Themen-Exploration) → in PAT-09 gemerged (Recherche)
- PAT-17 (Sanfter Einstieg) → in PAT-20 gemerged (Orientierungs-Guide)
- PAT-24 (Download-Hinweis) → in PAT-07 gemerged (Sub-Modus „Download")

**Wirkung:**
- Bestimmt Antwortstruktur (Ton, Laenge, Detailgrad)
- Steuert Tool-Zugang (`sources`, `tools`)
- Wird als einziges Pattern in den Prompt eingefuegt

---

### 7. Kontext (Page-Context)

**Datei:** `04-contexts/contexts.yaml` (4 Kontexte)

| ID | Label | Trigger |
|----|-------|---------|
| ctx-search-page | Suchergebnis-Seite | Pfad: /suche, /startseite |
| ctx-collection-detail | Sammlungs-Detailseite | Pfad: /sammlung/* |
| ctx-material-detail | Material-Detailseite | Pfad: /material/* |
| ctx-mobile-quick | Mobile Schnellinteraktion | Device: mobile + Session < 60s |

**Wirkung:**
- Gibt Pattern-Scoring einen Page-Bonus
- Mobile-Kontext verkuerzt Antworten automatisch
- Seitenkontext wird vom Widget automatisch erfasst (`auto-context="true"`)

---

## Die 4 Laufzeit-Elemente

Diese Elemente werden nicht in YAML definiert, sondern zur Laufzeit erzeugt:

### 8. Safety-Entscheidung

**Erzeugt von:** `safety_service.assess_safety()`

**Felder:**
- `risk_level`: low | medium | high
- `blocked_tools`: Liste gesperrter Tools (z.B. bei Krisen-Erkennung)
- `enforced_pattern`: Erzwungenes Pattern (z.B. `PAT-CRISIS` bei selbstbezogenen Krisen, `PAT-REFUSE-THREAT` bei Drohungen gegen Dritte)
- `disclaimers`: Pflicht-Hinweistexte

**Wechselwirkung mit anderen Elementen:**
- Blockiert Tools → MCP-Aufrufe werden unterdrueckt
- Erzwingt Pattern → ueberschreibt Pattern-Engine-Ergebnis
- High-Risk → spekulative Vorab-Abfragen werden abgebrochen

### 9. Policy-Entscheidung

**Erzeugt von:** `policy_service.evaluate()`

**Felder:**
- `blocked_tools`: Persona/Intent-basierte Tool-Blockaden
- `disclaimers`: Pflichthinweise (z.B. Presse-Disclaimer)

**Wechselwirkung:**
- Additiv zu Safety-Blockaden
- Disclaimers werden dem Prompt als Pflichttext hinzugefuegt

### 10. Klassifikations-Ergebnis

**Erzeugt von:** `classify_input()` (LLM-Call mit tool_choice)

**Felder:**
- `persona_id`, `intent_id`, `intent_confidence`
- `signals` (Liste aktiver Signal-IDs)
- `entities` (Slot-Werte)
- `turn_type` (initial | follow_up | clarification | correction | topic_switch)
- `next_state`

**Wechselwirkung:**
- Persona → steuert Anrede, Pattern-Gate, Policy
- Intent → steuert Pattern-Gate, spekulative Abfragen, Tool-Praeferenz
- Signals → modulieren Pattern-Defaults (Ton, Laenge, skip_intro, one_option)
- Entities → werden an MCP-Tools weitergegeben und ueber Turns akkumuliert
- Confidence → unter Schwelle: PAT-02 (Nachfrage) statt direkter Antwort

### 11. Trace (Debug-Info)

**Erzeugt von:** `trace_service`

Wird als `DebugInfo`-Objekt in der Chat-Response zurueckgegeben (nur bei aktiviertem Debug-Modus). Enthaelt alle Zwischen-Ergebnisse aller 7 Phasen. Persona, Intent und State werden mit menschenlesbaren Labels ausgegeben (z.B. `P-W-LK (Lehrkraft)`, `INT-W-06 (Faktenfragen)`, `state-3 (Information)`).

`phase3_modulations` enthaelt alle 19 Modulations-Felder:
- Stil: `tone`, `formality`, `length`, `detail_level`
- Response: `response_type`, `format_primary`, `format_follow_up`, `sources`
- Steuerung: `max_items`, `card_text_mode`, `tools`, `rag_areas`, `core_rule`
- Flags: `skip_intro`, `one_option`, `add_sources`
- Degradation: `degradation`, `missing_slots`, `blocked_patterns`

### 12. Quality-Log

**Erzeugt von:** `log_quality_event()` in `database.py`

Jeder Chat-Turn wird automatisch in der `quality_logs`-Tabelle protokolliert (non-blocking, fire-and-forget). Steuerbar ueber `01-base/quality-log-config.yaml`:

```yaml
logging:
  enabled: true    # An/Aus (Standard: true)
  retention_days: 180
```

**Gespeicherte Metriken:** Pattern-ID, Score-Gap zum Zweitplatzierten, Intent-Confidence, Entities, Degradation, Tool-Outcomes, Antwortlaenge sowie das vollstaendige Debug-JSON fuer Deep-Dive-Analyse.

**Aggregierte Statistiken** ueber `GET /api/quality/stats`:
- Pattern-Verteilung, Intent-Verteilung
- Durchschnittliche Confidence und Score-Gap
- Degradation-Rate, Empty-Entity-Rate, Tight Races

---

## Wechselwirkungs-Matrix

Wie beeinflussen sich die Elemente gegenseitig?

```
Persona ──────┬── filtert ──→ Pattern-Gate
              ├── aktiviert → Policy-Regeln
              ├── bestimmt → Anrede (Sie/du)
              └── beeinflusst → Tool-Zugang

Intent ───────┬── filtert ──→ Pattern-Gate
              ├── loest aus → Spekulative MCP-Abfrage
              ├── steuert ──→ Tool-Praeferenz (Collections vs Content)
              └── bestimmt → Entity-Erwartung

Signal ───────┬── moduliert → Pattern-Defaults (Ton, Laenge)
              ├── gewichtet → Pattern-Scoring (signal_high/medium/low_fit)
              └── reduziert → max_items bei Stress-Signalen

Entity ───────┬── parametriert → MCP-Tool-Aufrufe
              ├── gespeist von → Spekulative Query-Ermittlung
              └── akkumuliert → Ueber Turns via turn_type-Regeln

State ────────┬── filtert ──→ Pattern-Gate
              └── gesetzt von → Klassifikator (next_state)

Pattern ──────┬── bestimmt → Antwortstruktur + Ton
              ├── steuert ──→ Tool-Zugang (sources, tools)
              └── moduliert → Signal-Overrides

Context ──────┬── gibt Bonus → Pattern-Scoring (page_bonus)
              └── verkuerzt → Antworten bei mobile
```

## Konkrete Beispielkette

**Nutzernachricht:** *"Mathe Klasse 7 Videos"* (von einer Lehrkraft auf der Startseite)

1. **Klassifikation:**
   - Persona: `P-W-LK` (Lehrkraft)
   - Intent: `INT-W-03` (Inhalte abrufen)
   - Entities: fach=Mathematik, stufe=Klasse 7, medientyp=Video
   - Signals: [zielgerichtet, erfahren]
   - State: state-5 (Search)

2. **Safety:** risk=low, keine Blockaden

3. **Spekulative Abfrage:**
   - INT-W-03 ist in `_spec_search_intents` → `search_wlo_content` wird parallel gestartet
   - Query: "Mathematik" (aus Entity `fach`)

4. **Pattern-Engine:**
   - Gate: PAT-01 (alle offen), PAT-05 (LK + erfahren), PAT-07 (Search-State)
   - Scoring: PAT-05 gewinnt (signal_high_fit: erfahren + zielgerichtet)
   - Modulation: tone=sachlich, length=kurz, skip_intro=true

5. **Prompt-Zusammensetzung:**
   - System: base-persona + domain-rules + LK-Persona + PAT-05-Block + Signal-Overrides + guardrails
   - Messages: Verlauf + User-Nachricht + [prefetched search_wlo_content Result]
   - Tools: MCP-Tools (aber tool_choice nicht "required", weil Prefetch vorliegt)

6. **LLM-Antwort:** Knappe, sachliche Auflistung von Mathe-Videos fuer Klasse 7, keine Einleitung, Quellenkarten.
