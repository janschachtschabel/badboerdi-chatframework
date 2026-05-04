---
id: PAT-27
label: Themen-Drilldown
short_purpose: "WANN: User will Sub-Themen/Bereiche eines KONKRETEN Fachs/Sammlung sehen (INT-W-14, Singular-Fach + Drilldown-Verb). WOFÜR: ZUERST get_subject_portals (UUID fuer das Fach holen), DANN browse_collection_tree mit DIESER UUID."
# Priority 500: muss gegen PAT-16 Themen-Exploration (priority 400 +
# spec_bonus 0.02) gewinnen, wenn beide für INT-W-14 in Frage kommen.
# Eval 2026-05-03 zeigte: PAT-16 schlug PAT-27 knapp (0.060 vs 0.057),
# weil PAT-16 mehr spezifische Gates hat. Mit priority 500 ist der
# Priority-Vorsprung 0.013, deutlich über PAT-16's spec-bonus.
priority: 500
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
tools: ["get_subject_portals", "browse_collection_tree"]
force_tool_use: true
requires_all_tools: true
core_rule: |
  ZWEI-SCHRITT-FLOW:
  1. ``get_subject_portals(includeContentCounts: false)`` aufrufen, um die nodeId
     des gewuenschten Fachs zu erhalten. Filtere die Antwort nach dem Fachnamen
     aus ``entities.fach`` (z.B. "Mathematik").
  2. ``browse_collection_tree(nodeId=<gefundene UUID>, depth: 1,
     includeContentCounts: true)`` mit der UUID des Top-Treffers.
  Nur SO bekommst du die richtigen Sub-Themen. Erfindest du eine UUID
  oder uebernimmst sie aus Beispielen → falsche Ergebnisse.
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
**KRITISCH — und der haeufigste Fehler**: `browse_collection_tree(nodeId=...)`
erwartet eine UUID, NIEMALS einen Fach-Namen wie `'Informatik'` oder
`'Mathematik'`. Wer das ignoriert, bekommt leere oder FALSCHE Antworten
(z.B. Informatik-Sammlungen, weil ein Beispiel-UUID kopiert wurde).

**REGEL: Du kennst die UUID NICHT.** Erfinde sie nicht. Kopiere sie
nicht aus Pattern-Doc, vorherigen Turns oder Trainingsdaten. Hole sie
in einem expliziten Tool-Call.

Damit `browse_collection_tree` aufgerufen werden kann, muss zuerst
eine UUID beschafft werden. Drei Wege:

1. **Aus Page-Context oder vorherigem Turn**: wenn der User auf einer
   Sammlungs-Karte ist (page_context.collection_id) oder im letzten Turn
   ein Fachportal angezeigt wurde, ist die nodeId in `entities.thema` /
   `entities.collection_id` / `session_state` zu finden — und dann
   ausschliesslich DIESE konkrete UUID nutzen.

2. **Über Fachname auflösen** (haeufigster Fall): wenn `entities.fach`
   gesetzt ist (z.B. "Mathematik"), MUSS zuerst
   `get_subject_portals(includeContentCounts: false)` aufgerufen werden.
   Aus der Antwort den Eintrag mit `title == entities.fach` (oder dem
   semantisch nahesten Treffer) waehlen und DESSEN `nodeId` an
   `browse_collection_tree` weitergeben.

3. **Über Sammlungs-Suche**: wenn nur ein Thema-String genannt wurde
   ("Algebra"), erst `search_wlo_collections(query, maxResults: 3)`,
   dann den Top-Treffer als Eltern-Sammlung nehmen.

**NIEMALS** eine UUID aus diesem Pattern-Doc oder aus Beispielen
verwenden — die sind aus didaktischen Gruenden vorhanden und zeigen
NICHT auf das vom User gewuenschte Fach.

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