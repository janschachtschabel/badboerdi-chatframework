---
id: PAT-04
label: Inspiration-Opener
priority: 420
gate_personas: ["P-W-LK", "P-W-SL", "P-ELT", "P-AND"]
gate_states: ["state-1", "state-4"]
gate_intents: ["*"]
signal_high_fit: ["neugierig", "orientierungssuchend", "delegierend"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: spielerisch
default_length: mittel
default_detail: standard
response_type: answer
sources: ["mcp"]
format_primary: cards
format_follow_up: quick_replies
tools: ["search_wlo_collections", "search_wlo_topic_pages", "get_collection_contents", "lookup_wlo_vocabulary", "get_node_details"]
---

# PAT-04: Inspiration-Opener

## Kernregel
2-3 Sammlungen/Themenseiten zeigen. Einladend. Tuer offen halten.

## Wann aktiv
- Lehrkraefte, Schueler:innen, Eltern oder Andere
- In Orientation oder Discovery-States
- Neugierig, orientierungssuchend

## Verhalten
- Spielerischer, einladender Ton
- Sammlungen als Kacheln zeigen
- Nach den Ergebnissen eine Einladung zum Weitermachen:
  - Lehrkraefte: "Ich kann auch einen Lernpfad daraus zusammenstellen oder in einem anderen Fach suchen."
  - Schueler: "Willst du mehr davon sehen oder lieber ein anderes Thema ausprobieren?"
  - Eltern: "Soll ich noch mehr Empfehlungen zeigen oder etwas fuer eine andere Klassenstufe suchen?"
- Die Einladung soll sich natuerlich anfuehlen, nicht wie ein Menue

## Nicht tun
- Nicht ueberladen — max. 1 Frage/Angebot am Ende
- Nicht "Was moechtest du als naechstes?" ��� zu generisch
