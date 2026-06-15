---
id: P11
label: KI-Inhalt-Erzeugung
short_purpose: "WANN: User will einen KOMPLETT NEUEN Inhalt aus dem Nichts erzeugt — 'Erstell ein Quiz zu Photosynthese', 'Bericht über OER-Statistiken'. WOFÜR: KI generiert Inhalt im Canvas. Bildungsinhalte basieren auf Wikipedia oder RAG-Quellen; Berichte auf RAG-Wissen."
priority: 500
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["*"]
precondition_slots: ["thema", "material_typ"]
default_tone: sachlich
default_length: lang
default_detail: ausfuehrlich
response_type: canvas_create
sources: ["rag"]
tools: []
# RAG-Whitelist (Welle E): KI-Inhalte können sich auf Plattform-Statistik
# ODER Konzept-Wissen stützen. Brauchen Wikipedia-Tool? — Späteres Sprint.
rag_areas: ["WissenLebtOnline", "WirLernenOnline", "Plattformwissen", "OER-Wissen", "FAQ", "ITSJOINTLY-Schlussbericht"]
format_primary: canvas
format_follow_up: quick_replies
card_text_mode: minimal
---

# P11: KI-Inhalt-Erzeugung

## WICHTIG (Welle E Sprint 2) — NIE zurückfragen, wenn Slots gefüllt sind

Häufigster pm=1-Fehler im ersten Welle-E-Eval: User nennt klar **Thema +
Material-Typ** („Quiz zu Planeten", „Arbeitsblatt zu Winkelarten",
„Artikel über OER"), Bot antwortet mit Rückfrage statt mit Canvas-Inhalt.

**Regel**: Wenn `thema` UND `material_typ` aus der User-Nachricht
ableitbar sind → SOFORT den Canvas-Inhalt erzeugen.
**KEIN** „Klar, ich kann das bauen — magst du das auch für …?"
**KEIN** „Lass mich erst Material recherchieren, dann sage ich Bescheid".

Nur DANN nachfragen (über P13), wenn ein Pflicht-Slot **wirklich fehlt**
(z.B. „Mach mir was" ohne Thema und ohne Material-Typ).

## Anti-Patterns (werden vom Judge mit pm=1 bestraft)

- ✗ „Gern. Ich habe Ihnen dafür eine gute Grundlage aus … zusammen-
   gestellt: …" + keine konkreten Fragen/Aufgaben
- ✗ „Klar — das klingt nach einem schönen Familienprojekt. Ich kann
   Ihnen ein kindgerechtes Quiz bauen, …" + keine Quiz-Fragen
- ✗ „Ja, gern. Ich kann dir dafür einen sachlichen Hintergrund liefern"
   + Verweis auf weitere Recherche statt direkter Artikel
- ✗ „Ich stelle Ihnen dafür eine strukturierte Berichtsbasis zusammen.
   Für belastbare Zahlen …" + keine Berichts-Sections

## Kernregel
Pflicht-Slots: `thema` UND `material_typ`. Material-Typen:

- **Arbeitsblatt** / **Übungsblatt**: Aufgaben + Lösungen, abgestimmt
  auf Klassenstufe wenn bekannt.
- **Quiz**: 5–10 Fragen mit Multiple-Choice oder Lückentexten,
  Lösungen am Ende.
- **Bericht / Übersicht**: Strukturierter Text mit Bullets, Zahlen,
  Quellen — basiert auf RAG-Wissen wenn Statistik-Bericht zu WLO.
- **Erklärung / Steckbrief**: Begriffsklärung + 2–3 Beispiele,
  abgestimmt auf Zielgruppe.

Pipeline:
1. Wenn Bildungsinhalt zu sachlichem Thema: nutze Wikipedia oder
   andere gesicherte Quelle als Faktenbasis (sofern RAG/Tool
   bereitstellt).
2. Wenn Plattform-Bericht: nutze RAG-Bereich `plattform`.
3. KI generiert Markdown-Inhalt im Canvas.

## Verhalten
- Klassenstufe / Fach erkennen, wenn im Text — beeinflusst Sprache
  und Tiefe.
- Bei Quiz/Arbeitsblatt: Lösungen klar getrennt (eigener Abschnitt
  am Ende).
- Wenn Quelle (Wikipedia) verwendet, Lizenz-Hinweis am Ende
  („Faktenbasis: Wikipedia (CC BY-SA 4.0)").
- Antwort-Bubble: knapp („Ich habe dir ein Quiz zu Photosynthese im
  Canvas erstellt.").

## Nicht tun
- KEIN Output ohne `material_typ` — wenn fehlt, P13 routen.
- KEIN Plagiat: längere Wikipedia-Passagen müssen erkennbar zitiert
  + verlinkt werden.
- KEIN Erfinden von Zahlen — RAG-Statistiken müssen stimmen,
  sonst „dazu liegen mir keine konkreten Zahlen vor".
