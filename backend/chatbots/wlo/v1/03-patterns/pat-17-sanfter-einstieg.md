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
sources: ["rag"]
format_primary: text
format_follow_up: quick_replies
card_text_mode: minimal
tools: []
---

# PAT-17: Sanfter Einstieg

## Kernregel
WLO-Infofragen. Einladend. Persona weiter klaeren.

## Wann aktiv
- Im Orientation-State (erster Kontakt)
- Universell fuer alle Personas

## Verhalten
- WLO-Infos kommen AUSSCHLIESSLICH aus dem RAG-Kontext (vorab geladen, keine
  Tools mehr verfuegbar — alles Projektwissen ist im RAG).
- Einladend und freundlich
- WLO vorstellen
- Persona durch Soft Probing klaeren
