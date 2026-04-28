---
id: PAT-27
label: Themen-Drilldown
priority: 470
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["INT-W-14"]
signal_high_fit: ["vergleichend", "neugierig", "validierend", "ungeduldig", "effizient", "erfahren", "entscheidungsbereit"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: sachlich
default_length: kurz
default_detail: standard
response_type: cards
sources: ["mcp"]
rag_areas: []
format_primary: cards
format_follow_up: quick_replies
card_text_mode: minimal
tools: ["search_wlo_collections", "get_subject_portals", "browse_collection_tree"]
core_rule: ""
---

# PAT-27: Themen-Drilldown

## Kernregel
User will die **Sub-Sammlungen unter einer existierenden Sammlung oder Fachportal** sehen
(NICHT die Files). Tool: `browse_collection_tree`.

## Wann aktiv
- Intent `INT-W-14 Themen-Drilldown`
- Typische User-Inputs:
  - "Welche Themen gibt es unter Mathematik?"
  - "Zeig mir die Bereiche unter Informatik"
  - "Gliedere Biologie auf"
  - "In welche Unterthemen ist Geschichte aufgeteilt?"

## Vorbedingung: nodeId der Eltern-Sammlung — UUID, NICHT Fach-Name!
**KRITISCH**: `browse_collection_tree(nodeId=...)` erwartet eine UUID
wie `742d8c87-e5a3-4658-86f9-419c2cea6574`, NIEMALS einen Fach-Namen
wie `'Informatik'`. Wer das ignoriert, bekommt leere Antworten.

Damit `browse_collection_tree` aufgerufen werden kann, muss zuerst
eine UUID beschafft werden. Drei Wege:

1. **Aus Page-Context oder vorherigem Turn**: wenn der User auf einer
   Sammlungs-Karte ist (page_context.collection_id) oder im letzten Turn
   ein Fachportal angezeigt wurde, ist die nodeId in `entities.thema` /
   `entities.collection_id` / `session_state` zu finden.

2. **Über Fachname auflösen**: wenn `entities.fach` gesetzt ist (z.B.
   "Mathematik"), erst `get_subject_portals(includeContentCounts: false)`
   aufrufen, das passende Portal anhand des Titels finden, dann mit
   dessen nodeId `browse_collection_tree`.

3. **Über Sammlungs-Suche**: wenn nur ein Thema-String genannt wurde
   ("Algebra"), erst `search_wlo_collections(query, maxResults: 3)`,
   dann den Top-Treffer als Eltern-Sammlung nehmen.

## Verhalten
- `browse_collection_tree(nodeId, depth: 1, includeContentCounts: true)`
  als Default. Tiefe 2 nur, wenn User explizit nach "vollständige
  Gliederung" oder "alles auflisten" fragt — sonst ist die Antwort zu
  groß und langsam.
- Antwort als Karten-Liste mit File-Counts pro Sub-Sammlung.
- Antworttext kurz: "Unter **Mathematik** sind das die Bereiche:" —
  dann die Karten.
- Quick-Replies: 2–3 spannendste Sub-Sammlungen als Vertiefungs-Vorschläge
  ("Algebra genauer anschauen", "Geometrie vertiefen") plus
  "Materialien aus Mathematik direkt zeigen" als Fallback zu INT-W-03b.

## Folge-Aktion
Wenn User eine Sub-Sammlung wählt → kann erneut INT-W-14 (tieferer
Drilldown) oder INT-W-03b (Files zeigen) sein. Klassifikator entscheidet
basierend auf der User-Antwort.

## Nicht tun
- KEIN `get_collection_contents` mit `contentFilter: "folders"` als Ersatz
  — `browse_collection_tree` ist klarer im Output (Tree-Struktur, optional
  File-Counts) und der Pattern-Engine besser zuordenbar.
- Keine vorzeitige File-Suche — User wollte zuerst Struktur sehen, nicht
  Materialien.
- Bei `depth: 2` keine vollständige Tree-Aufzählung im Text — nur die
  Karten zeigen.