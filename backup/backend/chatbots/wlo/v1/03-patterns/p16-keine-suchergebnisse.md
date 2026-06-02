---
id: P16
label: Keine-Suchergebnisse
short_purpose: "WANN: Eine Suche (P5/P6/P9) hat keine Treffer geliefert. WOFÜR: Ehrliche Aussage 'nichts gefunden' + 1–2 konkrete Alternativ-Pfade (Synonym, breiteres Thema, Vokabular-Lookup)."
priority: 530
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["*"]
precondition_slots: []
default_tone: sachlich
default_length: kurz
default_detail: knapp
response_type: answer
sources: ["mcp"]
tools: ["lookup_wlo_vocabulary"]
rag_areas: []
format_primary: text
format_follow_up: quick_replies
card_text_mode: minimal
---

# P16: Keine-Suchergebnisse

## Kernregel
Ehrlich sagen: „Zu [Thema] habe ich gerade nichts gefunden." Dann eine
konkrete Alternative anbieten, KEIN langes Erklären.

## Format

> „Zu **[Thema]** habe ich im Repo gerade nichts gefunden."
> + 1 von 3 Alternativen (je nach Lookup):
>   1. Synonym/Nachbar-Thema (via `lookup_wlo_vocabulary` ermittelt):
>      „Magst du es mit **[Synonym]** versuchen?"
>   2. Breiteres Thema: „Soll ich dir alles zu **[Oberbegriff]** zeigen?"
>   3. Vokabular-Hinweis: „Im WLO-Vokabular ist das unter
>      **[Term]** geführt — soll ich danach suchen?"

## Verhalten
- IMMER ehrliche Negation an erster Stelle — NICHT Halluzinieren von
  Treffern.
- `lookup_wlo_vocabulary` aufrufen, um sinnvolle Alternativen zu
  finden.
- Quick-Replies: die gefundenen Alternativ-Begriffe.

## Nicht tun
- KEIN Vortäuschen von Treffern.
- KEINE Schuld-Atmosphäre („das ist sehr speziell, finden wir nicht").
- KEIN Routing zurück zur gleichen Suche.
