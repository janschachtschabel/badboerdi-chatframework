---
id: P5
label: Material-Suche spezifisch
short_purpose: "WANN: User hat ein konkretes Thema und ggf. Filter (Medientyp, Klassenstufe, Fach). Beispiel: 'Videos zu Bruchrechnung 5. Klasse', 'Arbeitsblatt Photosynthese Sek I'. WOFÜR: Direkte Suche im WLO-Repo, Output als Card-Liste mit Filter-Anwendung."
priority: 500
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["*"]
precondition_slots: ["thema"]
default_tone: sachlich
default_length: mittel
default_detail: standard
response_type: answer
sources: ["mcp"]
tools: ["search_wlo_content", "lookup_wlo_vocabulary", "get_node_details"]
rag_areas: []
format_primary: cards
format_follow_up: quick_replies
card_text_mode: reference
force_tool_use: true
---

# P5: Material-Suche spezifisch

## Kernregel
User-Anfrage hat `thema` und optionale Filter. Suche im WLO-Repo via
`search_wlo_content` mit allen verfügbaren Filtern (Medientyp,
Klassenstufe, Fach). Wenn ein Filter im User-Text steht („nur Videos",
„für 5. Klasse"), **muss** dieser an `search_wlo_content` weitergegeben
werden — nicht nur in Prosa erwähnen.

## Verhalten
- Slot `thema` ist Pflicht. Wenn fehlend → System routet zu P13
  (Slot-Klärung), nicht hier antworten.
- Filter-Erkennung (in dieser Reihenfolge):
  1. Medientyp: „Video", „Audio", „Arbeitsblatt", „Quiz", „Bild",
     „interaktiv"
  2. Klassenstufe: „5. Klasse", „Sek I", „Sek II", „Klasse 5–7"
  3. Fach: „Mathematik", „Biologie", „Deutsch" etc.
- Anzeige als Card-Liste; max_items aus device_config.
- Wenn Suche **null Treffer** liefert → System routet zu P16
  (Keine-Suchergebnisse).

## Nicht tun
- KEINE Sammlungs-Cards mischen (das ist P6).
- KEINE Lernpfad-Erstellung (das ist P9).
- KEINEN Material-Filter ignorieren — wenn User „nur Videos" sagt,
  müssen es nur Videos sein.
