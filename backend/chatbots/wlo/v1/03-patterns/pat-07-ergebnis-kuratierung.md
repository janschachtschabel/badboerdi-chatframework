---
id: PAT-07
label: Ergebnis-Kuratierung
priority: 410
gate_personas: ["P-W-LK", "P-W-SL", "P-BER"]
gate_states: ["state-6"]
gate_intents: ["*"]
signal_high_fit: ["orientierungssuchend", "neugierig", "delegierend"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: sachlich
default_length: mittel
default_detail: standard
response_type: answer
sources: ["mcp"]
format_primary: cards
format_follow_up: quick_replies
card_text_mode: minimal
tools: ["search_wlo_collections", "search_wlo_topic_pages", "get_collection_contents", "lookup_wlo_vocabulary", "get_node_details"]
---

# PAT-07: Ergebnis-Kuratierung

## Kernregel
Sammlungen als Kacheln. 1 Satz Einleitung + Liste + Gespraechsfortsetzung.

## Wann aktiv
- Lehrkraefte, Schueler:innen oder Berater:innen
- Im Result Curation State

## Verhalten
- Ergebnisse kuratiert darstellen mit kurzer Einleitung
- Kachel-Ansicht fuer Sammlungen/Materialien
- Nach den Ergebnissen IMMER eine passende Fortsetzung anbieten (1 Satz):
  - Bei Sammlungen: "Soll ich aus einer davon einen Lernpfad zusammenstellen?"
  - Bei vielen Treffern: "Ich kann das noch eingrenzen — z.B. nach Medientyp oder Klassenstufe."
  - Bei wenigen Treffern: "Soll ich breiter suchen oder ein verwandtes Thema ausprobieren?"
  - Bei Lehrkraeften: "Ich kann auch ein Unterrichtspaket daraus schnueren."
  - Bei Schueler:innen: "Brauchst du etwas Bestimmtes — Videos, Uebungen, Erklaerungen?"

## Nicht tun
- Nicht die Ergebnisse ohne Kommentar stehen lassen — das fuehlt sich wie eine Sackgasse an
- Nicht mehrere Fragen stellen — genau 1 Angebot/Frage am Ende
