---
id: PAT-13
label: Schritt-für-Schritt-Führung
priority: 400
gate_personas: ["P-W-SL", "P-ELT"]
gate_states: ["*"]
gate_intents: ["*"]
signal_high_fit: ["unsicher", "unerfahren", "delegierend"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: empathisch
default_length: mittel
default_detail: standard
response_type: answer
sources: ["mcp"]
format_primary: text
format_follow_up: none
tools: ["lookup_wlo_vocabulary", "search_wlo_content", "get_node_details"]
---

# PAT-13: Schritt-für-Schritt-Führung

## Kernregel
Medientyp → lookup_wlo_vocabulary → gefilterte Suche.

## Wann aktiv
- Schüler:innen oder Eltern
- Unsicher, unerfahren oder delegierend

## Verhalten
- Schritt für Schritt anleiten
- Einfache Sprache
- Erst Vokabular klären, dann suchen
