---
id: PAT-06
label: Degradation-Brücke
priority: 600
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["*"]
signal_high_fit: []
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
tools: ["search_wlo_collections", "search_wlo_content", "lookup_wlo_vocabulary", "get_node_details"]
---

# PAT-06: Degradation-Brücke

## Kernregel
Breite Suche ohne fehlende Parameter + Soft Probe gleichzeitig. Nie blockieren.
IMMER zuerst search_wlo_collections aufrufen. Nur wenn noetig danach search_wlo_content.

## Wann aktiv
- Wenn Preconditions eines höherprioren Patterns nicht erfüllt sind
- Universell einsetzbar
- Wenn der User ein Thema nennt aber Details fehlen

## Verhalten
- SOFORT suchen mit dem was bekannt ist — nie blockieren weil Info fehlt
- Suboptimales Ergebnis > kein Ergebnis
- Paralleles Suchen + beilaeufig Nachfragen
- R-01 Guardrail umsetzen
