---
id: PAT-16
label: Themen-Exploration
priority: 400
gate_personas: ["P-W-RED", "P-BER"]
gate_states: ["state-4", "state-10"]
gate_intents: ["*"]
signal_high_fit: ["neugierig", "vergleichend", "validierend"]
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

# PAT-16: Themen-Exploration

## Kernregel
Themengebiete identifizieren, Lücken erkennen.

## Wann aktiv
- Redakteur:innen oder Berater:innen
- In Discovery oder Recherche-States

## Verhalten
- Themenlandschaft erkunden
- Lücken identifizieren
- Vergleichende Analyse
