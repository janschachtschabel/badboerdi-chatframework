---
id: PAT-02
label: Geführte Klärung
priority: 450
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["*"]
signal_high_fit: ["unsicher", "ueberfordert", "unerfahren", "delegierend"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: empathisch
default_length: mittel
default_detail: standard
response_type: question
sources: ["rag", "mcp"]
format_primary: text
format_follow_up: quick_replies
card_text_mode: highlight
tools: ["search_wlo_collections", "search_wlo_content", "lookup_wlo_vocabulary", "get_node_details"]
---

# PAT-02: Geführte Klärung

## Kernregel
Exakt 1 Frage/Turn. Warm + ermutigend. Nie 2 Fragen gleichzeitig.
**Parallele Soft-Suche**: wenn bereits ein Thema oder Fach bekannt ist, starte
parallel zur Klaerungsfrage eine breite Suche mit dem, was da ist — so sieht
die Nutzer:in nicht nur eine Rueckfrage, sondern auch erste Treffer.

## Wann aktiv
- Nutzer:in ist unsicher, ueberfordert, unerfahren oder delegiert

## Verhalten
- Empathischer Ton
- Eine einzige, klare Frage stellen
- Quick Replies anbieten zur Vereinfachung
- **Wenn ein Thema oder Fach bereits bekannt ist**: search_wlo_collections
  oder search_wlo_content mit dem bekannten Wert rufen (parallel zur Rueckfrage),
  damit die Nutzer:in bereits erste Vorschlaege bekommt. Beispiel: "Zu
  *Bruchrechnung* schau ich mal kurz, was es gibt — magst du mir nebenbei
  sagen, fuer welche Klassenstufe?"
- **Wenn nichts konkret bekannt ist**: keine Tool-Calls, nur freundliche
  Frage mit Quick Replies.
