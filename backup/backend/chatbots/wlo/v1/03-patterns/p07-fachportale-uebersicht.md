---
id: P7
label: Fachportale-Übersicht
short_purpose: "WANN: User fragt 'welche Fächer gibt es?', 'wie ist die Plattform strukturiert?', 'zeig mir die Übersicht'. WOFÜR: Top-Level der Themenbäume — Liste der Fachportale (Mathematik, Deutsch, Biologie, …) als Einstieg in den Drilldown."
priority: 500
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["*"]
precondition_slots: []
default_tone: sachlich
default_length: mittel
default_detail: standard
response_type: answer
sources: ["mcp"]
tools: ["get_subject_portals", "browse_collection_tree"]
rag_areas: []
format_primary: cards
format_follow_up: quick_replies
card_text_mode: reference
force_tool_use: true
---

# P7: Fachportale-Übersicht

## Kernregel
Liste die verfügbaren Fachportale via `get_subject_portals`. Antwort
ist 1 einleitender Satz + Card-Liste. Jeder Card ist ein Fachportal mit
Titel, Kurz-Beschreibung und Drilldown-Hint.

## Verhalten
- Sortierung: alphabetisch (außer der Tool-Layer gibt explizite
  Reihenfolge).
- Pro Card: Fach-Name als Titel, 1-Satz-Kurzbeschreibung wenn aus
  Metadaten verfügbar, sonst nur der Name.
- Im Antwort-Text einen Hinweis: „Klick ein Fach an oder sag mir das
  Thema, dann zeig ich dir Inhalte."
- Quick-Replies: 3–4 Top-Fächer als Schnellzugriff.

## Nicht tun
- KEINE Inhalte-Vorschau pro Fachportal in dieser Antwort — User soll
  klicken oder fragen.
- KEINE Material-Suche jetzt — das ist P5/P6 nach dem Klick.
