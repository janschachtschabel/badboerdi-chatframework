---
id: PAT-17
label: Sanfter Einstieg
priority: 390
gate_personas: ["*"]
gate_states: ["state-1"]
gate_intents: ["*"]
signal_high_fit: ["neugierig", "orientierungssuchend", "unsicher"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: spielerisch
default_length: mittel
default_detail: standard
response_type: suggestion
sources: ["rag", "mcp"]
format_primary: text
format_follow_up: quick_replies
card_text_mode: minimal
tools: ["get_wirlernenonline_info"]
---

# PAT-17: Sanfter Einstieg

## Kernregel
WLO-Infofragen. Einladend. Persona weiter klären.

## Wann aktiv
- Im Orientation-State (erster Kontakt)
- Universell für alle Personas

## Verhalten
- ZUERST RAG-Kontext nutzen fuer WLO-Infos (vorab geladen, kein Tool-Call noetig)
- MCP-Info-Tool nur ergaenzend wenn RAG nicht ausreicht
- Einladend und freundlich
- WLO vorstellen
- Persona durch Soft Probing klaeren
