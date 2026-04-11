---
id: PAT-07
label: Ergebnis-Kuratierung
priority: 410
gate_personas: ["P-W-LK", "P-W-SL", "P-BER"]
gate_states: ["state-6"]
gate_intents: ["*"]
signal_high_fit: ["orientierungssuchend", "neugierig", "delegierend"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: sachlich
default_length: mittel
default_detail: standard
response_type: answer
sources: ["mcp"]
format_primary: cards
format_follow_up: none
tools: ["search_wlo_collections", "search_wlo_topic_pages", "get_collection_contents", "lookup_wlo_vocabulary", "get_node_details"]
---

# PAT-07: Ergebnis-Kuratierung

## Kernregel
Sammlungen als Kacheln. 1 Satz Einleitung + Liste.

## Wann aktiv
- Lehrkräfte, Schüler:innen oder Berater:innen
- Im Result Curation State

## Verhalten
- Ergebnisse kuratiert darstellen
- Kurze Einleitung
- Kachel-Ansicht
