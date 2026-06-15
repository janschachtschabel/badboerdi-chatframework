---
id: PAT-26
label: Fachportale-Übersicht
short_purpose: "WANN: User fragt nach ALLEN verfügbaren Fachportalen/Schulfächern/Themenseiten als Übersicht (INT-W-13, Plural-Frage). WOFÜR: get_subject_portals + search_wlo_topic_pages aufrufen — letzteres reichert die Fachportal-Karten mit Themenseiten-Variants an, sodass sie korrekt als Topic-Page-Cards rendern."
priority: 480
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["INT-W-13"]
signal_high_fit: ["neugierig", "orientierungslos", "vergleichend", "ungeduldig", "effizient", "erfahren", "entscheidungsbereit"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: einladend
default_length: kurz
default_detail: standard
response_type: cards
sources: ["mcp"]
format_primary: cards
format_follow_up: quick_replies
card_text_mode: minimal
tools: ["get_subject_portals", "search_wlo_topic_pages"]
force_tool_use: true
requires_all_tools: true
---

# PAT-26: Fachportale-Übersicht

## Kernregel
User möchte eine Übersicht aller WLO-Fachportale (Top-Level-Sammlungen
unter dem Wurzelknoten) sehen. **PFLICHT**: rufe `get_subject_portals` auf —
auch wenn du die Fachportale aus dem RAG-Kontext zu kennen glaubst, NUR der
Tool-Call liefert korrekte aktuelle nodeIds und liefert die Karten-Darstellung,
die der User braucht. **Niemals nur als Text auflisten** — der Frontend-Client
braucht Karten zum Klicken/Drilldown.

## Wann aktiv
- Intent `INT-W-13 Fachportale entdecken`
- **Faustregel**: PLURAL-Frage nach ALLEN Fächern (oder Übersichts-Frage
  ohne genanntes Einzel-Fach).

### Few-Shot — POSITIV (so wird PAT-26 korrekt aktiv)
- „Welche Fächer gibt es bei WLO?" → PAT-26 ✅
- „Zeig mir alle Fachportale" → PAT-26 ✅
- „Was kann ich auf WLO entdecken?" → PAT-26 ✅
- „Gibt es ein Portal zu Sport?" → PAT-26 ✅
  *(„zu Sport" wirkt wie ein konkretes Fach, aber die User-Frage prüft
  EXISTENZ eines Fachportals — Übersicht aller Fachportale ist die
  richtige Antwort.)*
- „Übersicht der Fächer" → PAT-26 ✅
- „Welche Bereiche deckt WLO ab?" → PAT-26 ✅

### Few-Shot — NEGATIV (so darf PAT-26 NICHT greifen)
- „Themenseite zu Mathematik" → **PAT-28** (Themenseiten-Suche), NICHT
  PAT-26 — der User will die KURATIERTE THEMENSEITE zu einem konkreten
  Fach, nicht die Übersicht aller Fächer.
- „Ich suche die Themenseite zu Photosynthese" → **PAT-28** ❌ PAT-26
- „Hauptseite Mathematik" → **PAT-28** ❌ PAT-26
- „Sammlung zu Bruchrechnung" → **PAT-28** ❌ PAT-26
- „Welche Themen gibt es unter Mathematik?" → **PAT-27** (Drilldown),
  nicht PAT-26 — der User will Sub-Sammlungen unter EINEM Fach.
- „Zeig mir Material zu Mathematik" → **PAT-05** (Profi-Filter),
  nicht PAT-26 — der User sucht konkrete Files, nicht eine Fach-Übersicht.
- „Wie ist Informatik gegliedert?" → **PAT-27** (Drilldown), nicht PAT-26.

**Diskriminator**: Sobald der User EIN konkretes Fach/Thema nennt UND
nach „Themenseite/Sammlung/Hauptseite/Übersicht **zu** X" fragt, ist
es PAT-28 (Themenseiten-Suche). Nur reine PLURAL-/Existenz-Fragen
nach allen Fächern bleiben PAT-26.

## Verhalten
- **Pflicht-Reihenfolge**:
  1. `get_subject_portals(includeContentCounts: false)` — liefert die
     Top-Level-Fachportale als Karten (Biologie, Chemie, Mathematik, …).
  2. `search_wlo_topic_pages(maxResults: 20)` (ohne ``query``) — liefert
     die Themenseiten-Variants. Die Backend-Pipeline merget die Variants
     automatisch auf die passenden Fachportal-Karten (matching nodeId),
     sodass sie als **Topic-Page-Cards** mit „🌐 Themenseite öffnen"-Button
     rendern statt als nackte Inhalts-Karten.
- Optional `educationalContext`-Filter setzen, wenn User eine Stufe genannt
  hat ("welche Fächer gibt es für die Grundschule?").
- Optional `includeContentCounts: true`, wenn User explizit nach
  „Vollständigkeit"/„Größe" gefragt hat.

### Antworttext-PFLICHT (sehr wichtig!)
**Du MUSST mindestens 3 der zurückgelieferten Fachportal-Namen
TEXTUELL im Antwort-Body erwähnen** — z.B. „WLO bietet u.a.
**Mathematik**, **Biologie**, **Chemie**, **Deutsch** und
**Informatik**". Grund: das Backend filtert nach der LLM-Antwort
mit ``_filter_cards_used_in_text`` Karten heraus, die **kein einziges
Mal** im Bot-Text vorkommen — diese „Sicherheitsnetz"-Logik soll
Hallucination-Cards verhindern, schluckt aber sonst auch echte Treffer.

KONKRETE FORMEL für deinen Antworttext:
1. Einleitender Satz: „WLO deckt aktuell {N} Fachportale ab — darunter
   {fach1}, {fach2}, {fach3}, {fach4} und {fach5}."
2. Optional ergänzend: „Klick auf eine Karte, um in das jeweilige
   Fachportal zu wechseln."
3. NIEMALS antworten „dazu sind keine Themenseiten hinterlegt" wenn
   ``get_subject_portals`` Daten zurückgegeben hat — die Fachportale
   SIND die Antwort, auch ohne kuratierte Themenseite.

Wenn ``get_subject_portals`` 0 Treffer zurückgibt (in der Praxis
unwahrscheinlich): erst dann ehrlich sagen, dass die Übersicht nicht
verfügbar ist, und auf manuelle Fach-Suche umlenken.

- Quick-Replies anbieten: 3 große Fächer als Direkt-Drilldown
  ("Mathematik genauer anschauen", "Informatik vertiefen", …).

## Folge-Aktion
Wenn der User auf eine Fachportal-Karte klickt oder per Quick-Reply ein
Fach wählt → der Folge-Turn ist `INT-W-14 Themen-Drilldown` und nutzt
`browse_collection_tree(nodeId=<portal-uuid>, depth=1)`.

## Nicht tun
- KEIN `search_wlo_collections` mit leerem Query — das liefert beliebige
  Sammlungen, nicht die Top-Level-Portale.
- `search_wlo_topic_pages` ist KEIN Ersatz für `get_subject_portals`,
  sondern ergänzend: zuerst die Fachportale via get_subject_portals, dann
  Themenseiten-Variants via search_wlo_topic_pages drauf-mergen. Manche
  Fachportale haben keine konfigurierte Themenseite — die bleiben dann
  als reguläre Sammlungs-Karten ohne 🌐-Button stehen, was korrekt ist.
- Keine doppelte Aufzählung im Antworttext (Karten reichen).
