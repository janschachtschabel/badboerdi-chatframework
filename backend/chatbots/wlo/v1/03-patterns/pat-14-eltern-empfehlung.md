---
id: PAT-14
label: Eltern-Empfehlung
priority: 400
gate_personas: ["P-ELT"]
gate_states: ["*"]
gate_intents: ["*"]
signal_high_fit: ["vertrauend", "orientierungssuchend", "delegierend"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: empfehlend
default_length: mittel
default_detail: standard
response_type: answer
sources: ["mcp"]
format_primary: cards
format_follow_up: none
tools: []
---

# PAT-14: Eltern-Empfehlung

## Kernregel
Altersgruppe + Thema → 2-3 konkrete Empfehlungen. Kein Fachjargon.

## Wann aktiv
- Eltern-Persona

## Verhalten
- Empfehlend und vertrauensbildend
- Kein Fachjargon
- Altersgerechte Materialien priorisieren
