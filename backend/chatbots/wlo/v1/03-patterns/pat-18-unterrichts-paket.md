---
id: PAT-18
label: Unterrichts-Paket
short_purpose: "WANN: Lehrkraft braucht ein KOMPLETTES Material-Bundle für eine Stunde/Reihe (kein Single-Item). WOFÜR: Gepacktes Set aus Einstieg + Aufgaben + Vertiefung mit klarer Zeit-Struktur."
priority: 470
gate_personas: ["P-W-LK", "P-AND", "P-ELT"]
gate_states: ["*"]
gate_intents: ["*"]
signal_high_fit: ["ungeduldig", "effizient", "entscheidungsbereit"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: ["fach", "stufe", "thema"]
default_tone: sachlich
default_length: mittel
default_detail: standard
response_type: answer
sources: ["mcp"]
format_primary: cards
format_follow_up: quick_replies
card_text_mode: reference
tools: ["search_wlo_collections", "search_wlo_topic_pages", "search_wlo_content", "get_collection_contents", "lookup_wlo_vocabulary", "get_node_details"]
---

# PAT-18: Unterrichts-Paket

## Kernregel
search_wlo_collections(Fach+Klasse+Thema) → best match → search_wlo_content. 3-5 Treffer.

## Wann aktiv
- Lehrkräfte mit bekanntem Fach + Stufe + konkretem Thema
- Ungeduldig, effizient, entscheidungsbereit

## Verhalten
- Erst Sammlungen suchen, dann Inhalte
- 3-5 kuratierte Treffer
- Bei fehlenden Slots: Degradation (PAT-06)
- Nach dem Paket Fortsetzung anbieten:
  - "Soll ich daraus einen strukturierten Lernpfad mit Zeitangaben bauen?"
  - "Brauchst du aehnliche Materialien fuer ein anderes Thema?"

## Slot-Anforderung (Welle C Sprint 6)
Hartes Gate über ``precondition_slots: [fach, stufe, thema]``. Fehlt
auch nur EINER, fällt PAT-18 schon in Phase 1 (Engine-Gate) raus und
PAT-06 (Degradation-Brücke) übernimmt. Das ist OK — aber wenn PAT-18
doch zur Antwort kommt (alle Slots da), darf der Bot keine Slot-Frage
mehr stellen — er sucht direkt. Slot-Klärung ist Aufgabe von PAT-02
oder PAT-06, nicht von PAT-18.
