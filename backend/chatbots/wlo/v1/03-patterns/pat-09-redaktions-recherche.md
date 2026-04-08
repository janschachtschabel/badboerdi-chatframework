---
id: PAT-09
label: Redaktions-Recherche
priority: 400
gate_personas: ["P-W-RED"]
gate_states: ["state-10"]
gate_intents: ["*"]
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
format_follow_up: none
tools: ["search_wlo_collections", "get_collection_contents", "lookup_wlo_vocabulary", "get_node_details"]
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
