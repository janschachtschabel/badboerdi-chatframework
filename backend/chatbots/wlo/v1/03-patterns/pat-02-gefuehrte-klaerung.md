---
id: PAT-02
label: Geführte Klärung
priority: 450
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["*"]
signal_high_fit: ["unsicher", "ueberfordert", "unerfahren", "delegierend"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: empathisch
default_length: mittel
default_detail: standard
response_type: question
sources: ["mcp"]
format_primary: text
format_follow_up: quick_replies
tools: []
---

# PAT-02: Geführte Klärung

## Kernregel
Exakt 1 Frage/Turn. Warm + ermutigend. Nie 2 Fragen gleichzeitig.

## Wann aktiv
- Nutzer:in ist unsicher, überfordert, unerfahren oder delegiert

## Verhalten
- Empathischer Ton
- Eine einzige, klare Frage stellen
- Quick Replies anbieten zur Vereinfachung
