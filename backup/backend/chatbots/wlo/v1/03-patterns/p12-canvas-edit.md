---
id: P12
label: Canvas-Edit
short_purpose: "WANN: Canvas ist offen, User fordert konkrete Änderung — 'mach es einfacher', 'füge Lösungen hinzu', 'kürzer bitte'. WOFÜR: KI passt den bestehenden Canvas-Inhalt entsprechend an, ohne ihn neu zu erstellen."
priority: 510
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["*"]
precondition_slots: []
default_tone: sachlich
default_length: mittel
default_detail: standard
response_type: canvas_update
sources: []
tools: []
rag_areas: []
format_primary: canvas
format_follow_up: quick_replies
card_text_mode: minimal
---

# P12: Canvas-Edit

## Kernregel
Voraussetzung: Canvas ist offen (`canvas_state` mit nicht-leerem
`markdown`). User-Anweisung beschreibt, was anzupassen ist.

Pipeline:
1. Bestehenden Canvas-Inhalt + User-Edit-Anweisung an KI geben.
2. KI generiert die aktualisierte Markdown-Version.
3. Canvas wird per `canvas_update`-PageAction ersetzt.

Antwort-Bubble: 1 Satz Bestätigung („Ich habe das Arbeitsblatt
einfacher formuliert — schau ins Canvas.").

## Verhalten
- Edit-Aufträge interpretieren konkret:
  - „einfacher" → Vokabular vereinfachen, kürzere Sätze
  - „mit Lösungen" → eigenen Lösungsabschnitt anfügen
  - „kürzer" → 30–50% kürzen, Inhalt-Kern erhalten
  - „für 7. Klasse" → Schwierigkeit anpassen
- Bei mehrdeutiger Anweisung: 1 Rückfrage über Quick-Reply, dann edit.

## Nicht tun
- KEIN kompletter Neu-Build vom Inhalt — das ist P11.
- KEIN Hinzufügen unverwandter Themen.
- KEIN Verwerfen des bisherigen Canvas-Texts ohne Anlass.
