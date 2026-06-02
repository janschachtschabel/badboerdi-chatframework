---
id: P9
label: Lernpfad-Erstellung
short_purpose: "WANN: User will einen sequenziellen Lernpfad/Unterrichtsentwurf zu einem konkreten Thema, basierend auf existierenden WLO-Inhalten. Beispiel: 'Erstell mir einen Lernpfad zu Bruchrechnen für die 5. Klasse'. WOFÜR: KI wählt aus Sammlungen die besten Inhalte für die Zielgruppe und baut narrativen Pfad im Canvas."
priority: 500
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["*"]
precondition_slots: ["thema"]
default_tone: sachlich
default_length: lang
default_detail: ausfuehrlich
response_type: canvas_create
sources: ["mcp"]
tools: ["search_wlo_collections", "get_collection_contents", "search_wlo_content", "get_node_details", "lookup_wlo_vocabulary"]
rag_areas: []
format_primary: canvas
format_follow_up: quick_replies
card_text_mode: reference
force_tool_use: true
requires_all_tools: false
card_text_link_required: true
---

# P9: Lernpfad-Erstellung

## Kernregel
Pflicht-Slot: `thema`. Optional: `klassenstufe`, `fach`, `material_typ`.
Pipeline:

1. Sammlung(en) zum Thema laden (`search_wlo_collections` →
   `get_collection_contents`).
2. KI wählt die für die Zielgruppe besten 4–7 Inhalte aus.
3. Baue im Canvas einen narrativen Pfad mit Phasen
   (Einstieg → Erarbeitung → Vertiefung → Anwendung → Sicherung),
   jede Phase verlinkt ein konkretes Material aus den Sammlungen.

Antwort-Bubble: kurze Einleitung („Ich habe dir den Lernpfad zu X
im Canvas aufgebaut."), Canvas-Inhalt ist der eigentliche Output.

## Verhalten
- Jede Phase MUSS mindestens einen Material-Link aus den
  aufgerufenen Sammlungen enthalten ([Titel](URL)).
- Wenn die Zielgruppe (Klassenstufe/Fach) klar ist, schließe
  unpassende Materialien aus.
- Wenn keine Sammlung zum Thema gefunden → fallback auf
  `search_wlo_content` mit Thema-Filter; wenn auch das null Treffer
  → P16 (Keine-Suchergebnisse).

## Nicht tun
- KEINE generischen „Du kannst …"-Listen ohne konkrete Material-Links.
- KEINE Inhalte „frei aus der KI" — alle Material-Verweise müssen aus
  dem Such-Output stammen.
- KEINE Empfehlung von Sammlungen direkt — User will den Pfad, nicht
  die Sammlungs-Liste (das ist P8).
