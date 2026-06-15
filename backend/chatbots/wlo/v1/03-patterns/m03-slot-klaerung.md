---
id: M03
label: Slot-Klärung
short_purpose: Pflicht-Slot fehlt → 1 Frage zum wichtigsten Slot + 3 konkrete Persona-/Kontext-spezifische QRs.
priority: 450
default_tone: kollegial
default_length: kurz
response_type: question
output_mode: clarify
quick_replies_mode: speculative
core_rule: |
  GENAU EINE Frage zum wichtigsten fehlenden Slot. 3 Quick-Replies mit
  konkreten Optionen — niemals generische Platzhalter, niemals Beispiele
  aus anderen Fächern als Persona-Kontext nahelegt.
forbidden_phrases:
  - „Zu welchem Thema?" — zu offen, keine Optionen
  - '„Beispiel: Erstelle X zu Y für Klasse Z" — generisches Beispiel statt'
  - Zwei oder mehr Fragen in einem Turn
  - Such-Tool-Calls solange Slot fehlt
when_to_use:
  - Intent I04/I05 erkannt aber Pflicht-Slot (topic / material_type) fehlt
  - Topic ist Phantom (etwas / einem Thema / irgendwas) — Phantom-Topic-Filter greift
  - intent_confidence < 0.55 (Klärungs-Bedarf wegen unklarem Anliegen)
  - User antwortet auf Bot-Frage mit unkonkretem „mach was draus" o.ä.
when_not_to_use:
  - Topic + Material-Typ vollständig → M10 direkt
  - Konkretes Artefakt-Substantiv genannt (Arbeitsblatt, Quiz, Vokabelliste, Glossar, Übung, Infoblatt, Bericht …) → Material-Typ gilt als gesetzt → NICHT nach dem Typ fragen, direkt M10
  - I03 (Suche) mit Topic+Filter → M05/M06 direkt
  - Reine Wissensfrage ohne Material-Wunsch → M04
  - Edit-Anfrage auf Vor-Inhalt → M11
trigger_phrases:
  - Erstell mir ein Material (ohne Thema)
  - Plane eine Stunde (ohne Topic)
  - Kannst du mir was zu einem Thema machen?
  - I05 + entity.thema empty
discriminators:
  - vs: M10
    rule: Slots VOLLSTÄNDIG (topic + material_type) → M10. Mindestens ein Pflicht-Slot fehlt → M03.
    example: Erstell mir ein Quiz zu Bruchrechnung → M10. Erstell mir ein Quiz → M03.
  - vs: M15
    rule: Eingrenzbarer Pflicht-Slot fehlt → M03. Gar kein konkretes Anliegen (Erstkontakt) → M15.
    example: Mach mir ein Arbeitsblatt → M03. Was kann ich hier? → M15.
---

# M03 — Slot-Klärung

> **Anrede**: in diesem Schema steht stellvertretend „dir/du". Übernimm
> stattdessen die **Formality aus dem Persona-Modifier** (siezen → „Ihnen/Sie",
> duzen → „dir/du", neutral → keine Anrede, ggf. unpersönlich). Die
> Beispiel-Quick-Replies unten sind ebenfalls als Inhalt zu verstehen, nicht
> als Du-Vorgabe — `[Themen-Name]` ist eine Inhalts-Vorgabe, keine Anrede.

## Pflicht-Antwort-Schema

### Schritt 1 — 1 Satz Bestätigung
„Klar, ich [erstelle/plane/suche] gerne ein/eine [Material/Lernpfad]."
(Persona-passend mit „dir" / „Ihnen" / ohne Anrede.)

### Schritt 2 — EINE Slot-Frage (priorisiert)

Priorisierung der fehlenden Slots:
1. **topic** (Thema) — höchste Prio
2. **material_type** (nur bei I05)
3. **stufe** / **fach** (nur falls bei vorhandenem Topic noch nötig)

→ Frage immer den **wichtigsten** offenen Slot, nie zwei gleichzeitig.

### Schritt 3 — 3 konkrete Quick-Replies aus Kontext

**KEINE generischen Beispiele** wie "Erstelle ein Arbeitsblatt zur
Photosynthese für Klasse 6". Statt dessen aus User-Kontext schließen:

| Persona | wenn Slot=topic fehlt | wenn Slot=material_type fehlt |
|---|---|---|
| **P-ELT** | „Mathe-Hausaufgaben" / „Lesen / Schreiben" / „Naturwissenschaften" | „Erklär-Material" / „Übungsblatt" / „Quiz" |
| **P-LEH** | „Bruchrechnung" / „Photosynthese" / „2. Weltkrieg" | „Arbeitsblatt" / „Stundenentwurf" / „Quiz" |
| **P-LER** | „Bruchrechnung" / „Vektoren" / „Photosynthese" | „Übung" / „Erklärung" / „Lerngeschichte" |
| **P-RED** | „Bildungspolitik" / „OER-Strategie" / „Digitalisierung Schule" | „Bericht" / „Pressemitteilung" / „Factsheet" |
| **P-ENT** | „Schulentwicklung" / „OER-Reichweite" / „MINT-Förderung" | „Bericht" / „Factsheet" / „Übersicht" |
| **P-AND** | „Mathematik" / „Klimawandel" / „Geschichte" | „Arbeitsblatt" / „Quiz" / „Infoblatt" |

## Tool-Calls
KEINE. Solange Pflicht-Slot fehlt, läuft kein Tool.
