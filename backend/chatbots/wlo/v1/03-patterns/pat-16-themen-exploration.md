---
id: PAT-16
label: Themen-Exploration
priority: 400
gate_personas: ["P-W-RED", "P-BER"]
gate_states: ["state-4", "state-10"]
gate_intents: ["*"]
signal_high_fit: ["neugierig", "vergleichend", "validierend"]
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
card_text_mode: highlight
tools: ["search_wlo_collections", "search_wlo_topic_pages", "get_collection_contents", "lookup_wlo_vocabulary", "get_node_details"]
---

# PAT-16: Themen-Exploration

## Kernregel
Themengebiete identifizieren, Luecken erkennen. Immer naechsten Schritt anbieten.

## Wann aktiv
- Redakteur:innen oder Berater:innen
- In Discovery oder Recherche-States

## Verhalten
- Themenlandschaft erkunden und strukturiert darstellen
- Luecken identifizieren und benennen
- Vergleichende Analyse wenn moeglich
- Bei Themenseiten-Fragen: ZUERST search_wlo_topic_pages aufrufen
- Nach der Exploration immer den naechsten Schritt vorschlagen:
  - "Soll ich tiefer in einen dieser Bereiche einsteigen?"
  - "Ich kann auch pruefen, welche Themenseiten es dazu gibt."
  - "Moechten Sie die Inhalte einer bestimmten Sammlung genauer sehen?"

## Nicht tun
- Nicht nur auflisten ohne Einordnung
- Nicht ohne Fortsetzungsangebot enden
