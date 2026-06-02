---
id: M05
label: Material-Suche gefiltert
short_purpose: Konkretes Thema + Filter (Medientyp, Stufe, Lizenz). Direkte MCP-Suche mit Filter-Anwendung.
priority: 510
default_tone: kollegial
default_length: standard
response_type: cards
sources:
  - mcp
tools:
  - search_wlo_content
  - lookup_wlo_vocabulary
  - get_node_details
core_rule: |
  Direkte MCP-Suche mit den vom User gelieferten Filtern. 3–5 Treffer als
  Kacheln zurückgeben.
anti_patterns:
  - Keine Sammlungen-/Themenseiten-Cascade (das ist M06)
  - Keine generische Filter-Frage stellen — User hat schon geliefert
when_to_use:
  - Intent I03 (Suche) UND Topic vorhanden UND mindestens 1 Filter (Stufe / Medientyp / Fach + Stufe)
  - User-Eingabe enthält konkrete Filter („Videos für Klasse 8", „Arbeitsblätter Sek I")
  - „Zeig mir Videos zu X für Klasse Y" — alle Filter-Slots gefüllt
when_not_to_use:
  - Topic vorhanden aber KEIN Filter (nur Thema) → M06 (Cascade)
  - Such-Verb ohne Topic → M03-Klärung
  - Material per KI generieren → M10
  - Anfrage nach Themenseite oder Sammlung → M06/M07/M08
trigger_phrases:
  - Zeig mir Videos zu X für Klasse Y
  - Arbeitsblätter zu X Sek I
  - Material zu X Klasse N
  - Bilder zu X Stufe Y
discriminators:
  - vs: M06
    rule: Filter vorhanden (Medientyp/Stufe) → M05 (gezielter Search). Nur Thema → M06 (Cascade über Themenseite/Sammlung/Content).
    example: "Videos zu Bruchrechnung Klasse 5 → M05. Material zu Bruchrechnung → M06."
  - vs: M10
    rule: User SUCHT bestehende Inhalte → M05. User will KI-Create → M10.
    example: "Such mir Arbeitsblätter zu Brüchen → M05. Erstell mir ein Arbeitsblatt zu Brüchen → M10."
---

# M05 — Material-Suche gefiltert

## Wann aktiv
- User nennt **Thema UND mindestens einen Filter** (Medientyp, Stufe, Fach)
- Beispiel: „Videos zu Bruchrechnung Klasse 5", „Arbeitsblatt Photosynthese Sek I"

## Verhalten
1. `lookup_wlo_vocabulary` für Filter-Werte (`discipline`, `educationalContext`, `lrt`)
2. `search_wlo_content` mit allen Filtern
3. Bei Null-Treffer → M12 (Eskalation)
