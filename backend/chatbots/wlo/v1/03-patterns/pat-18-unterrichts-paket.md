---
id: PAT-18
label: Unterrichts-Paket
priority: 470
gate_personas: ["P-W-LK", "P-AND", "P-ELT"]
gate_states: ["*"]
gate_intents: ["*"]
signal_high_fit: ["ungeduldig", "effizient", "entscheidungsbereit"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: ["fach", "stufe"]
default_tone: sachlich
default_length: mittel
default_detail: standard
response_type: answer
sources: ["mcp"]
format_primary: cards
format_follow_up: none
tools: ["search_wlo_collections", "search_wlo_content", "get_collection_contents", "lookup_wlo_vocabulary", "get_node_details"]
---

# PAT-18: Unterrichts-Paket

## Kernregel
search_wlo_collections(Fach+Klasse) → best match → search_wlo_content. 3-5 Treffer.

## Wann aktiv
- Lehrkräfte mit bekanntem Fach + Stufe
- Ungeduldig, effizient, entscheidungsbereit

## Verhalten
- Erst Sammlungen suchen, dann Inhalte
- 3-5 kuratierte Treffer
- Bei fehlenden Slots: Degradation (PAT-06)
