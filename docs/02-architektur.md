# Architektur — Schichten und Pipeline

> **Stand: Welle E v4 (2026-05-25) — Hint-Primary-Architektur.**

## Architektur-Überblick

BadBoerdi besteht aus **5 Konfig-Schichten** + einer schlanken
**Pattern-Pipeline**, die zur Laufzeit den finalen System-Prompt
zusammensetzt. Jede Schicht ist eine separate Datei-Hierarchie unter
`backend/chatbots/<bot>/<version>/` und wird vom Studio einzeln gepflegt.

```
01-base/              Identität & Schutz       (immer aktiv)
02-domain/            Domain-Wissen & Regeln   (immer aktiv)
03-patterns/          15 Antwort-Muster        (nur das gewählte Pattern)
04-personas/          6 Personas               (nur die erkannte)
04-intents/           8 Intents                (Klassifikator-Hilfen)
04-entities/          5 Slots                  (Klassifikator-Hilfen)
04-states/            3 Gesprächs-Phasen       (aktive Phase)
04-signals/           Tone-Modulationen        (aktive Signale)
05-knowledge/         RAG & MCP-Server         (kontextabhängig)
06-rules/             Routing-Rules            (Korrektur-Schicht)
```

**Warum Schichten?**
- **Kein Prompt-Overload** — nur aktive Elemente werden in den finalen Prompt eingefügt.
- **Token-Management** — bei Überschreitung des Token-Limits werden niedrigprioritäre Schichten entladen.
- **Separation of Concerns** — Identität, Sicherheit, Fachregeln, Gesprächsmuster, Wissen sind unabhängig editierbar.
- **Studio-Kompatibilität** — jede Schicht hat eine eigene Datei; Studio kann gezielt einzelne Elemente laden und speichern.

---

## Schicht 1: Identität & Schutz

**Pfad:** `01-base/`

| Datei | Zweck |
|-------|-------|
| `base-persona.md` | BOERDi-Identität: Name, Rolle (blaue Eule), Tonalitäts-Basis |
| `guardrails.md` | Harte Regeln, die nie überschrieben werden (max. 1 Frage pro Turn, kein Blockieren ohne Grund) |
| `safety-config.yaml` | Safety-Stufenkonfiguration (off/regex/standard/strict/paranoid) |
| `quality-log-config.yaml` | Quality-Logging-Toggle + Retention + Schwellenwerte |
| `device-config.yaml` | Geräte-Limits (max_items pro Desktop/Tablet/Mobile) + Persona-Anrede-Fallback |
| `tone-modifiers.yaml` | Default-Modifier wenn Persona-MD `formality: wie_user` setzt |
| `display-rules.yaml` | Frontend-Display-Limits (Cards-pro-Box, Inline-Doc-Anzeige, …) |
| `widget-modes.yaml` | Widget-Embed-Modi (cards-enabled, canvas-enabled, …) |
| `placeholder-topics.yaml` | Beispielthemen für leere QR-Slots |
| `privacy-config.yaml` | Privacy-Toggles (Logging an/aus pro Datenklasse) |
| `card-pipeline.yaml` | MCP-Card-Rendering-Konfiguration |
| `website-tour.yaml` | Geführte Besucher-Tour: Begrüßung, Schritt-Texte, Ziel-URLs, 7 Besucher-Gruppen + Gruppe→Angebot-Mapping (Verhalten/State-Machine in `app/services/tour_service.py`, **kein** Pattern) |

**Priorität:** 1000 — `base-persona.md` steht am Anfang, `guardrails.md` immer am Ende. Wird **nie** entladen.

---

## Schicht 2: Domain & Regeln

**Pfad:** `02-domain/`

| Datei | Zweck |
|-------|-------|
| `domain-rules.md` | Plattform-Regeln (Such-Strategie, Themenseiten-Integration, Disambiguierung, Vollständigkeitsprüfung) |
| `policy.yaml` | Strukturelle Berechtigungen (Tool-Blockaden pro Persona/Intent, Disclaimer-Texte) |
| `wlo-plattform-wissen.md` | Faktenwissen über WLO (Struktur, Angebote, Zielgruppen) |
| `guide-rules.yaml` | Lotsen-Regeln für die Material-Vorschläge |

**Priorität:** 900 — wird nie entladen.

---

## Schicht 3: Patterns (Antwort-Muster)

**Pfad:** `03-patterns/` (15 Pattern-MDs)

Jedes Pattern definiert *wie* der Bot auf eine erkannte Situation reagiert:
Antwort-Struktur, Tool-Set, Tone-Default, Pflicht-Regeln, verbotene
Formulierungen. Die volle Pattern-Liste mit Verwendungen siehe
[`03-elemente.md`](./03-elemente.md#5-pattern-antwort-muster).

### Pattern-Selektion (Hint-Primary)

Seit Welle E v4 entscheidet **der Klassifikator-LLM** das Pattern via
`pattern_id_hint`. Die frühere 3-Phasen-Engine (Gate → Score → Modulate)
wurde reduziert auf:

```python
# backend/app/services/pattern_engine.py:select_pattern
def select_pattern(...):
    # 1. Safety-Override (Krisen-Patterns M01/M02)
    if enforced_pattern_id:
        return enforced, phase3_modulate(...), {enforced.id: 1.0}, []

    # 2. LLM-Hint
    if pattern_id_hint:
        return hinted, phase3_modulate(...), {hinted.id: 1.0}, []

    # 3. Fallback (M15 Orientierung)
    return fallback, phase3_modulate(...), {fallback.id: 1.0}, []
```

**Reihenfolge der Selektoren** in `routers/chat.py:_pattern_for_request`:

1. **Safety-Layer** — kann via `enforced_pattern_id` ein Pattern erzwingen (M01 bei Selbstgefährdung, M02 bei Drohungen)
2. **Pre-Route-Rules** — `06-rules/routing-rules.yaml` kann via `enforced_pattern_id` korrigieren
   - z. B. `rule_create_needs_topic`: I05 ohne `topic` → M03 (Slot-Klärung)
   - z. B. `rule_iterative_edit`: Edit-Verb + voriger M09/M10-Turn → M11
3. **LLM-Hint** (`pattern_id_hint`) — primärer Pfad in praktisch 100 % der Turns
4. **Fallback** — M15 (Orientierung), wenn weder Safety noch Rules noch Hint ein gültiges Pattern liefern
5. **`phase3_modulate`** — Stil/Tonalitäts-Anpassung über Persona-Modifier + Pattern-Defaults + aktive Signale
6. **Post-Route-Rules** — letzte Chance für `enforced_pattern_id`-Korrektur

### `phase3_modulate` — die einzige verbliebene deterministische Schicht

```python
def phase3_modulate(pattern, signals, device, entities, persona_id):
    # 1. Persona-Tone-Modifier (tone-modifiers.yaml + Persona-MD)
    tone_mod = get_tone_modifier_for_persona(persona_id)
    effective_tone = tone_mod['tone'] if (tone_mod.override or pattern.default_tone == 'sachlich') else pattern.default_tone
    effective_length = apply_length_bias(pattern.default_length, tone_mod.length_bias)
    effective_formality = tone_mod.formality if tone_mod.formality != 'wie_user' else device_config[persona_id]

    # 2. Tool-Liste + RAG-Areas aus Pattern-Frontmatter
    # 3. Signal-Modulationen (deterministische IF-THEN auf Tone/Länge)
    # 4. Slot-Degradation: fehlen Pflicht-Slots → degradation=true, missing_slots=[...]

    return output
```

### Was kommt **nicht** mehr vor (Welle E v4 Cleanup)

- ❌ `phase1_gate` — Persona-/State-/Intent-Gates filterten Patterns vor dem Score
- ❌ `phase2_score` — gewichtetes Ranking mit signal_high_fit/page_bonus/precondition-Vollständigkeit
- ❌ Tie-Breaker — Hint-Override bei knappen Score-Races
- ❌ `gate_personas`/`gate_states`/`gate_intents` im Pattern-Frontmatter
- ❌ `signal_*_fit`, `page_bonus` im Pattern-Frontmatter
- ❌ `tie-breaker.yaml`

**Priorität:** 500–800 — kann bei Token-Knappheit entladen werden (Fallback: M15 Orientierung).

---

## Schicht 4: Dimensionen

**Pfad:** `04-*/`

Schicht 4 besteht aus **5 Element-Typen**:

| Verzeichnis | Element-Typ | Anzahl | Beschreibung |
|-------------|-------------|--------|--------------|
| `04-personas/` | Personas | 6 | Nutzergruppen (Lehrkraft, Lerner, Eltern, Entscheider, Redaktion, Andere) |
| `04-intents/` | Intents | 8 | Erkannte Absichten (Orientierung, Wissensfrage, Inhalte-Suchen, Lernpfad, …) |
| `04-entities/` | Entities | 5 | Slots (Fach, Stufe, Thema, Medientyp, Lizenz) |
| `04-states/` | States | 3 | Gesprächs-Verlaufs-Phasen (Orientierung, Klärung, Aktion) |
| `04-signals/` | Signale | dyn. | Tone-/Länge-Modifikatoren (zeitdruck, ungeduldig, neugierig, …) |

**Im Prompt:** Nur die erkannte Persona, der aktive Intent, die aktive State-`bot_directive` und die detektierten Signale werden eingebaut — nicht alle 6 Personas oder 8 Intents.

**Priorität:** 300–600.

Detail-Schema und Wirkungs-Matrix: siehe [`03-elemente.md`](./03-elemente.md).

---

## Schicht 5: Wissen (RAG + MCP)

**Pfad:** `05-knowledge/` (+ Laufzeit-Service `page_context_service.py`)

| Datei | Zweck |
|-------|-------|
| `rag-config.yaml` | RAG-Bereichskonfiguration (always-on vs on-demand) |
| `mcp-servers.yaml` | MCP-Server-Registry mit Tool-Definitionen |

### RAG-Wissensbereiche

- **Always-On** (z. B. `wlo-plattform-wissen`): bei jeder Nachricht als Kontext eingebunden
- **On-Demand**: nur geladen, wenn das aktive Pattern `sources: ["rag"]` hat
- Dokumente werden per Studio hochgeladen (Datei/URL/Freitext), in Chunks zerlegt, in SQLite-Vec gespeichert
- **Seed-System**: Backend liefert initiale Wissensbasis als `knowledge/rag-seed.json` (~348 Chunks in 4 Bereichen). Bei leerer DB wird automatisch importiert; Embedding-Generation läuft im Hintergrund.

### MCP-Server (externe Tools)

Aktuell **1 Server**: WLO edu-sharing (~11 Tools)

- `search_wlo_collections` / `search_wlo_content` / `search_wlo_topic_pages`
- `get_collection_contents` / `get_subject_portals` / `browse_collection_tree`
- `get_node_details` / `lookup_wlo_vocabulary`
- `get_wirlernenonline_info` / `get_edu_sharing_*` / `get_metaventis_info`

`search_wlo_topic_pages` unterstützt zielgruppenspezifische Varianten (teacher/learner/general).

### Themenseiten-Resolver (`page_context_service.py`)

Wenn das Widget eine `node_id` oder `topic_page_slug` über `page_context` mitliefert, löst das Backend die URL vor dem ersten Turn auf:

| Status | TTL | Verhalten |
|--------|-----|-----------|
| resolved | 30 Min | Themenseiten ändern sich selten |
| unresolved (MCP-Fehler / Titel-Fallback) | 2 Min | Transiente Ausfälle erholen sich schnell |

Die Metadaten landen als semantischer Block im System-Prompt — der Bot kann „Worum geht es hier?" oder „Erstelle mir ein Quiz dazu" ohne Rückfragen beantworten.

**Priorität:** 100–200 — wird als erstes entladen bei Token-Knappheit.

---

## Schicht 6: Routing-Rules

**Pfad:** `06-rules/routing-rules.yaml`

Korrektur-Schicht für klare Edge-Cases, die der Klassifikator-LLM nicht
zuverlässig erfasst. **Rules sind Sanity-Net, nicht Hauptselektor.**

| Rule-Klasse | Beispiele |
|-------------|-----------|
| Safety-Override | `rule_safety_override` |
| Slot-Klärung (Pattern-Force) | `rule_create_needs_topic`, `rule_plan_needs_topic`, `rule_vague_search` |
| Edit-Detection | `rule_iterative_edit`, `rule_edit_without_prior_content`, `rule_create_followup_after_slot_clarification` |
| Such-Cascade | `rule_search_with_filter`, `rule_search_cascade` |
| Spezial-Routing | `rule_subject_portals`, `rule_subject_drilldown`, `rule_learning_deficit`, `rule_personal_data_request` |
| Persona-Self-ID (Lookup) | `lookup_persona_self_id__{leh,ler,elt,red,ent}` — setzt `persona_override`, nicht Pattern |
| Intent-Anchor (Lookup) | `lookup_intent_anchor__{i04_plan,i05_create,i08_submit,…}` — korrigiert Catch-All-Intents |

**Confidence-Fallbacks:**
- `rule_low_persona_confidence` (< 0.40) → `persona_override: P-AND`
- `rule_low_intent_confidence` (< 0.55) → `enforced_pattern_id: M03` (Slot-Klärung)

**Telemetrie:** Jede Rule wird in `logs/shadow_router_*.jsonl` protokolliert
mit `fired`/`effective`/`redundant`-Counters — Studio zeigt das im
Routing-Rules-Editor an, inkl. Lösch-Vorschlägen bei dauerhaft 100 %
redundanten Rules.

---

## Pattern-Pipeline zur Laufzeit

```
User-Nachricht
   ↓
parallel: [Safety-Layer]   [Klassifikator-LLM]   [Memory-Fetch]
              │                    │
              ▼                    ▼
          enforced_pattern    pattern_id_hint
          (M01/M02)           persona_id, intent_id, state_id,
                              entities, signals, tool_hint
   ↓
Pre-Route-Rules (routing-rules.yaml, live: true)
   → kann enforced_pattern_id / intent_override / persona_override setzen
   ↓
select_pattern():
   1. enforced_pattern_id (Safety + Rules)
   2. pattern_id_hint (LLM)
   3. Fallback M15
   ↓
phase3_modulate():
   - Persona-Tone-Modifier anwenden
   - Pattern-Defaults setzen
   - Signal-Modulationen
   - Slot-Degradation prüfen
   ↓
Post-Route-Rules (peek + apply)
   ↓
generate_response():
   - System-Prompt aus Schichten zusammenbauen
   - MCP-Tools als Function-Definitions
   - RAG-Prefetch als synthetisches Tool-Result
   - LLM-Call mit Tools
   - Reflection-Loop (Tool → Response → ggf. weiteres Tool)
   ↓
Response + Debug-Trace
```

---

## Prompt-Zusammensetzung

```
System-Prompt:
+----------------------------------+
| Schicht 1: base-persona.md       |  <-- immer, Priorität 1000
+----------------------------------+
| Schicht 2: domain-rules.md       |  <-- immer, Priorität 900
|            wlo-plattform-wissen  |
+----------------------------------+
| Schicht 4: Persona-Prompt        |  <-- nur erkannte Persona
|            (goals, rules)        |
|            Intent-Kontext        |
|            State-Direktive       |
|            Signal-Overrides      |
+----------------------------------+
| Schicht 3: Pattern-Block         |  <-- nur das gewählte Pattern
|            core_rule             |
|            forbidden_phrases     |
|            anti_patterns         |
|            body_md               |
+----------------------------------+
| Schicht 5: Page-Context          |  <-- wenn node_id/slug auflösbar
|            RAG-Kontext           |  <-- bei always-on Areas / on-demand
+----------------------------------+
| Schicht 1: guardrails.md         |  <-- IMMER am Ende
+----------------------------------+

Nachrichten:
+----------------------------------+
| Gesprächsverlauf (max. 20 Turns) |
| Aktuelle Nutzernachricht         |
| [MCP-Prefetch Tool-Call/Result]  |  <-- optional bei tool_hint
+----------------------------------+

Tools (Function-Definitions):
+----------------------------------+
| MCP-Tools (wenn sources=["mcp"]) |
| query_knowledge (on-demand RAG)  |
+----------------------------------+
```

**Token-Budget-Management:** Bei Token-Limit-Überschreitung werden Schichten nach Priorität entladen:

1. Schicht 5 (Wissen + Themenseite) → entfernt
2. Schicht 4 (Dimensionen) → reduziert (nur Tonalität, keine Goals/Rules)
3. Schicht 3 (Pattern) → Fallback auf M15 (Orientierung) mit minimaler core_rule
4. Schichten 1–2 → werden **nie** entfernt

---

## Telemetrie & Diagnostik

### Quality-Log (`badboerdi.db:quality_logs`)

Jeder Turn wird mit Pattern-ID, Intent, Persona, State, Entities, Tools-Called,
Antwortlänge, Debug-JSON protokolliert. Studio-Reports: **Pattern-Verteilung**,
**Intent-Verteilung**, **Degradation-Rate**, **Pattern-Disagreement** (Hint vs
Final).

Welle E v4 (2026-05-25): `phase2_score_gap` / `phase2_runner_up` /
`eliminated_count` werden weiterhin in der Tabelle vorgehalten (Backward-Compat),
sind aber durchgängig 0/leer — die Score-Phase läuft nicht mehr.
Pattern-Ambiguität ist jetzt nur noch über die **EvaluationView** (LLM-Hint vs
Engine-Disagreement) sichtbar.

### Shadow-Router-Log (`logs/shadow_router_*.jsonl`)

Jede Routing-Rule schreibt ein Pre-/Post-Phase-Record. Aggregat-Metriken pro Rule:

- `fired` — wie oft die Rule gematcht hat
- `effective_pct` — Anteil mit Agreement zur finalen Decision
- `redundant_pct` — Anteil, in dem der LLM-Hint dasselbe Pattern ohne Rule gewählt hätte
- `conflict_pct` — Anteil, in dem die Rule überschrieben wurde
- `recommendation` — keep | review | redundant | delete | insufficient_data

Studio: Routing-Rules-Editor zeigt diese Stats inline, mit Lösch-Vorschlag bei
dauerhaft 100 % redundanten Rules.

### Eval-Service (`eval_service.py`)

Persona-/Intent-Eval-Runs über die Studio-Eval-View. Aggregat-Metriken:

- `persona_correct_rate_fair` — Klassifikator-Trefferquote
- `intent_correct_rate`
- `pattern_match_score_distribution` — wie oft Judge das Pattern als „passend" einstuft
- `llm_engine_match_rate` / **`llm_hint_final_match_rate`** (Alias) — wie oft Hint == Final-Pattern
- `pattern_hint_verdict_counts` — bei Disagreement: war Rule-Override oder Hint allein besser?
- `pattern_engine_better_rate` / **`pattern_override_better_rate`** (Alias) — Quote, in der das
  Final-Pattern (Rule-Override) besser war als der LLM-Hint allein
- `pattern_disagreement_pairs` — Top-N Konflikt-Paare (Final → Hint)

#### Glossar zur „Engine"-Bezeichnung (Welle E v4)

| Begriff | Bedeutet seit Welle E v4 |
|---|---|
| **„Engine"** (in `llm_engine_match_rate`, `engine_pattern_judge_ok_rate` etc.) | Die volle Override-Pipeline aus Safety + Pre-Route-Rules + LLM-Hint + Fallback. **NICHT** die ehemalige 3-Phasen-Score-Engine — die ist seit v4 aus dem Code. |
| **„Final-Pattern"** (neuer Alias) | Synonym zu „Engine"-Wahl. Beschreibt, was nach allen Override-Schichten als gewähltes Pattern herauskommt. |
| **„LLM-Hint"** | Was der Klassifikator-LLM als `pattern_id_hint` vorschlägt. Primärer Selektor, kann von Safety/Rules überstimmt werden. |
| **„Disagreement"** | LLM-Hint ≠ Final-Pattern ⇒ eine Rule oder Safety hat den Hint korrigiert. Die Disagreement-Statistik ist die zentrale **Daseinsberechtigungs-Telemetrie** für jede Routing-Rule. |
| **„Rule-Override besser"** | Bei Disagreement: Judge findet das Final-Pattern (nach Rule-Eingriff) angemessener als den rohen Hint → Rule wirkt korrigierend. |
| **„LLM-Hint allein besser"** | Bei Disagreement: Judge findet den ursprünglichen Hint besser → Rule hat den Hint kaputtgemacht oder ist falsch konfiguriert. |
| **„redundant"** (in Rules-Stats) | Rule feuert, Final-Pattern == LLM-Hint ⇒ Rule hat denselben Effekt wie der Hint allein und ist verzichtbar. |

---

## Wichtige Änderungen seit Welle E v3

| Was | Vorher (v3) | Jetzt (v4) | Wann |
|---|---|---|---|
| Pattern-Selektion | Hint-Shortcut + Phase 1+2 Fallback | Hint-Primary nur, Phase 1+2 entfernt | 2026-05-25 |
| `gate_*` Felder in MDs | aktiv | aus 15 MDs entfernt | 2026-05-25 |
| `signal_*_fit`, `page_bonus` | aktiv | entfernt | 2026-05-25 |
| Tie-Breaker | `01-base/tie-breaker.yaml` | gelöscht | 2026-05-25 |
| `lookup_intent_forces_pattern` | 7 Items, alle shadow | 0 Items (gelöscht) | 2026-05-25 |
| Pattern-MD-Format | gate-zentriert | inhaltszentriert | 2026-05-25 |
| Studio-PatternEditor | 6 Tabs (Identität/Gates/Scoring/Output/Tools/Anweisungen) | 5 Tabs (Identität/Antwort-Form/Tools/Slots/Anweisungen) | 2026-05-25 |
| Studio-PersonaEditor | gemischte Felder | Banner „Persona = Stil, nicht Pattern" | 2026-05-25 |
| Studio-QualityView | „Tight Races"-Card mit Score-Gap-Zähler | Card zeigt „—" mit Erklärung; Disagreement-Analyse in Eval-View | 2026-05-25 |
