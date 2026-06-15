---
id: M08
label: Sammlung-Drilldown
short_purpose: Singular-Fach oder konkrete Sammlung → Sub-Themen und Inhalte der Ebene.
priority: 490
default_tone: kollegial
default_length: standard
response_type: cards
sources:
  - mcp
tools:
  - get_subject_portals
  - browse_collection_tree
  - get_collection_contents
core_rule: 'Navigation EINE Ebene tiefer: Sub-Sammlungen + ggf. enthaltene Inhalte.'
anti_patterns:
  - Bei Plural-Frage → M07
  - Bei konkretem Material-Wunsch in der Sammlung → M05/M06
when_to_use:
  - User fragt nach Sub-Themen/Bereichen eines KONKRETEN Fachs (Singular)
  - Drilldown-Verb — Bereiche unter X / gegliedert in / Unterthemen von / was ist in dieser Sammlung?
  - User klickt auf ein Fachportal-Kachel und möchte tiefer navigieren
when_not_to_use:
  - Plural-Frage nach ALLEN Fachportalen → M07
  - Konkretes Material-/Treffer-Wunsch zu Thema in der Sammlung → M05/M06
  - Wissensfrage über das Fach → M04
trigger_phrases:
  - Welche Bereiche unter X
  - Was ist in der Sammlung X
  - Unterthemen von X
  - X gegliedert
  - Wie ist X aufgebaut
discriminators:
  - vs: M07
    rule: Singular-Fach mit Drilldown → M08. Plural-Übersicht aller Fächer → M07.
    example: Bereiche unter Mathematik → M08. Alle Fächer → M07.
  - vs: M06
    rule: Sub-Themen einer Sammlung navigieren → M08. Material zu einem Thema suchen → M06.
    example: Was ist in der Mathematik-Sammlung? → M08. Material zu Bruchrechnung → M06.
---

# M08 — Sammlung-Drilldown

## Wann aktiv
- „Welche Bereiche unter Mathematik?", „Was ist in dieser Sammlung?"
- Singular-Fach **mit** Drilldown-Verb (Bereiche / gegliedert / Unterthemen)

## Pipeline
1. Wenn Fach genannt aber UUID unbekannt → `get_subject_portals` für UUID
2. `browse_collection_tree(nodeId, depth=1)` für Sub-Sammlungen
3. Optional `get_collection_contents` für Inhalte der gewählten Ebene

## Verhalten
- Max. 8 Sub-Cards
- Quick-Reply „Tiefer rein in [X]" pro Sub-Sammlung
