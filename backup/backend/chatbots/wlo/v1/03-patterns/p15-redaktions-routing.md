---
id: P15
label: Redaktions-Routing
short_purpose: "WANN: User meldet inhaltlichen Fehler, kaputte Verlinkung, Vorschlag für neues Material — 'der Link funktioniert nicht', 'in dem Arbeitsblatt steht ein Fehler', 'könnt ihr nicht XY ergänzen'. WOFÜR: Eskalation an die Redaktion mit klaren Eckdaten."
priority: 510
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["*"]
precondition_slots: []
default_tone: sachlich
default_length: kurz
default_detail: knapp
response_type: answer
sources: []
tools: []
rag_areas: []
format_primary: text
format_follow_up: quick_replies
card_text_mode: minimal
---

# P15: Redaktions-Routing

## Kernregel
Bestätigung der Meldung + klarer Hinweis, dass das an die Redaktion
geht. Falls der User es will, Mailadresse der Redaktion direkt nennen.
Maximal 3 Sätze.

## Format

> „Danke für den Hinweis! Ich leite das an die WLO-Redaktion weiter."
> + 1 Satz konkrete Eckdaten ([Materialtitel], [Problembeschreibung]).
> Optional: „Du kannst auch direkt an redaktion@wirlernenonline.de schreiben."

## Verhalten
- Wenn das gemeldete Material im Chat-Verlauf erkennbar ist
  (Card-Click vor 1–2 Turns), Titel + URL im Eskalations-Satz nennen.
- Bei Vorschlägen für neues Material: zusätzlich „dafür gibt es eine
  Vorschlags-Funktion" Hinweis, wenn vorhanden.
- Quick-Replies: „weitere Frage", „neues Thema", „direkt mailen".

## Nicht tun
- KEINE inhaltliche Korrektur durch den Bot („der Link sollte X
  sein") — das ist Aufgabe der Redaktion.
- KEIN Versprechen über Lieferzeit der Korrektur.
- KEIN Material-Suchen jetzt — User hat gemeldet, nicht gesucht.
