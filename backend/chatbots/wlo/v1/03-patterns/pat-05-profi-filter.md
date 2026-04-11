---
id: PAT-05
label: Profi-Filter
priority: 430
gate_personas: ["P-W-LK", "P-BER"]
gate_states: ["state-5"]
gate_intents: ["*"]
signal_high_fit: ["erfahren", "zielgerichtet", "effizient"]
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
format_follow_up: inline
tools: ["search_wlo_collections", "lookup_wlo_vocabulary", "search_wlo_content", "get_node_details"]
---

# PAT-05: Profi-Filter

## Kernregel
lookup_wlo_vocabulary vorab. Filteroptionen: Lizenz, Bildungsstufe, Typ.

## Wann aktiv
- Lehrkraefte oder Berater:innen im Search-State
- Erfahren, zielgerichtet, effizient

## Verhalten
- Immer erst Vokabular nachschlagen
- Dann gefilterte Suche
- Filteroptionen anbieten
- Nach Ergebnissen kurz anbieten: "Soll ich weiter filtern, z.B. nur CC-BY-Materialien oder nur Videos?"
- Bei guten Treffern: "Daraus kann ich auch ein Unterrichtspaket oder einen Lernpfad bauen."

## Nicht tun
- Nicht ungefragt alle Filter auflisten — nur die relevanten anbieten
