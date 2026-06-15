---
id: M07
label: Fachportale-Übersicht
short_purpose: Plural-Frage nach allen Fachportalen / Top-Level-Sammlungen → Liste der Fächer.
priority: 490
default_tone: kollegial
default_length: standard
response_type: cards
sources:
  - mcp
tools:
  - get_subject_portals
quick_replies_mode: speculative
core_rule: Top-Level-Fachportale als Cards rendern (max. 12). Kein Drilldown.
anti_patterns:
  - Keine Material-Treffer rendern (das ist M05/M06)
  - Bei Singular-Fach mit Drilldown-Verb → M08
when_to_use:
  - User fragt nach ALLEN Fächern (Plural) — „Welche Fächer gibt es?"
  - „Was bietet WLO insgesamt?" / „Liste aller Fachportale"
  - Übersichts-Frage ohne konkretes Fach
when_not_to_use:
  - Konkretes Singular-Fach + Drilldown-Verb („Welche Bereiche unter Mathematik?") → M08
  - Material-Suche zu konkretem Thema → M05/M06
  - Reine Wissensfrage über WLO → M04
trigger_phrases:
  - Welche Fächer gibt es
  - Liste der Fachportale
  - Was bietet WLO
  - Alle Fächer zeigen
  - Übersicht Fächer
discriminators:
  - vs: M08
    rule: PLURAL/Übersicht aller Fächer → M07. Singular-Fach mit Drilldown → M08.
    example: Welche Fächer gibt es? → M07. Welche Bereiche hat Mathematik? → M08.
  - vs: M04
    rule: Liste der Fachportale (kuratierter MCP-Output) → M07. Wissensfrage „Was sind Fachportale?" → M04.
    example: Liste Fachportale → M07. Was bedeutet Fachportal? → M04.
---

# M07 — Fachportale-Übersicht

## Wann aktiv
- „Welche Fächer gibt es?", „Was bietet WLO insgesamt?", „Liste der Fachportale"
- **Plural** / Übersichts-Frage ohne ein konkretes Fach

## Verhalten
- `get_subject_portals` aufrufen
- Cards alphabetisch
- Quick-Reply am Ende: „In ein Fach reinschauen?" → führt zu M08
