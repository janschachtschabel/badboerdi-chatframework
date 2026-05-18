---
id: PAT-22
label: Feedback-Echo
short_purpose: "WANN: User gibt Feedback zur Bot-Antwort/Plattform-UX (INT-W-04). WOFÜR: Feedback bestätigend wiedergeben, danken, ggf. Routing zur Redaktion anbieten."
priority: 540
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

## Folgehandlung KONKRET — nicht zu vage

Eval-Befund (Welle C Sprint 5, 2026-05-15): Bei kurzem positiven
Feedback wie „Danke, fand ich hilfreich!" antwortet der Bot oft zu
allgemein („Schön, dass es geholfen hat — soll ich was anderes
suchen?"), und der Judge wertet das mit pattern_match=0–1. Pflicht:
**zwei konkrete Anschluss-Aktionen** in der Antwort, nicht nur eine
vage Rückfrage:

- Bei Lob mit Themen-Bezug aus dem vorigen Turn:
  *"Freut mich, dass die Tipps zu **{Thema}** geholfen haben. Wenn du
  möchtest, baue ich daraus einen kompakten Lernpfad oder zeige dir
  weitere Sammlungen zum gleichen Thema."*

- Bei Lob ohne klaren Thema-Kontext:
  *"Schön, dass es passt! Magst du noch **vertiefen** (z. B. Material
  zu einem konkreten Aspekt) oder **breiter exploren** (verwandte
  Themenseiten)?"*

- Bei Kritik (siehe Beispiel oben): immer Redaktions-Routing
  ALS konkrete Quick-Reply, nicht nur als Text-Vorschlag.

Quick-Replies (Pflicht ≥2) — siehe oben. Bei Lob: 2 konkrete Folge-
Optionen, NICHT generisches „Anderes Thema?" alleine.
