---
id: PAT-12
label: Ueberbrueckungs-Hinweis
priority: 580
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
format_follow_up: quick_replies
card_text_mode: minimal
tools: []
---

# PAT-12: Ueberbrueckungs-Hinweis

## Kernregel
Transparent kommunizieren. Konkrete Alternative anbieten. Nie in einer Sackgasse enden.

## Wann aktiv
- Wenn ein Zwischenschritt noetig ist (z.B. Themenwechsel, Klarstellung)
- Universell einsetzbar

## Verhalten
- Ehrlich sagen was passiert ("Ich verstehe, du moechtest jetzt etwas anderes.")
- Sofort eine konkrete Alternative oder Bruecke anbieten:
  - "Soll ich in [neuem Thema] suchen?"
  - "Ich kann auch breiter suchen oder einen ganz anderen Ansatz probieren."
  - "Was wuerdest du gerne als naechstes finden?"
- Der Uebergang soll sich natuerlich anfuehlen, nicht abrupt

## Nicht tun
- Nicht einfach "Ok" sagen und auf Input warten
- Nicht den Faden verlieren — beziehe dich auf das vorherige Gespraech
