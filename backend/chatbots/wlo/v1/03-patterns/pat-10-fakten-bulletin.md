---
id: PAT-10
label: Fakten-Bulletin
priority: 460
gate_personas: ["P-W-POL", "P-W-PRESSE", "P-AND", "P-W-LK", "P-BER", "P-VER"]
gate_states: ["*"]
gate_intents: ["INT-W-01", "INT-W-06", "INT-W-09"]
signal_high_fit: ["ungeduldig", "zielgerichtet", "effizient"]
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
tools: ["get_wirlernenonline_info", "get_metaventis_info"]
---

# PAT-10: Fakten-Bulletin

## Kernregel
Bullet-Facts, zitierfähig. Kein Suche-Angebot.

## Wann aktiv
- Politik oder Presse
- R-03: Kein Suche-Angebot für diese Personas

## Verhalten
- Zitierfähige Fakten
- Bullet-Point-Format
- Keine Suche anbieten
