---
id: PAT-24
label: Download-Hinweis
priority: 545
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["INT-W-07"]
signal_high_fit: ["zielgerichtet", "erfahren"]
signal_medium_fit: ["unsicher"]
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: sachlich
default_length: kurz
default_detail: niedrig
response_type: answer
sources: ["llm"]
format_primary: text
format_follow_up: quick_replies
card_text_mode: highlight
tools: []
---

# PAT-24: Download-Hinweis

## Kernregel
Wenn Nutzer:innen ein konkretes Material herunterladen oder oeffnen
moechten, erklaert der Bot kurz, dass der Download ueber die Kachel
(Link zum Original-Content) laeuft, und gibt Orientierung zu Lizenz /
Oeffnen-im-neuen-Tab.

## Wann aktiv
- Intent INT-W-07 (Material herunterladen)
- Beispiele:
  - "Wie lade ich das Arbeitsblatt runter?"
  - "Kann ich den Inhalt speichern?"
  - "Wo ist der Download-Button?"
  - "Ist das als PDF verfuegbar?"

## Verhalten
- **Hinweis**: Materialien oeffnen sich ueber den Link auf der Kachel im
  Original-Portal (edu-sharing / Partner-Plattform). Dort steht der
  Download-/Oeffnen-Button.
- **Lizenz-Hinweis** (kurz): "Auf der Zielseite steht die Lizenz — CC,
  Public Domain oder proprietaer. Bitte beachten, wenn du das Material
  weiterverwendest."
- Falls im aktuellen Kontext eine Kachel-Liste schon sichtbar ist:
  verweise auf diese Kacheln.
- Falls noch keine Kachel da: biete direkt eine Suche nach dem Material
  (degradiere auf PAT-06 oder PAT-05).

## Quick-Replies (Standard)
- "Material suchen"
- "Was bedeutet CC BY?"
- "Kann ich das im Unterricht nutzen?"
- "Nein, danke"

## Hinweis
Aktiv wird ein technischer Download (Datei-Stream) im Widget nicht
unterstuetzt — das Pattern erklaert nur den Weg zum Inhalt.
