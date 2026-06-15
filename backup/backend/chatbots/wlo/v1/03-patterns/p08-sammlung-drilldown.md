---
id: P8
label: Sammlung-Drilldown
short_purpose: "WANN: User klickt eine Sammlung an oder fragt nach Unterthemen einer Sammlung ('zeig mir Algebra in Mathematik', 'was ist in dieser Sammlung?'). WOFÜR: Navigation im Themenbaum — Untersammlungen + Inhalte der gewählten Ebene zeigen."
priority: 500
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["*"]
precondition_slots: []
default_tone: sachlich
default_length: mittel
default_detail: standard
response_type: answer
sources: ["mcp"]
tools: ["browse_collection_tree", "get_collection_contents", "lookup_wlo_vocabulary"]
rag_areas: []
format_primary: cards
format_follow_up: quick_replies
card_text_mode: reference
force_tool_use: true
---

# P8: Sammlung-Drilldown

## Kernregel
User navigiert tiefer in einen Themenbaum. Tool-Layer löst die
gewünschte Sammlung auf (entweder via `collection_id` aus dem Klick
oder via `thema`/`fach` aus Slots) und zeigt:

1. **Untersammlungen** (wenn vorhanden) als Cards
2. **Direkt-Inhalte** der gewählten Ebene (wenn keine Untersammlungen
   oder wenig)

## Verhalten
- Wenn Sammlung hat Untersammlungen + Inhalte: zeige BEIDE, klar
  getrennt („Themen weiter unten:", „Inhalte direkt hier:").
- Bei tiefer Verschachtelung: zeig im Antwort-Text den Pfad
  (z.B. „Mathematik → Algebra → Lineare Gleichungen").
- Quick-Replies: 2–3 Unterthemen oder „nach oben".

## Nicht tun
- KEINE Suche außerhalb der angeklickten Sammlung — bleib im Baum.
- KEINE Lernpfad-Erstellung — das ist P9.
