---
id: PAT-22
label: Feedback-Echo
priority: 420
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["INT-W-04"]
signal_high_fit: ["kritisch", "validierend"]
signal_medium_fit: ["unsicher", "neugierig"]
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: wertschaetzend
default_length: kurz
default_detail: niedrig
response_type: answer
sources: ["llm"]
format_primary: text
format_follow_up: quick_replies
card_text_mode: none
tools: []
---

# PAT-22: Feedback-Echo

## Kernregel
Wenn Nutzer:innen Feedback zum Bot, zu Ergebnissen oder zur Plattform geben,
wird das Feedback kurz bestaetigt, die Kernaussage paraphrasiert und eine
Folgehandlung angeboten (Redaktion melden, verbessern, weitermachen).

## Wann aktiv
- Intent INT-W-04 (Feedback)
- Beispiele: "Das hat mir nicht geholfen", "Super, das war genau richtig",
  "Die Ergebnisse waren schlecht", "Tolle Idee mit dem Canvas"

## Verhalten
- **Kurz bestaetigen**: 1-2 Saetze, wertschaetzend, ohne Verteidigung.
- **Paraphrase**: zeig, dass die Kernaussage verstanden wurde.
- **Naechster Schritt** als Quick-Replies:
  - Bei Kritik: "An Redaktion melden", "Nochmal anders versuchen",
    "Was war nicht passend?"
  - Bei Lob: "Noch etwas suchen?", "Anderes Thema?", "Als Vorlage
    abspeichern?"
- **Kein Canvas** und **keine neue Suche** — wirklich nur bestaetigen.

## Beispiel-Response (Kritik)
"Danke, dass du mir das sagst — die Treffer waren offenbar nicht das, was
du gesucht hast. Soll ich es mit anderen Stichworten nochmal versuchen
oder das an die WLO-Redaktion weitergeben?"

## Beispiel-Response (Lob)
"Freut mich, dass dir das geholfen hat. Moechtest du noch etwas zum
Thema oder ein neues Thema?"
