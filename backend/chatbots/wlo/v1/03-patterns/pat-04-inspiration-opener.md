---
id: PAT-04
label: Inspiration-Opener
short_purpose: "WANN: Erst-Begegnung mit der Plattform, User fragt offen 'Was kann ich hier?' WOFÜR: Inspirations-Beispiele aus 2-3 Bereichen zeigen, statt Plattform-Theorie zu erklären."
priority: 450
gate_personas: ["P-W-LK", "P-W-SL", "P-ELT", "P-AND"]
gate_states: ["state-1", "state-4"]
gate_intents: ["INT-W-01", "INT-W-02"]
signal_high_fit: ["neugierig", "orientierungssuchend", "delegierend"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
# Welle C Eval-Fix (2026-05-15): precondition_slots: ["thema"] schärft
# die Abgrenzung zu PAT-20. PAT-04 zeigt 2-3 inspirierende Kacheln und
# braucht dafür einen Themen-Anker (User nennt Mathe/Klimawandel/...).
# Ohne Thema gewinnt PAT-20 sauber, das ist die richtige "Was kann ich
# hier"-Antwort ohne Material-Bombardement. Im Eval-Run 2026-05-15 hat
# PAT-04 vs PAT-20 3× knapp kollidiert (gap 0.0070) — diese Race ist
# durch den precondition-Slot deterministisch aufgelöst.
precondition_slots: ["thema"]
default_tone: spielerisch
default_length: mittel
default_detail: standard
response_type: answer
sources: ["mcp"]
format_primary: cards
format_follow_up: quick_replies
card_text_mode: highlight
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
- Nicht "Was moechtest du als naechstes?" — zu generisch
- NICHT aktivieren, wenn kein konkretes Thema erkennbar ist. Fuer "ich
  bin Schuelerin, such mir was" / "zeig mir irgendwas" greift stattdessen
  PAT-20 (Orientierungs-Guide), damit der:die Nutzer:in erst ein Thema
  oder Fach nennt. Zufaellige Top-Treffer ohne Themenkontext wirken
  willkuerlich.
