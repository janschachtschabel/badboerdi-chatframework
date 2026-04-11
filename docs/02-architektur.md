# Architektur — Die 5 Schichten

## Warum 5 Schichten?

Chatbot-Prompts werden schnell lang und unstrukturiert. BadBoerdi loest das durch eine **5-Schichten-Architektur**: Jede Schicht hat eine klare Aufgabe, wird als separate Datei gepflegt und erst zur Laufzeit zum finalen System-Prompt zusammengesetzt.

**Vorteile:**
- **Kein Prompt-Overload** — Nicht jede Schicht ist in jeder Nachricht aktiv. Schicht 5 (Wissen) wird nur bei Bedarf geladen; Schicht 4 (Dimensionen) wird dynamisch gefiltert.
- **Token-Management** — Bei Ueberschreitung des Token-Limits werden Schichten nach Prioritaet entladen (5 → 4 → 3), Schichten 1-2 bleiben immer.
- **Separation of Concerns** — Persona-Text, Sicherheit, Fachregeln, Gespraechsmuster und Wissen sind unabhaengig editierbar.
- **Studio-Kompatibilitaet** — Jede Schicht/jedes Element hat eine eigene Datei → Studio kann gezielt einzelne Elemente laden und speichern.

---

## Schicht 1: Identitaet & Schutz

**Pfad:** `chatbots/wlo/v1/01-base/`

**Dateien:**
| Datei | Zweck |
|-------|-------|
| `base-persona.md` | Grundlegende Identitaet: Name (BOERDi), Rolle (blaue Eule von WLO), Tonalitaet, Verhalten |
| `guardrails.md` | Harte Regeln, die nie ueberschrieben werden (z.B. nie blockieren, max. 1 Frage pro Turn) |
| `safety-config.yaml` | Sicherheits-Presets (off/basic/standard/strict/paranoid) mit Stufenkonfiguration fuer Regex, Moderation, Legal-Classifier |
| `device-config.yaml` | Geraete-spezifische Limits (max_items) und Persona-Anrede (Sie/du/neutral) |

**Im Prompt:** `base-persona.md` steht am Anfang, `guardrails.md` **immer am Ende** (nicht ueberschreibbar).

**Prioritaet:** 1000 (hoechste) — wird **nie** entladen.

---

## Schicht 2: Domain & Regeln

**Pfad:** `chatbots/wlo/v1/02-domain/`

**Dateien:**
| Datei | Zweck |
|-------|-------|
| `domain-rules.md` | Plattform-spezifische Regeln (Such-Strategie, Themenseiten-Integration, Disambiguierung, Seitenkontext-Reaktionen, Vollstaendigkeitspruefung) |
| `policy.yaml` | Strukturelle Berechtigungen: Tool-Blockaden pro Persona/Intent, Disclaimer-Texte, Regex-basierte Sperren |
| `wlo-plattform-wissen.md` | Faktenwissen ueber WLO (Struktur, Angebote, Zielgruppen) |

**Im Prompt:** Direkt nach der Persona, vor den Patterns.

**Prioritaet:** 900 — wird **nie** entladen.

**Beispiel-Policy:**
```yaml
- id: pol-presse-only-public
  match:
    persona: P-W-PRESSE
  effect:
    disclaimer: "Hinweis: Es werden ausschliesslich oeffentlich verfuegbare Inhalte angezeigt."
```

---

## Schicht 3: Patterns (Gespraechsmuster)

**Pfad:** `chatbots/wlo/v1/03-patterns/`

**20 Patterns** (PAT-01 bis PAT-20) definieren, *wie* der Bot auf verschiedene Situationen reagiert. Jedes Pattern ist eine Markdown-Datei mit YAML-Frontmatter.

**Auswahl-Mechanismus (Pattern-Engine, 3 Phasen):**
1. **Gate-Pruefung** — Passt Persona, State, Intent? UND: Sind alle `precondition_slots` gefuellt? (Hard Gate — z.B. PAT-19 braucht fach+stufe+thema; fehlt eines, wird das Pattern eliminiert, nicht nur schlechter bewertet)
2. **Scoring** — Signal-Fit-Gewichte + Page-Bonus + Entity-Vollstaendigkeit → gewichteter Score
3. **Modulation** — Signale ueberschreiben Defaults (Ton, Laenge, skip_intro)

**Pattern-Anatomie (Beispiel PAT-01 Direkt-Antwort):**
```yaml
id: PAT-01
label: Direkt-Antwort
priority: 500
gate_personas: ["*"]          # Alle Personas erlaubt
gate_states: ["*"]            # Alle States erlaubt
gate_intents: ["*"]           # Alle Intents erlaubt
signal_high_fit: ["ungeduldig", "effizient", "erfahren"]
default_tone: sachlich
default_length: kurz
sources: ["mcp"]              # Darf MCP-Tools nutzen
tools: []                     # Keine spezifischen Tools erzwungen
```

**Wichtige Steuerungsfelder:**
- `sources: ["mcp"]` → MCP-Tools erlaubt
- `sources: ["rag"]` → Nur RAG-Wissen, kein MCP
- `sources: []` → Reine Text-Antwort, keine externen Quellen
- `tools: ["search_wlo_collections"]` → Spezifische Tools erzwungen

**Im Prompt:** Nur das **gewinnende** Pattern wird eingesetzt (nicht alle 20).

**Prioritaet:** 500-800 — kann bei Token-Knappheit entladen werden (Fallback: PAT-06 Degradation).

---

## Schicht 4: Dimensionen

**Pfad:** `chatbots/wlo/v1/04-*/`

Schicht 4 besteht aus **6 Element-Typen**, die zur Laufzeit dynamisch gefiltert und kombiniert werden:

| Verzeichnis | Element-Typ | Anzahl | Beschreibung |
|------------|-------------|--------|--------------|
| `04-personas/` | Personas | 9 | Nutzergruppen (Lehrkraft, Schueler, Eltern, Presse, ...) |
| `04-intents/` | Intents | 10 | Erkannte Absichten (WLO kennenlernen, Material suchen, ...) |
| `04-entities/` | Entities | 5 | Extrahierte Slots (Fach, Stufe, Thema, Medientyp, Lizenz) |
| `04-signals/` | Signale | 17 | Emotionale/situative Hinweise in 4 Dimensionen (Zeit, Sicherheit, Haltung, Kontext) |
| `04-states/` | States | 11 | Gespraechszustaende (Orientierung → Suche → Kuratierung → Feedback) |
| `04-contexts/` | Kontexte | 4 | Seitenbasierte Situationen (Suchseite, Sammlungsdetail, Mobil, ...) |

**Im Prompt:** Nur die **erkannte Persona**, der **aktive Intent** und die **detektierten Signale** werden eingefuegt — nicht alle 9 Personas oder 10 Intents.

**Prioritaet:** 300-600 — kann teilweise entladen werden.

---

## Schicht 5: Wissen

**Pfad:** `chatbots/wlo/v1/05-knowledge/`

**Dateien:**
| Datei | Zweck |
|-------|-------|
| `rag-config.yaml` | RAG-Bereichskonfiguration (mode: always/on-demand, Beschreibung) |
| `mcp-servers.yaml` | MCP-Server-Registry mit Tool-Definitionen |

**Seed-System:**
Das Backend liefert eine initiale Wissensbasis als `knowledge/rag-seed.json` mit (aktuell 348 Chunks in 4 Bereichen). Bei einer Neuinstallation (leere Datenbank) werden die Chunks automatisch importiert und Embeddings im Hintergrund generiert. Export/Re-Export ueber `python scripts/rag_export.py --db <pfad>`.

**Zwei Wissensquellen:**

### RAG-Wissensbereiche
- **Always-On** (z.B. `wirlernenonline.de-webseite`, `edu-sharing-com-webseite`): Werden bei jeder Nachricht automatisch als Kontext eingebunden
- **On-Demand**: Werden nur geladen, wenn das aktive Pattern `sources: ["rag"]` hat und der LLM das Tool `query_knowledge` aufruft
- Dokumente werden per Studio hochgeladen (Datei/URL/Freitext), in Chunks zerlegt und als Vektoren in SQLite-Vec gespeichert

### MCP-Server (externe Tools)
- Derzeit 1 Server: **WLO edu-sharing** (11 Tools)
- Tools: `search_wlo_collections`, `search_wlo_content`, `get_collection_contents`, `get_node_details`, `lookup_wlo_vocabulary`, `search_wlo_topic_pages`, `get_wirlernenonline_info`, `get_edu_sharing_product_info`, `get_edu_sharing_network_info`, `get_metaventis_info`, u.a.
- `search_wlo_topic_pages` unterstuetzt zielgruppenspezifische Varianten (teacher/learner/general) und wird persona-basiert sortiert
- Server werden per Studio registriert (URL eingeben → automatische Tool-Discovery)

**Im Prompt:** RAG-Kontext wird als synthetisches Tool-Call/Result-Paar injiziert. MCP-Tools werden als OpenAI-Function-Definitions bereitgestellt und vom LLM bei Bedarf aufgerufen.

**Prioritaet:** 100-200 — wird als erstes entladen bei Token-Knappheit.

---

## Prompt-Zusammensetzung zur Laufzeit

```
System-Prompt (zusammengesetzt aus):
+----------------------------------+
| Schicht 1: base-persona.md      |  <-- immer
+----------------------------------+
| Schicht 2: domain-rules.md      |  <-- immer
|            wlo-plattform-wissen  |
+----------------------------------+
| Schicht 4: Persona-Prompt       |  <-- nur erkannte Persona
|            Intent-Kontext        |
|            Signal-Modulationen   |
+----------------------------------+
| Schicht 3: Pattern-Block        |  <-- nur das gewinnende Pattern
+----------------------------------+
| Schicht 5: RAG-Kontext          |  <-- nur bei always-on Areas
+----------------------------------+
| Schicht 1: guardrails.md        |  <-- IMMER am Ende
+----------------------------------+

Nachrichten:
+----------------------------------+
| Gespraechsverlauf (max. 20 Turns)|
| Aktuelle Nutzernachricht         |
| [RAG-Prefetch Tool-Call/Result]  |  <-- optional
| [MCP-Prefetch Tool-Call/Result]  |  <-- optional
+----------------------------------+

Tools (Function-Definitions):
+----------------------------------+
| MCP-Tools (wenn sources=["mcp"])|
| query_knowledge (wenn on-demand)|
+----------------------------------+
```

**Token-Budget-Management:**
Wenn der zusammengesetzte Prompt das Kontextfenster ueberschreitet, werden Schichten nach Prioritaet entladen:
1. Schicht 5 (Wissen) → wird entfernt
2. Schicht 4 (Dimensionen) → wird reduziert
3. Schicht 3 (Pattern) → Fallback auf PAT-06 Degradation
4. Schichten 1-2 → werden **nie** entfernt
