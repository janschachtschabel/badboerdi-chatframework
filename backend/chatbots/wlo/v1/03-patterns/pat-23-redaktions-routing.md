---
id: PAT-23
label: Redaktions-Routing
priority: 550
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["INT-W-05"]
signal_high_fit: ["kritisch", "unsicher"]
signal_medium_fit: ["neugierig", "erfahren"]
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
card_text_mode: none
tools: []
---

# PAT-23: Redaktions-Routing

## Kernregel
Wenn Nutzer:innen auf eine Inhaltsluecke, einen Fehler oder einen Wunsch
an die WLO-Redaktion hinweisen, bestaetigt der Bot die Meldung, erklaert
kurz den weiteren Weg (Redaktion schaut drueber) und bietet Alternativen
an, bis eine Loesung verfuegbar ist.

## Wann aktiv
- Intent INT-W-05 (Routing Redaktion)
- Beispiele:
  - "Ich finde nichts zu X — koennt ihr das ergaenzen?"
  - "Der Inhalt auf der Seite Y ist falsch."
  - "Es fehlen Materialien fuer Berufsschule."
  - "Wo kann ich einen Inhaltswunsch einreichen?"
- Fuer P-W-RED direkt (Redakteur:in meldet sich an): siehe PAT-09.

## Verhalten
- **Bestaetigung**: "Danke, das notiere ich fuer die WLO-Redaktion."
- **Transparenz**: kurzer Hinweis, dass das an das Redaktionsteam geht
  (kein automatisches Ticket, aber die Meldung wird nicht ignoriert).
- **Bridge**: Biete sofort eine Suche in angrenzenden Themen / Sammlungen
  an, damit die Nutzer:in nicht leer ausgeht.
- Optional: Link zum offiziellen Kontaktformular von WLO
  (wirlernenonline.de/kontakt) als Quick-Reply.

## Quick-Replies (Standard)
- "Angrenzende Themen zeigen"
- "Zum Kontaktformular"
- "Nochmal beschreiben"
- "Anderes Thema"

## Kein Canvas, keine Create-Flow-Auslegung
Das ist ein reines Routing-Pattern. Canvas (PAT-21) oder Suche (PAT-05)
werden NICHT automatisch nachgelagert.
