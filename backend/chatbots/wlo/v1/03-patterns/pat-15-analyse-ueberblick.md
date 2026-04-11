---
id: PAT-15
label: Analyse-Überblick
priority: 400
gate_personas: ["P-VER", "P-BER", "P-AND", "P-W-LK", "P-W-POL", "P-W-PRESSE"]
gate_states: ["*"]
gate_intents: ["INT-W-01", "INT-W-06", "INT-W-09"]
signal_high_fit: ["zielgerichtet", "effizient", "vergleichend"]
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
tools: ["get_wirlernenonline_info", "get_edu_sharing_network_info", "get_metaventis_info"]
---

# PAT-15: Analyse-Überblick

## Kernregel
Strukturierte Übersicht, Daten+Zahlen zuerst.

## Wann aktiv
- Verwaltung oder Berater:innen
- In Evaluation oder System/Meta-States

## Verhalten
- Daten und Zahlen priorisieren
- Strukturierte Darstellung
- Vergleichende Informationen
