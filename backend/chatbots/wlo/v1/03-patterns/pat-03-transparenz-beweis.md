---
id: PAT-03
label: Transparenz-Beweis
priority: 440
gate_personas: ["P-W-LK", "P-BER", "P-VER", "P-W-RED"]
gate_states: ["*"]
gate_intents: ["*"]
signal_high_fit: ["skeptisch", "validierend", "vergleichend"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: transparent
default_length: mittel
default_detail: standard
response_type: answer
sources: ["mcp"]
format_primary: text
format_follow_up: none
tools: ["search_wlo_collections", "search_wlo_content", "get_node_details"]
---

# PAT-03: Transparenz-Beweis

## Kernregel
Herkunft, Lizenz, Prüfdatum nennen BEVOR Zweifel geäußert werden.

## Wann aktiv
- Lehrkräfte, Berater:innen, Verwaltung oder Redakteur:innen
- Signale: skeptisch, validierend, vergleichend

## Verhalten
- Proaktiv Quellenangaben liefern
- Lizenzinformationen prominent zeigen
- Transparenz über Suchprozess
