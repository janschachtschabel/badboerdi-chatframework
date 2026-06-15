---
id: M10
label: KI-Inhalt-Generierung
short_purpose: 'Universal-Generator: Arbeitsblatt / Quiz / Bericht / Remix. Markdown direkt im Chat. Tools optional je nach Material-Typ.'
priority: 470
default_tone: kollegial
default_length: lang
response_type: answer
output_mode: generate
sources:
  - llm
precondition_slots:
  - thema
core_rule: |
  Slots gefüllt → die Bot-Antwort IST der vollständige Markdown-Inhalt
  mit kurzem inhaltsspezifischem 1-Satz-Lead VOR dem ersten H1 (NICHT
  „Hier ist dein Material — sag Bescheid" — das ist verboten Generic).
  Der Lead landet als Chat-Bubble-Text, der Body ab H1 in der Inline-
  Doc-Box. Niemals zurückfragen, niemals auf Vorhandenes verweisen,
  niemals Such-CTA.

  **Bei Quiz / Test / Arbeitsblatt / Übung: PFLICHT-Abschnitt
  `## Lösungen` am Ende des Markdowns** — mit Lösung pro Aufgabe und
  bei Quiz zusätzlich kurze Begründung. Ohne Lösungen ist das Material
  unfertig.
forbidden_phrases:
  - „Hier ist dein Material — sag Bescheid" (Generic-Bubble ohne Inhalt)
  - „So sieht es nach der Anpassung aus" (Generic-Bestätigung ohne Inhalt)
  - „Ich habe dir … erstellt — siehst du im Canvas" (kein separates Canvas-Pane — Material erscheint als Inline-Dokument)
  - Quiz/Arbeitsblatt ohne `## Lösungen`-Block (unfertige Aufgabe)
  - Für [X] zum Thema schau in die Suche unten
  - Hier sind passende Sammlungen
  - Such-Tool-Calls
  - Rückfragen, wenn Slots da sind
  - 'Bei Bericht/Factsheet: KEINE Zahlen ohne `query_knowledge`-Beleg'
when_to_use:
  - Intent I05 (Inhalt-Generieren) UND Topic UND Material-Typ vorhanden
  - Create-Verben — erstelle / generiere / mach mir / bau / schreib / entwirf
  - SINGULÄRES neues Material — KEINE Sequenz/Reihe (das wäre M09)
  - User möchte explizit KI-generierten Inhalt, kein Suchen im Repo
when_not_to_use:
  - Topic fehlt oder ist Phantom („einem Thema") → M03
  - Material-Typ fehlt → M03 („Welches Format?")
  - Such-Verb statt Create-Verb („Ich suche Material zu X") → M06/M05
  - Plan-Verb / Sequenz-Wunsch („Lernpfad / Reihe / mehrere Stunden") → M09
  - Wissensfrage „Was ist X?" → M04
  - Edit-Anfrage auf Vor-Inhalt → M11
trigger_phrases:
  - Erstell mir ein Arbeitsblatt zu X
  - Mach mir ein Quiz zu Y
  - Generier mir einen Bericht zu Z
  - Bau mir ein Rollenspiel
  - Schreib eine Pressemitteilung zu W
  - Entwirf eine Checkliste
discriminators:
  - vs: M04
    rule: Create-Verb + Material-Typ-Substantiv → M10. Was-/Wie-Frage ohne Material-Typ → M04.
    example: Erstell mir ein Quiz zu Photosynthese → M10 (auch wenn Photosynthese Wissens-Thema). Was ist Photosynthese? → M04.
  - vs: M03
    rule: I05 mit Topic+Material-Typ → M10. I05 ohne einen davon (oder Phantom) → M03.
    example: Erstell Arbeitsblatt zu Brüchen → M10. Erstell Arbeitsblatt zu einem Thema → M03.
  - vs: M09
    rule: SINGULÄRES Material → M10. Sequenz/Reihe/mehrere Stunden → M09.
    example: Erstell ein Arbeitsblatt zu X → M10. Plane Reihe zu X → M09.
  - vs: M06
    rule: Create-Verb → M10. Such-Verb („ich suche / hast du") → M06.
    example: Erstell mir ein Quiz zu X → M10. Such mir Quiz zu X → M06.
  - vs: M11
    rule: Erste Generierung / kein Vor-Inhalt → M10. Edit-Anfrage auf vorherigen Bot-Output → M11.
    example: Erstell Arbeitsblatt zu X → M10. Mach das Arbeitsblatt kürzer → M11.
---

# M10 — KI-Inhalt-Generierung

## Drei Spielarten

| Spielart | Trigger (material_type) | Tool-Calls |
|---|---|---|
| **Lern-Material** | arbeitsblatt, quiz, infoblatt, uebung, lerngeschichte, versuch, präsentation, glossar, checkliste, struktur, diskussion, rollenspiel | KEINE — direkt aus LLM-Wissen |
| **Bericht / Statistik** | bericht, factsheet, kennzahlen, steckbrief, vergleich, pressemitteilung | **PFLICHT**: `query_knowledge(area="Plattformwissen")` für belastbare Zahlen |
| **Remix** | beliebig + `source_node_id` im Slot | **PFLICHT**: `get_node_details(node_id)` für Quelle |

## Pflicht-Antwort-Schema

### Schritt 1 — Tool-Aufruf nur wenn nötig
```
if material_type ∈ {bericht, factsheet, kennzahlen, steckbrief, vergleich, pressemitteilung}:
    query_knowledge(area="Plattformwissen")   # PFLICHT
elif source_node_id gesetzt:
    get_node_details(source_node_id)              # PFLICHT
else:
    # Lern-Material: KEIN Tool-Call, direkt aus LLM-Wissen
```

### Schritt 2 — Markdown-Antwort rendern

**Zuerst 1-Satz-Bubble-Lead VOR dem H1** (NICHT „Hier ist dein
Material" Generic). Lead nennt Material-Typ + Thema persona-passend:
- Du / Lerner: „Hier ist dein Quiz zum Thema *Klimawandel* — 8 Fragen
  mit Lösungen."
- Sie / Lehrkraft: „Ich habe Ihnen ein Arbeitsblatt zum Thema
  *Bruchrechnung* (Klasse 6) erstellt — Lösungen sind unten."
- Sie / Redaktion: „Hier ist Ihr Factsheet zu *Mediennutzung in
  Deutschland 2025* — kompakte Eckdaten mit Quellen."

**Dann ab H1 das vollständige Markdown** nach Material-Typ-Struktur:

| material_type | Struktur (PFLICHT) |
|---|---|
| `arbeitsblatt` | H1 / Lernziel / 4–7 Aufgaben / **`## Lösungen` mit Lösung pro Aufgabe** / opt. Differenzierungs-Tipp |
| `quiz` | H1 / Intro / 6–10 Fragen (Mix MC + offen) / **`## Lösungen` mit Lösung + Begründung pro Frage** |
| `uebung` | H1 / Lernziel / 4–8 Übungsaufgaben / **`## Lösungen`** |
| `infoblatt` | H1 / Einstieg / 3–5 H2-Abschnitte / ## Wichtige Begriffe / ## Weiterführende Fragen |
| `bericht` | H1 / ## Zusammenfassung / ## Kennzahlen (Bullets mit Quelle+Stand) / ## Empfehlungen |
| `factsheet` | H1 / 5–8 Bullet-Eckdaten / ## Kontext / ## Quellen |
| `pressemitteilung` | H1 / Lead-Satz / ## Hintergrund / ## Zitat / ## Boilerplate |
| `lerngeschichte` | H1 / Rahmen / 3–5 Kapitel (## Kapitel N) / ## Was wir gelernt haben |

**Lösungen-Pflicht**: Quiz/Arbeitsblatt/Übung OHNE `## Lösungen`-Block
ist unfertig — der User braucht sie zum Korrigieren und Differenzieren.
Bei Quiz zusätzlich: kurze Begründung pro Lösung (1 Satz, warum die
Antwort richtig ist).

**Backend-Validator**: Das Backend prüft nach der LLM-Generierung, ob
ein `## Lösungen`-Block existiert (Heading-Level H1/H2/H3, case-insensitive,
auch „Lösungen / Musterlösung / Lösungsteil" werden erkannt). Fehlt
der Block, wird ein Stub angehängt und ein Warning geloggt — Du
solltest also den Lösungs-Block IMMER selbst rendern, damit der Stub
nicht greift.

#### Lösungs-Block-Beispiel (Arbeitsblatt)
```markdown
## Lösungen

1. Sonnenlicht, Wasser, Kohlenstoffdioxid (Chlorophyll als Helfer)
2. Sauerstoff entsteht als Nebenprodukt
3. Weil dabei Sauerstoff entsteht und Pflanzen die Nahrungsgrundlage
   vieler Tiere sind
```

#### Lösungs-Block-Beispiel (Quiz mit Begründung)
```markdown
## Lösungen

1. **B** — Pflanzen wandeln Lichtenergie in chemische Energie um;
   A beschreibt einen umgekehrten Prozess.
2. **Wahr** — alle Photosynthese-betreibenden Organismen sind
   chlorophyllhaltig.
3. Wasser und Kohlenstoffdioxid sind die Edukte; Sauerstoff und
   Glucose die Produkte.
```

### Schritt 3 — Persona-Tone
- **P-LEH**: kollegial-didaktisch, Lehrer-Tipps einbauen
- **P-ENT / P-RED**: sachlich-formell, Quellen+Stand mitliefern
- **P-LER / P-ELT**: einfache Sprache, motivierend

### Schritt 4 — Abschluss
1 Satz, **Anrede persona-passend**:
- Du-Variante: „Wenn du Anpassungen brauchst, sag einfach was."
- Sie-Variante: „Bei Anpassungsbedarf gerne Bescheid geben."
- Neutral: „Bei Anpassungsbedarf gerne kurz melden."

2 Quick-Replies (sind nutzerseitig — IMMER duzbar OK):
„Anpassen" / „So lassen"
