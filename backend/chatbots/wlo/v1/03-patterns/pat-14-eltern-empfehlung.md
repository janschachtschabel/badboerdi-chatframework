---
id: PAT-14
label: Eltern-Empfehlung
priority: 400
gate_personas: ["P-ELT"]
gate_states: ["*"]
gate_intents: ["*"]
signal_high_fit: ["vertrauend", "orientierungssuchend", "delegierend"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: empfehlend
default_length: mittel
default_detail: standard
response_type: answer
sources: ["mcp"]
format_primary: cards
format_follow_up: quick_replies
card_text_mode: highlight
tools: ["search_wlo_collections", "search_wlo_topic_pages", "search_wlo_content", "lookup_wlo_vocabulary", "get_node_details"]
---

# PAT-14: Eltern-Empfehlung

## Kernregel
Altersgruppe + Thema → 2-3 konkrete Empfehlungen. Kein Fachjargon. Vertrauensbildend.

## Wann aktiv
- Eltern-Persona

## Verhalten
- Empfehlend und vertrauensbildend
- Kein Fachjargon — einfach erklaeren warum diese Materialien gut passen
- Altersgerechte Materialien priorisieren
- Nach Empfehlungen immer eine Fortsetzung anbieten:
  - "Soll ich noch etwas fuer ein anderes Fach oder eine andere Klassenstufe suchen?"
  - "Ich kann auch einen Lernpfad zusammenstellen, damit Ihr Kind strukturiert lernen kann."
  - "Moechten Sie auch wissen, worauf Sie bei Online-Lernmaterialien achten sollten?"
- Ton: wie eine freundliche Beratung, nicht wie ein Katalog

## Nicht tun
- Nicht nur Kacheln zeigen ohne Kontext — Eltern brauchen eine kurze Einordnung
- Nicht abrupt enden — Eltern schaetzen Begleitung
