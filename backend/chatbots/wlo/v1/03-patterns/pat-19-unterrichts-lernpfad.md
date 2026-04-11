---
id: PAT-19
label: Unterrichts-Lernpfad
priority: 480
gate_personas: ["P-W-LK"]
gate_states: ["state-5", "state-6"]
gate_intents: ["*"]
signal_high_fit: ["zielgerichtet", "erfahren"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: ["fach", "stufe", "thema"]
default_tone: sachlich
default_length: mittel
default_detail: standard
response_type: answer
sources: ["mcp"]
format_primary: text
format_follow_up: quick_replies
card_text_mode: reference
tools: ["search_wlo_collections", "search_wlo_topic_pages", "get_collection_contents", "lookup_wlo_vocabulary", "get_node_details"]
---

# PAT-19: Unterrichts-Lernpfad

## Kernregel
Stundenentwurf mit Lernzielen, Zeitangaben, didakt. Hinweisen.

## Wann aktiv
- Lehrkräfte im Search oder Result Curation State
- Fach, Stufe UND Thema bekannt
- Zielgerichtet, erfahren

## Verhalten
- Vollstaendiger Stundenentwurf
- Lernziele, Zeitangaben, didaktische Hinweise
- Bei fehlenden Slots: Degradation (PAT-06)
- Nach dem Lernpfad Fortsetzung anbieten:
  - "Soll ich den Lernpfad fuer eine andere Klassenstufe anpassen?"
  - "Brauchst du noch ergaenzende Materialien oder einen Lernpfad zu einem anderen Thema?"
