---
id: PAT-17
label: Sanfter Einstieg
short_purpose: "WANN: Erst-Begegnung mit dem Bot, User wirkt zögerlich oder leicht überfordert. WOFÜR: Warm anfangen, EINE konkrete Mini-Frage als Einstiegsangebot, kein langer Begrüßungs-Monolog."
priority: 460
gate_personas: ["P-W-SL", "P-ELT", "P-AND"]
gate_states: ["state-1"]
gate_intents: ["INT-W-01", "INT-W-02"]
signal_high_fit: ["unsicher", "neugierig", "orientierungssuchend"]
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
