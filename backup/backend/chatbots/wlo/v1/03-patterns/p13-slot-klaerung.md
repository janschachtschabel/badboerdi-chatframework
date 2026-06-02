---
id: P13
label: Slot-Klärung
short_purpose: "WANN: System hat erkannt, dass für den eigentlich gewollten Pattern ein Pflicht-Slot fehlt (z.B. `thema` bei Material-Suche, `material_typ` bei KI-Inhalt-Erzeugung). WOFÜR: Genau EINE klare Frage stellen mit konkreten Quick-Reply-Optionen — nicht mehr."
priority: 530
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["*"]
precondition_slots: []
default_tone: sachlich
default_length: kurz
default_detail: knapp
response_type: clarify
sources: []
tools: []
rag_areas: []
format_primary: text
format_follow_up: quick_replies
card_text_mode: minimal
---

# P13: Slot-Klärung

## Kernregel
Eine kurze Frage mit drei konkreten Quick-Reply-Optionen plus eine
„weiß-nicht / sonstige"-Option. Maximal 2 Sätze einleitend.

## Format
> „Damit ich dir helfen kann, brauche ich noch [Slot-Name].
> Zu welchem Thema/welche Klasse/welche Materialart?"

Quick-Replies (Beispiele je nach fehlendem Slot):

- `thema` fehlt: „Mathematik", „Deutsch", „Biologie", „etwas anderes"
- `material_typ` fehlt: „Arbeitsblatt", „Quiz", „Video", „lass mich
  wählen"
- `klassenstufe` fehlt: „Grundschule", „Sek I", „Sek II", „flexibel"

## Verhalten
- KURZ und SPEZIFISCH — kein Smalltalk vor der Klärung.
- Wenn der User auf eine Quick-Reply klickt, wird der Slot gefüllt und
  System routet zu dem ursprünglich gewollten Pattern.
- Wenn der User stattdessen frei antwortet, übergibt der Classifier
  den neuen Text — Routing geht von vorne.

## Nicht tun
- KEINE Mehrfach-Fragen in einem Turn („zu welchem Thema, welche
  Klasse, welches Material?") — eine Frage, ein Slot.
- KEINE generischen „kannst du mir mehr sagen?" — konkret fragen.
- KEINE Antwort mit Materialien jetzt — erst nach Klärung.
