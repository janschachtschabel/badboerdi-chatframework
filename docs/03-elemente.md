# Elemente und ihre Wechselwirkungen

> **Stand: Welle E v4 (2026-05-25) — Hint-Primary-Architektur.**
> Die Pattern-Wahl trifft das Klassifikator-LLM; eine deterministische
> Score-Engine ist nicht mehr aktiv. Persona steuert ausschließlich Stil
> und Anrede, nicht die Pattern-Auswahl.

---

## Übersicht

Das BadBoerdi-Framework arbeitet mit **6 Konfig-Elementen** (Persona, Intent,
State, Entity, Pattern, Signal) und **3 Laufzeit-Elementen** (Safety, Policy,
Klassifikation). Zusammen formen sie den System-Prompt und steuern die
Antwort-Generierung.

| # | Element | Quelle | Anzahl | Wirkt auf |
|---|---|---|---|---|
| 1 | Persona | `04-personas/*.md` | 6 | Stil + Anrede (Phase 3 Modulate) |
| 2 | Intent | `04-intents/intents.yaml` | 8 | Klassifikator-Hint für Pattern |
| 3 | State | `04-states/states.yaml` | 3 | Gesprächs-Verlaufs-Phase |
| 4 | Entity | `04-entities/entities.yaml` | 5 | MCP-Tool-Parameter + Degradation |
| 5 | Pattern | `03-patterns/*.md` | 15 | Antwort-Struktur, Tools, Stil-Defaults |
| 6 | Signal | `04-signals/signal-modulations.yaml` | dyn. | Stil-Overrides (Tone/Länge) |

---

## 1. Persona

**Datei:** `04-personas/*.md` (6 Stück)

| ID | Label | Beschreibung | Formality (Default) | Override |
|----|-------|--------------|---------------------|----------|
| P-AND | Andere / Unbekannt | Default ohne klare Persona-Marker | neutral | nein |
| P-ELT | Eltern | Eltern eines schulpflichtigen Kindes | wie_user → Sie | nein |
| P-ENT | Entscheider | Verwaltung / Politik / Schulberatung / Schulleitung | siezen | **ja** |
| P-LEH | Lehrkraft | Lehrkraft, plant Unterricht für eine Klasse | wie_user → Sie | nein |
| P-LER | Lerner:in / Schüler:in | Schüler:in, die selbst lernt | duzen | **ja** |
| P-RED | Redaktion & Medien | WLO-Redaktion / Presse / Journalismus | wie_user → Sie | nein |

**Welle E v4: Persona ist nur noch Stil-Modifier.**

Persona wählt **kein** Pattern aus. Sie steuert ausschließlich:

- **Tone** (formell · kollegial · spielerisch · warm · …)
- **Length-Bias** (-0.3 bis +0.3 — Antwort eine Stufe kürzer/länger)
- **Formality** (siezen · duzen · wie_user · neutral)
- **Card-Text-Mode** (minimal · reference · highlight · explanation)
- **Override-Flag** — wenn true, schlägt der Persona-Modifier den Pattern-Default

**Frontmatter-Schema (Persona-MD, 5 Sektionen):**

```yaml
---
id: P-ENT
label: Entscheider
description: ...

# Stil & Anrede (Phase 3 Modulate)
tone: formell
length_bias: 0.1
formality: siezen
card_text_mode: minimal
override: true

# Klassifikations-Hilfen (nur für den Klassifikator-LLM)
positive_markers: ["Schulamt", "Ministerium", "Wahlkreis", "amtliche Daten", …]
anti_markers:
  - { phrase: "mein Kind", redirect_to: P-ELT, rationale: "Eltern-Pronomen" }
  - …
discriminators:
  - { vs: P-LEH, rule: "amtliche KPI vs Klassenraum", example_a: …, example_b: … }

# Verantwortlichkeit + Wunsch (für Response-Prompt)
goals: ["Belastbare Daten beschaffen", …]
rules: ["Quellen + Zeitstand immer angeben", …]
typical_intents: [I02, I03, I05]
---
```

**Wirkung:**
- Phase 3 Modulate liest `tone`/`length_bias`/`formality`/`card_text_mode`/`override`
- Klassifikator-Prompt erhält `positive_markers` + `anti_markers` + `discriminators`
- Response-Prompt erhält `goals` + `rules` (persona-passende Antwort-Direktive)
- `lookup_persona_self_id__*`-Rules in `routing-rules.yaml` setzen Persona auf Basis expliziter Selbst-ID-Phrasen ("ich bin Lehrkraft …") — als zusätzliches Korrektiv neben dem Klassifikator-LLM

---

## 2. Intent

**Datei:** `04-intents/intents.yaml` (8 Stück)

| ID | Label | Typisches Pattern (Klassifikator-Hint) |
|----|-------|---------------------------------------|
| I01 | Orientierung | M15 (Orientierung) |
| I02 | Wissensfrage | M04 (Wissens-Antwort) |
| I03 | Inhalte-Suchen | M05/M06/M07/M08/M12 (je nach Slots) |
| I04 | Lernpfad | M09 (Lernpfad-Erstellung) |
| I05 | Inhalt-Generieren | M10 (KI-Inhalt-Generierung) |
| I06 | Inhalt-Nachbearbeiten | M11 (Iterative Nachbearbeitung) |
| I07 | Feedback-Bot | M14 (Bot-Feedback-Echo) |
| I08 | Einreichen / Melden | M13 (Inhalt-Einreichen / Melden) |

**YAML-Schema:**

```yaml
intents:
  - id: I05
    label: Inhalt-Generieren
    description: Neues Material vom Bot generieren lassen — Arbeitsblatt, Quiz, Bericht …
    trigger_verbs: ["erstelle", "generiere", "bau mir", "schreib mir", "mach mir"]
    negative_triggers:
      - { phrase: "suche", redirect_to: I03, when: "ohne Erstell-Verb" }
    discriminators:
      - { vs: I04, rule: "Einzel-Material (I05) vs sequenzieller Lernpfad (I04)",
          example_a: "Erstelle mir ein Arbeitsblatt → I05",
          example_b: "Erstelle mir einen Lernpfad → I04" }
```

**Wirkung:**
- Klassifikator-LLM nutzt `trigger_verbs` + `discriminators` + `negative_triggers` zur Intent-Erkennung
- Intent kommt als Klassifikations-Ergebnis (`classification.intent_id`) in die Pipeline
- Rules in `06-rules/routing-rules.yaml` können bei klaren Slot-Lagen das Pattern erzwingen (z. B. I05 ohne `topic` → M03 Slot-Klärung statt M10)
- `lookup_intent_anchor__*`-Rules korrigieren Catch-All-Verwechslungen (I01/I05 → I03/I04 etc. anhand expliziter Verb-Anker)

---

## 3. State (Gesprächs-Verlaufs-Phase)

**Datei:** `04-states/states.yaml` (3 Stück — Welle E v3)

| ID | Label | Bot-Rolle |
|----|-------|-----------|
| S1 | Orientierung | Bot sondiert offen, präsentiert Möglichkeiten |
| S2 | Klärung | Bot fragt nach fehlendem Slot (max. 1 Frage pro Turn) |
| S3 | Aktion | Bot liefert Material / Inhalt / Routing |

Welle E v3 hat die früheren 11 States auf 3 reduziert — States modellieren jetzt
**Gesprächs-Verlaufs-Phasen**, nicht zweite Klassifikations-Achse zum Intent.

**YAML-Schema:**

```yaml
states:
  - id: S3
    label: Aktion
    role: Liefere konkrete Antwort (Material, Inhalt, Routing).
    bot_directive: |
      Gib konkrete Treffer / Inhalte / Links. Frag nur dann zurück,
      wenn dir ein harter Pflicht-Slot fehlt.
    next_likely: [S1, S2, S3]   # plausible Folge-Zustände
```

**Wirkung:**
- `bot_directive` wird in den Response-Prompt eingebaut (Verhaltens-Hinweis pro Phase)
- `next_likely` validiert State-Übergänge im Trace (Plausibilitäts-Telemetrie)
- States werden vom Klassifikator gesetzt (`classification.state_id`)

---

## 4. Entity (Slot)

**Datei:** `04-entities/entities.yaml` (5 Slots)

| ID | Label | Beispiel |
|----|-------|----------|
| `fach` | Fach / Fachgebiet | Mathematik, Biologie, Geschichte |
| `stufe` | Bildungsstufe | Grundschule, Sek I, Klasse 7 |
| `thema` | Thema | Bruchrechnung, Photosynthese, Klimawandel |
| `medientyp` | Medientyp | Video, Arbeitsblatt, Simulation |
| `lizenz` | Lizenz | CC BY, CC BY-SA, CC0 |

**Wirkung:**
- Werden als **Such-Parameter** an MCP-Tools weitergegeben
- Werden **über Turns akkumuliert** (Entity-Memory, je nach `turn_type`)
- `precondition_slots` im Pattern: fehlt ein Pflicht-Slot, setzt `phase3_modulate`
  das Flag `degradation=true` + `missing_slots`-Liste — der Antwort-Builder kann
  darauf eine Klärungs-Rückfrage anschließen
- Slot-fehlt-Rules in `routing-rules.yaml` (`rule_create_needs_topic`,
  `rule_plan_needs_topic`, `rule_vague_search`) erzwingen M03 (Slot-Klärung)
  wenn ein Pflicht-Slot leer ist

---

## 5. Pattern (Antwort-Muster)

**Datei:** `03-patterns/*.md` (16 Patterns, M01–M16)

**Pattern-Selektion (Welle E v4):** kein 3-Phasen-Engine mehr.

1. **Safety-Override** — `enforced_pattern_id` vom Safety-Layer (M01/M02) gewinnt immer
2. **Pre-Route-Rules** — können `enforced_pattern_id` aus `routing-rules.yaml` setzen
3. **LLM-Hint** — `pattern_id_hint` vom Klassifikator (primärer Pfad in ≈ 100 % der Turns)
4. **Fallback** — defensives M15 (Orientierung) bzw. M03 (Klärung), wenn weder Safety
   noch Rules noch Hint ein gültiges Pattern liefern
5. **`phase3_modulate`** — Stil/Tonalitäts-Anpassung via Persona-Modifier + Pattern-Defaults

| ID | Label | Priorität | Typischer Einsatz |
|----|-------|-----------|-------------------|
| M01 | Krisen-Empathie | 999 | Akute Notlage (Safety-enforced) |
| M02 | Bedrohungs-Refusal | 998 | Drohung/Verbalattacke (Safety-enforced) |
| M03 | Slot-Klärung | 450 | Pflicht-Slot fehlt → 1 Frage + 3 Quick-Replies |
| M04 | Wissens-Antwort | 520 | Definitions-/Konzept-/Faktenfrage aus RAG |
| M05 | Material-Suche gefiltert | 510 | Thema + Filter → direkte MCP-Suche |
| M06 | Material-Suche Cascade | 500 | Thema, Filter unklar → Themenseite→Sammlung→Content |
| M07 | Fachportale-Übersicht | 490 | Plural-Frage „welche Fächer?" → `get_subject_portals` |
| M08 | Sammlung-Drilldown | 490 | Singular-Fach mit Drilldown-Verb → eine Ebene tiefer |
| M09 | Lernpfad-Erstellung | 480 | Sequenzieller Plan aus existierenden Materialien (precond: `topic`) |
| M10 | KI-Inhalt-Generierung | 470 | Arbeitsblatt/Quiz/Bericht/Remix (precond: `material_type` + `topic`) |
| M11 | Iterative Nachbearbeitung | 600 | Voriger Bot-Inhalt anpassen |
| M12 | Null-Treffer-Eskalation | 590 | 0 Treffer → Synonym-Lookup, breitere Suche, Alternativ-Pfad |
| M13 | Inhalt-Einreichen / Melden | 540 | User reicht Material ein / meldet Fehler → Submit-Link |
| M14 | Bot-Feedback-Echo | 530 | Rückmeldung zum Bot → Echo + Folge-Angebot |
| M15 | Orientierung | 460 | Erstkontakt / „Was kann ich hier?" → Begrüßung + 3 Angebote |

**Frontmatter-Schema (Welle E v4, reduziert):**

```yaml
---
id: M03
label: Slot-Klärung
priority: 450
short_purpose: Pflicht-Slot fehlt → 1 Frage + 3 konkrete Persona-/Kontext-spezifische QRs.

# precondition_slots wirken in phase3_modulate als Degradation-Flag,
# NICHT mehr als Selektor-Gate
precondition_slots: []

# Antwort-Form (Phase 3 Defaults — werden von Persona-Modifier überschrieben falls override=true)
default_tone: kollegial
default_length: kurz
default_detail: standard
response_type: question
format_primary: text
format_follow_up: quick_replies
card_text_mode: minimal

# Tools & Wissen
sources: [mcp]
tools: []
rag_areas: []
force_tool_use: false
requires_all_tools: false

# Inhalt-Regeln (für Response-Prompt)
core_rule: |
  GENAU EINE Frage zum wichtigsten fehlenden Slot. 3 Quick-Replies
  mit konkreten Optionen — niemals generische Platzhalter.
forbidden_phrases:
  - "Zu welchem Thema?" — zu offen, keine Optionen
  - Such-Tool-Calls solange Slot fehlt
anti_patterns:
  - Zwei oder mehr Fragen in einem Turn
---
```

**Entfernt seit Welle E v4** (waren tot oder durch Hint-Primary überflüssig):
`gate_personas`, `gate_states`, `gate_intents`, `signal_high_fit`,
`signal_medium_fit`, `signal_low_fit`, `page_bonus`, `priority`-Specificity-Bonus.

---

## 6. Signal

**Datei:** `04-signals/signal-modulations.yaml`

Signale sind emotionale/situative Hinweise aus der Nutzer-Nachricht (vom
Klassifikator-LLM extrahiert). Sie wirken als **Tone-/Length-Overrides**
in `phase3_modulate`.

**Beispiel-Modulationen:**

| Signal | Ton | Länge | skip_intro | Sonstiges |
|--------|-----|-------|------------|-----------|
| zeitdruck | sachlich | kurz | ja | |
| ungeduldig | sachlich | kurz | ja | reduziert max_items |
| gestresst | beruhigend | kurz | ja | reduziert max_items |
| unsicher | empathisch | mittel | | one_option |
| neugierig | spielerisch | mittel | | show_more |
| skeptisch | transparent | mittel | | add_sources |

**Wirkung:**
- Aktive Signale modulieren Pattern-Defaults deterministisch (IF-THEN)
- `reduce_items_signals` (ungeduldig, gestresst) halbieren die Kartenanzahl
- Bei Konflikten: kürzere Länge gewinnt, restriktiveres Verhalten gewinnt
- Signale sind keine Pattern-Selektoren mehr (Signal-Fit-Scoring entfernt)

---

## Die 3 Laufzeit-Elemente

### 7. Safety-Entscheidung

**Erzeugt von:** `safety_service.assess_safety()` (Regex + OpenAI-Moderation + LLM-Legal)

**Felder:**
- `risk_level`: low | medium | high
- `blocked_tools`: gesperrte Tools (bei Krisen-Erkennung)
- `enforced_pattern`: erzwungenes Pattern (`M01` bei Selbstgefährdung, `M02` bei Drohungen)
- `disclaimers`: Pflicht-Hinweistexte

**Wechselwirkung:**
- Blockiert Tools → MCP-Aufrufe unterdrückt
- Erzwingt Pattern → überschreibt Hint und Rules

### 8. Policy-Entscheidung

**Erzeugt von:** `policy_service.assess_policy()` mit `01-base/policy.yaml`

**Felder:**
- `blocked_tools`: Persona/Intent-basierte Tool-Blockaden
- `disclaimers`: Pflichthinweise

**Wechselwirkung:**
- Additiv zu Safety-Blockaden
- Disclaimers werden dem Prompt als Pflichttext hinzugefügt

### 9. Klassifikations-Ergebnis

**Erzeugt von:** `classify_input()` (LLM-Call mit tool_choice)

**Felder:**
- `persona_id`, `intent_id`, `state_id`
- `intent_confidence`, `persona_confidence`
- `signals` (Liste aktiver Signal-IDs)
- `entities` (Slot-Werte)
- `turn_type` (initial | follow_up | clarification | correction | topic_switch)
- **`pattern_id_hint`** — der vorgeschlagene Pattern-Selektor (primär)
- `pattern_reasoning` — Begründung des Hints (Eval-Telemetrie)
- `tool_hint` — vorgeschlagene MCP-Tools (für spekulative Vorab-Abfrage)

**Wechselwirkung:**
- `pattern_id_hint` ist der primäre Pattern-Selektor (siehe oben)
- Persona → Phase 3 Modulate (Stil)
- Intent → Klassifikator-Signal + Rules-Kondition
- Signals → Phase 3 Modulate (Tone/Länge-Override)
- Entities → MCP-Tool-Parameter + Degradation-Detection

---

## Wechselwirkungs-Matrix (Welle E v4)

```
Persona ──── Phase 3 Modulate (Stil + Anrede)
             └─ KEIN Pattern-Gate mehr

Intent  ──── Klassifikator → pattern_id_hint
             └─ Rules-Kondition (z. B. I05+empty topic → M03)

Signal  ──── Phase 3 Modulate (Tone/Length-Override)
             └─ KEIN Pattern-Scoring mehr

Entity  ──── MCP-Tool-Parameter
             └─ Degradation-Flag wenn Pflicht-Slot fehlt

State   ──── Gesprächs-Phase → bot_directive im Response-Prompt
             └─ next_likely → Plausibilitäts-Validator

Pattern ──── Antwort-Struktur (tone, length, format, tools)
             └─ core_rule + forbidden_phrases im Response-Prompt
             └─ wird vom LLM-Hint gewählt, nicht von Scoring
```

---

## Konkrete Beispielkette

**Nutzernachricht:** *„Mach mir bitte ein Quiz zur Photosynthese für Klasse 7"* (Lehrkraft)

1. **Safety:** risk=low, keine Blockaden, kein enforced_pattern

2. **Klassifikator:**
   - `persona_id = P-LEH` (Lehrkraft — kein expliziter Marker, aber implizit
     durch typische Frageformulierung)
   - `intent_id = I05` (Inhalt-Generieren — „Mach mir … Quiz")
   - `state_id = S3` (Aktion)
   - `entities = { material_typ: "Quiz", thema: "Photosynthese", stufe: "Klasse 7" }`
   - `signals = [zielgerichtet]`
   - `pattern_id_hint = M10` (KI-Inhalt-Generierung)

3. **Pre-Route-Rules:** keine Rule trifft zu (`thema` ist gefüllt, kein Edit-Verb)

4. **`select_pattern`:** Hint M10 wird direkt gewählt — Engine-Phase 1/2 laufen nicht.

5. **`phase3_modulate`:**
   - Persona-Tone-Modifier P-LEH: `tone=kollegial`, `formality=wie_user → Sie`,
     `card_text_mode=minimal`, `override=false`
   - Pattern-Default M10: `default_tone=kollegial` (gleich), `default_length=lang`
   - Length-Bias P-LEH = 0.0 → bleibt `lang`
   - `precondition_slots` von M10 = `[material_type, topic]` → beide gefüllt → kein Degradation-Flag

6. **Response-Prompt:**
   - Schicht 1: base-persona + guardrails
   - Schicht 2: domain-rules + wlo-plattform-wissen
   - Schicht 3: M10-Block mit `core_rule` + `forbidden_phrases`
   - Schicht 4: P-LEH-Block mit `goals` + `rules`
   - Schicht 6: Page-Context wenn vorhanden, RAG-Snippets bei Always-On-Areas

7. **Antwort:** Quiz zur Photosynthese (Klasse 7), 8–12 Fragen mit Lösungen,
   Sie-Form, mittellange Erklärungen.

---

## Pflege im Studio

| Element | Studio-Tab | Endpoint |
|---------|------------|----------|
| Persona | Dimensionen → Personas | `PUT /api/config/personas` |
| Intent | Dimensionen → Intents | `PUT /api/config/intents` |
| State | Dimensionen → States | `PUT /api/config/states` |
| Entity | Dimensionen → Entities | `PUT /api/config/entities` |
| Pattern | Patterns | `PUT /api/config/patterns` |
| Routing-Rules | Routing | `06-rules/routing-rules.yaml` via Datei-Endpoint |
| Signal-Modulationen | Datei-Browser | `04-signals/signal-modulations.yaml` |
| Tone-Modifier-Default | Datei-Browser | `01-base/tone-modifiers.yaml` |
| Device-Config (Formality-Fallback) | Datei-Browser | `01-base/device-config.yaml` |
