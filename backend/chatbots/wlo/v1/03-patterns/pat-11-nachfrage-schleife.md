---
id: PAT-11
label: Nachfrage-Schleife
priority: 380
gate_personas: ["*"]
gate_states: ["state-9"]
gate_intents: ["*"]
signal_high_fit: []
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: sachlich
default_length: kurz
default_detail: standard
response_type: question
sources: ["mcp"]
format_primary: text
format_follow_up: quick_replies
card_text_mode: minimal
tools: []
---

# PAT-11: Nachfrage-Schleife

## Kernregel
'Hat das gepasst?' → wenn nein: sofort Fallback. Kurz.

## Wann aktiv
- Im Evaluation/Feedback-State

## Verhalten
- Kurze Zufriedenheitsfrage
- Bei Nein: sofort alternative Ergebnisse
- Max. 3 Refinement-Zyklen (R-07)
