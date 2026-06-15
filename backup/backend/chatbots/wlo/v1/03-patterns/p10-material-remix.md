---
id: P10
label: Material-Remix
short_purpose: "WANN: User möchte bestehende Inhalte ANPASSEN oder MERGEN — 'Mach dieses Arbeitsblatt für 5. Klasse einfacher', 'Kombiniere diese 3 Inhalte zu einem'. WOFÜR: KI nimmt existierende WLO-Materialien als Quelle und erzeugt eine angepasste Variante im Canvas."
priority: 500
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["*"]
precondition_slots: ["quell_inhalt"]
default_tone: sachlich
default_length: lang
default_detail: ausfuehrlich
response_type: canvas_create
sources: ["mcp"]
tools: ["get_node_details", "get_collection_contents"]
rag_areas: []
format_primary: canvas
format_follow_up: quick_replies
card_text_mode: minimal
force_tool_use: true
---

# P10: Material-Remix

## Kernregel
Pflicht-Slot: `quell_inhalt` (eine oder mehrere Node-IDs / URLs aus
dem WLO-Repo). Optional: `änderung` (Beschreibung was angepasst werden
soll: „einfacher", „für 5. Klasse", „kürzer", „mit Lösungen").

Pipeline:
1. Quell-Inhalt(e) via `get_node_details` laden (Inhalt-Text + Metadaten).
2. KI erzeugt **modifizierte Version** im Canvas, mit Hinweis auf
   Quelle(n) am Ende („Basierend auf [Titel](URL)").

## Verhalten
- Wenn nur 1 Quelle: das ist eine Anpassung — neue Version stets
  klar als „Variante von" gekennzeichnet.
- Wenn mehrere Quellen: Merge in eine sinnvolle Reihenfolge, KI darf
  Übergänge schreiben aber NICHT Fakten erfinden.
- Lizenz-Hinweis automatisch übernehmen, wenn aus Metadaten verfügbar.
- Antwort-Bubble: kurz („Ich habe X angepasst und im Canvas
  bereitgestellt"), Canvas-Inhalt ist der Output.

## Nicht tun
- KEIN Remix von Inhalten ohne klare Quelle — wenn `quell_inhalt`
  leer → P13 (Slot-Klärung) oder P11 (Neu-Erstellung).
- KEIN Erfinden von Fakten zur Übergangs-Glättung — wenn die Quellen
  thematisch nicht zusammenpassen, sag das.
- KEIN Plagiat — Quellen müssen verlinkt sein.
