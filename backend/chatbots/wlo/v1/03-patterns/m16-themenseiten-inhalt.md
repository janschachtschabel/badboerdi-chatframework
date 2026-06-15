---
id: M16
label: Themenseiten-Inhalt
short_purpose: Inhalte EINER konkreten Themenseite nach Schwimmlinien zeigen (Auszug) + Absprung.
priority: 486
default_tone: kollegial
default_length: kurz
response_type: cards
sources:
  - mcp
tools:
  - search_wlo_topic_pages
  - get_topic_page_content
core_rule: Inhalte EINER bestimmten Themenseite, nach Schwimmlinien gruppiert (max. 3 je Box, „(Auszug)") + Absprung-Button auf die Themenseite. KEINE normalen Sammlungs-/Inhalts-Boxen.
anti_patterns:
  - Liste von Themenseiten zu einem Thema → M06
  - Allgemeine Materialsuche zu einem Thema → M05/M06
  - Wissensfrage über das Thema → M04
when_to_use:
  - User will sehen, was AUF einer KONKRETEN Themenseite ist / deren Inhalte
  - 'Öffnen/Anzeigen-Verb + Themenseite: „zeig mir die Inhalte der Themenseite X", „was ist auf der Themenseite X", „öffne die Themenseite X"'
  - User klickt „Inhalte dieser Themenseite zeigen" an einem Themenseiten-Treffer
when_not_to_use:
  - User sucht Themenseiten ZU einem Thema (Liste/Auswahl) → M06
  - Konkreter Material-/Treffer-Wunsch zu einem Thema → M05/M06
  - Sub-Themen/Aufbau einer normalen Sammlung navigieren → M08
trigger_phrases:
  - Inhalte der Themenseite X
  - Was ist auf der Themenseite X
  - Zeig mir die Themenseite X
  - Öffne die Themenseite X
  - Was steht auf der Themenseite X
discriminators:
  - vs: M06
    rule: Inhalte EINER bestimmten Themenseite anzeigen → M16. Themenseiten zu einem Thema SUCHEN (Liste) → M06.
    example: Was ist auf der Themenseite Nachhaltigkeit? → M16. Gibt es Themenseiten zu Nachhaltigkeit? → M06.
  - vs: M08
    rule: Schwimmlinien-Inhalte einer Themenseite → M16. Sub-Sammlungen/Aufbau einer normalen Sammlung → M08.
    example: Inhalte der Themenseite Klimawandel → M16. Wie ist die Mathematik-Sammlung gegliedert? → M08.
---

# M16 — Themenseiten-Inhalt

## Wann aktiv
- „Zeig mir die Inhalte der Themenseite X", „Was ist auf der Themenseite X?", „Öffne Themenseite X"
- Folge-Klick „Inhalte dieser Themenseite zeigen" an einem Themenseiten-Treffer (M06)

## Pipeline (deterministisch im Backend)
1. `search_wlo_topic_pages(thema)` → beste Themenseite (Cross-Encoder-Gate; greift keine → freundlicher Hinweis + Such-Angebot)
2. `get_topic_page_content(collectionId)` → Schwimmlinien mit echten Inhalts-Karten
3. Anzeige: je Schwimmlinie eine Box „<Überschrift> (Auszug)" (max. 3 Karten) + Absprung-Button auf die Themenseite

## Verhalten
- **Antwort-Text kurz** (1–2 Sätze): nennt die Themenseite + dass es ein Auszug ist; die Boxen tragen den Inhalt.
- **KEINE** normalen Sammlungs-/Inhalts-/Themenseiten-Boxen — nur die Schwimmlinien-Boxen + Absprung.
- Wahrheitspflicht: nur über die tatsächlich gezeigten Schwimmlinien/Karten sprechen.
