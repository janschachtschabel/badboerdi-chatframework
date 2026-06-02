---
id: M06
label: Material-Suche Cascade
short_purpose: 'Thema vorhanden, Filter unklar oder Erkundungs-Sprache. Kuratiert-Cascade: Themenseite → Sammlung → Content.'
priority: 500
default_tone: kollegial
default_length: standard
response_type: cards
sources:
  - mcp
tools:
  - search_wlo_topic_pages
  - search_wlo_collections
  - search_wlo_content
  - lookup_wlo_vocabulary
core_rule: |
  Kuratiertes vor Algorithmischem. Pipeline durchläuft drei Stufen, bis
  Treffer da sind.
anti_patterns:
  - Keine Vor-Frage stellen wenn Thema klar ist
  - Kein direkter Content-Search wenn Cascade noch nicht durchlaufen
when_to_use:
  - Intent I03 (Suche) UND Topic vorhanden ABER kein/wenig Filter
  - „Material zu X" / „hast du was zu X?" / „such mir was zu X"
  - User möchte ein BREITES Such-Ergebnis, sortiert nach Kuration (Themenseite → Sammlung → Content)
  - I03 mit nur Thema + Fach (ohne Stufe oder Medientyp)
when_not_to_use:
  - Vollständige Filter (Stufe + Medientyp) → M05 (gezielt)
  - Topic fehlt komplett → M03 oder M15
  - User möchte KI-Generierung statt Suche → M10
  - Plan-Anfrage (Lernpfad/Reihe) → M09
trigger_phrases:
  - Material zu X
  - Hast du was zu X
  - Such mir was zu X
  - Ich brauche Material zu X
  - Welches Material gibt es zu X
discriminators:
  - vs: M05
    rule: Nur Thema → M06 (Cascade). Thema + Filter (Stufe/Medientyp) → M05 (gefiltert).
    example: "Material zu Bruchrechnung → M06. Videos zu Bruchrechnung Klasse 5 → M05."
  - vs: M09
    rule: 'Hauptverb entscheidet. Such-Verb als Hauptverb (suche/finde/zeig/hast du) → M06 — auch wenn ein um-zu-planen oder Unterrichtseinheit-Nebensatz folgt. Plan-Verb als Hauptverb (plane/stelle zusammen/Stundenentwurf) → M09.'
    example: 'Material zur Unterrichtseinheit Bruchrechnung → M06. Plane Unterrichtsreihe Bruchrechnung → M09. Ich suche Material, um meine Unterrichtseinheit zu planen → M06 (Hauptverb=suche).'
  - vs: M10
    rule: Such-Verb (zeig/finde/hast du) → M06. Create-Verb (erstell/generiere) → M10.
    example: "Such mir Quiz zu X → M06. Erstell mir Quiz zu X → M10."
---

# M06 — Material-Suche Cascade

## Wann aktiv
- Thema da, aber kein konkreter Filter
- Erkundungs-Sprache („was habt ihr zu Klima?", „zeig mir was zu Bruchrechnung")

## Pipeline
1. `search_wlo_topic_pages(query=thema)` → wenn Treffer, fertig
2. Sonst `search_wlo_collections(query=thema)` → wenn Treffer, fertig
3. Sonst `search_wlo_content(query=thema)`
4. Bei 0 Treffer in allen → M12 (Eskalation)

## Verhalten
- Bei >5 Treffern: kuratiert 3–4 mit Diversität (Stufe + Medientyp)
- Wenn Themenseite getroffen: deren Inhalte direkt zeigen
