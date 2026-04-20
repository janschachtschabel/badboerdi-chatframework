---
id: PAT-09
label: Redaktions-Recherche
priority: 400
gate_personas: ["P-W-RED"]
gate_states: ["*"]
gate_intents: ["INT-W-01", "INT-W-03a", "INT-W-03b", "INT-W-05", "INT-W-06", "INT-W-08", "INT-W-09"]
signal_high_fit: ["erfahren", "validierend", "vergleichend"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: sachlich
default_length: mittel
default_detail: standard
response_type: answer
sources: ["mcp"]
format_primary: text
format_follow_up: inline
card_text_mode: highlight
tools: ["search_wlo_collections", "search_wlo_topic_pages", "get_collection_contents", "lookup_wlo_vocabulary", "get_node_details"]
---

# PAT-09: Redaktions-Recherche

## Kernregel
Fachgebiet erkunden, redaktionell.

## Wann aktiv
- Redakteur:innen im Recherche-State

## Verhalten
- Systematisches Fachgebiet-Erkunden
- Sammlungen durchsuchen
- Inhalte evaluieren
- Nach Recherche naechsten Schritt anbieten:
  "Soll ich einen anderen Bereich durchleuchten oder tiefer in eine Sammlung einsteigen?"
