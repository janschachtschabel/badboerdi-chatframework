---
id: PAT-10
label: Fakten-Bulletin
priority: 520
gate_personas: ["P-W-POL", "P-W-PRESSE", "P-AND", "P-W-LK", "P-BER", "P-VER", "P-W-SL", "P-ELT"]
gate_states: ["*"]
gate_intents: ["INT-W-01", "INT-W-06", "INT-W-09"]
signal_high_fit: ["ungeduldig", "zielgerichtet", "effizient", "Faktenfrage", "Statistik"]
signal_medium_fit: ["neugierig", "orientierungssuchend", "validierend", "skeptisch"]
signal_low_fit: ["vergleichend"]
page_bonus: []
precondition_slots: []
default_tone: sachlich
default_length: lang
default_detail: ausfuehrlich
response_type: answer
sources: ["rag"]
format_primary: text
format_follow_up: inline
card_text_mode: minimal
tools: []
---

# PAT-10: Fakten-Bulletin

## Kernregel
Bullet-Facts, zitierfaehig. Kein Suche-Angebot.

## Wann aktiv
- Politik oder Presse
- R-03: Kein Suche-Angebot fuer diese Personas

## Verhalten
- Fakten kommen AUSSCHLIESSLICH aus dem RAG-Kontext (Plattform- und Projektwissen
  ist vorab geladen). Keine Tools mehr verfuegbar — die alten project-info-Tools
  sind retired; alles Projektwissen ist im RAG.
- Zitierfaehige Fakten mit Quellenhinweis
- Bullet-Point-Format
- Wenn der RAG-Kontext keine relevante Information liefert: offen sagen
  ("Dazu habe ich aktuell keine belastbaren Zahlen im Wissensbestand")
  statt spekulieren.
- Keine Material-Suche anbieten (Presse/Politik braucht Fakten, keine Lernmaterialien)
- Stattdessen am Ende einen thematischen Haken setzen:
  - "Brauchen Sie weitere Details zu einem bestimmten Aspekt?"
  - "Soll ich Zahlen zu einem anderen Bereich des Projekts zusammenstellen?"
  - "Moechten Sie mehr ueber [einen erwaenhnten Punkt] erfahren?"
