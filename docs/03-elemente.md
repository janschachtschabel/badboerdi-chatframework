# Elemente und ihre Wechselwirkungen

## Uebersicht

Das BadBoerdi-Framework arbeitet mit **7 Kernelementen** (aktiv bei jeder Nachricht) und **4 Laufzeit-Elementen** (dynamisch erzeugt). Zusammen bilden sie das **Triple-Schema v2** — ein deterministisches Steuerungssystem, das den LLM-Prompt nicht nur inhaltlich, sondern auch stilistisch und strukturell formt.

---

## Die 7 Kernelemente

### 1. Persona

**Datei:** `04-personas/*.md` (9 Stueck)

| ID | Label | Anrede |
|----|-------|--------|
| P-W-LK | Lehrkraft | Sie |
| P-W-SL | Schueler:in | du |
| P-W-ELT | Eltern | Sie |
| P-W-POL | Politikvertreter | Sie |
| P-W-PRESSE | Pressekontakt | Sie |
| P-W-RED | Redaktion | du |
| P-W-BER | Berater:in | Sie |
| P-W-VER | Verwaltung | Sie |
| P-AND | Sonstige/Unbekannt | neutral |

**Wirkung:**
- Bestimmt Anrede (Sie/du/neutral) aus `device-config.yaml`
- Filtert Pattern-Gates (`gate_personas`)
- Aktiviert Policy-Regeln (z.B. Presse-Disclaimer, Tool-Blockaden)
- Steuert persona-spezifischen Prompt-Abschnitt (z.B. Lehrkraft bekommt didaktische Tipps)

---

### 2. Intent

**Datei:** `04-intents/intents.yaml` (10 Stueck)

| ID | Label | Typische Aktion |
|----|-------|-----------------|
| INT-W-01 | WLO kennenlernen | Plattform-Info aus RAG |
| INT-W-02 | Soft Probing | Bot fragt nach Bedarf |
| INT-W-03a | Themenseite entdecken | `search_wlo_collections` + `search_wlo_topic_pages` |
| INT-W-03b | Unterrichtsmaterial suchen | `search_wlo_content` |
| INT-W-03c | Lerninhalt suchen | `search_wlo_content` |
| INT-W-04 | Feedback | Kein Tool, Dank/Weiterleitung |
| INT-W-05 | Routing Redaktion | Weiterleitung an Redaktion |
| INT-W-06 | Faktenfragen | MCP-Info-Tools (WLO, edu-sharing) |
| INT-W-07 | Material herunterladen | `get_node_details` |
| INT-W-08 | Inhalte evaluieren | `get_node_details` + RAG |
| INT-W-09 | Analyse & Reporting | `search_wlo_collections` + Statistik |
| INT-W-10 | Unterrichtsplanung | `search_wlo_collections` + `search_wlo_content` |

**Wirkung:**
- Bestimmt, welche MCP-Tools der LLM bevorzugt aufruft
- Filtert Pattern-Gates (`gate_intents`)
- Loest spekulative Vorab-Abfragen aus (INT-W-03a/b/c und INT-W-10)
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

**Datei:** `04-states/states.yaml` (11 Zustaende)

```
state-1  Orientation          → Erster Kontakt
state-2  Context Building     → Bot sammelt Kontext
state-3  Information          → Informationslieferung
state-4  Navigation/Discovery → Themenseiten erkunden
state-5  Search               → Aktive Materialsuche
state-6  Result Curation      → Ergebnis-Praesentation
state-7  Refinement           → Verfeinerung
state-8  Learning             → Arbeit mit Materialien
state-9  Evaluation/Feedback  → Feedback-Phase
state-10 Redaktions-Recherche → Systematische Recherche
state-11 System/Meta          → Meta-Fragen zum Bot
```

**Wirkung:**
- Filtert Pattern-Gates (`gate_states`)
- Wird pro Turn vom LLM-Klassifikator gesetzt (`next_state`)
- Ermoeglicht zustandsabhaengiges Verhalten (z.B. in state-6 werden Ergebniskarten gezeigt)

---

### 6. Pattern (Gespraechsmuster)

**Datei:** `03-patterns/*.md` (26 Patterns)

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
| PAT-11 | Nachfrage-Schleife | Iteratives Verfeinern |
| PAT-12 | Ueberbrueckungs-Hinweis | Uebergang zwischen Themen |
| PAT-13 | Schritt-fuer-Schritt | Angefuehrte Anleitung |
| PAT-14 | Eltern-Empfehlung | Speziell fuer Eltern |
| PAT-15 | Analyse-Ueberblick | Statistiken und Uebersichten |
| PAT-16 | Themen-Exploration | Breite Themen-Erkundung |
| PAT-17 | Sanfter Einstieg | Behutsamer Erstkontakt |
| PAT-18 | Unterrichts-Paket | Materialzusammenstellung (precondition: fach+stufe+thema) |
| PAT-19 | Unterrichts-Lernpfad | Strukturierter Lernpfad (precondition: fach+stufe+thema) |
| PAT-20 | Orientierungs-Guide | Reine Text-Orientierung (kein MCP!) |
| PAT-21 | Canvas-Create | Neues Material KI-generiert im Canvas (precondition: thema+material_typ, INT-W-11) |
| PAT-22 | Feedback-Echo | Nutzer-Feedback bestaetigen + Folge-Angebot (INT-W-04) |
| PAT-23 | Redaktions-Routing | Luecken/Fehler an Redaktion weiterleiten (INT-W-05) |
| PAT-24 | Download-Hinweis | Download-Weg ueber Kachel erklaeren + Lizenz-Hinweis (INT-W-07) |
| PAT-CRISIS | Crisis-Empathie | Notfall-Pattern: Bei Krisen-Signalen sofort deeskalieren |
| PAT-REFUSE-THREAT | Refuse-Threat | Abweisung von Bedrohungs-/Policy-Verletzungen |

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
   - Intent: `INT-W-03b` (Unterrichtsmaterial suchen)
   - Entities: fach=Mathematik, stufe=Klasse 7, medientyp=Video
   - Signals: [zielgerichtet, erfahren]
   - State: state-5 (Search)

2. **Safety:** risk=low, keine Blockaden

3. **Spekulative Abfrage:**
   - INT-W-03b ist in `_spec_search_intents` → `search_wlo_content` wird parallel gestartet
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
