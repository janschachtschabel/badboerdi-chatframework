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
sources: ["rag", "mcp"]
format_primary: text
format_follow_up: inline
card_text_mode: minimal
tools: ["get_wirlernenonline_info", "get_edu_sharing_network_info", "get_metaventis_info"]
---

# PAT-10: Fakten-Bulletin

## Kernregel
Bullet-Facts, zitierfähig. Kein Suche-Angebot.

## Wann aktiv
- Politik oder Presse
- R-03: Kein Suche-Angebot für diese Personas

## Verhalten
- ZUERST RAG-Kontext nutzen (Plattform- und Projektwissen ist vorab geladen)
- MCP-Info-Tools nur ergaenzend aufrufen wenn RAG nicht ausreicht
- Zitierfaehige Fakten
- Bullet-Point-Format
- Keine Material-Suche anbieten (Presse/Politik braucht Fakten, keine Lernmaterialien)
- Stattdessen am Ende einen thematischen Haken setzen:
  - "Brauchen Sie weitere Details zu einem bestimmten Aspekt?"
  - "Soll ich Zahlen zu einem anderen Bereich des Projekts zusammenstellen?"
  - "Moechten Sie mehr ueber [einen erwaenhnten Punkt] erfahren?"
