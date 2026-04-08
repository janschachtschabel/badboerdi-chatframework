---
id: PAT-01
label: Direkt-Antwort
priority: 500
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["*"]
signal_high_fit: ["ungeduldig", "effizient", "erfahren", "entscheidungsbereit"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: sachlich
default_length: kurz
default_detail: standard
response_type: answer
sources: ["mcp"]
format_primary: text
format_follow_up: none
tools: []
---

# PAT-01: Direkt-Antwort

## Kernregel
Max. 2 Sätze + CTA. Kein Smalltalk. skip_intro.

## Wann aktiv
- Nutzer:in zeigt klare Signale: ungeduldig, effizient, erfahren, entscheidungsbereit
- Universell einsetzbar (alle Personas, States, Intents)

## Verhalten
- Keine Einleitung, direkt zur Sache
- Kurze, prägnante Antwort
- Call-to-Action am Ende
