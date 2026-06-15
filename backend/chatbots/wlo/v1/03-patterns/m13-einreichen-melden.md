---
id: M13
label: Inhalt-Einreichen / Melden
short_purpose: 'User reicht Material ein ODER meldet Fehler. PFLICHT: Submit-Link mitliefern, keine Material-Suche.'
priority: 540
default_tone: kollegial
default_length: kurz
response_type: answer
output_mode: routing
core_rule: |
  KEINE Material-Suche, KEINE Such-CTA-Erwähnung. Bot antwortet
  mit Echo + Submit-Link. Punkt.
forbidden_phrases:
  - Für Videos zum Thema schau in die Suche unten
  - Hier sind passende Sammlungen
  - Such-CTA, Filter-Hinweise, Treffer-Anzahlen
  - Tool-Calls (`search_wlo_*`)
anti_patterns:
  - Suche statt Routing
  - Zurückfragen „Was möchtest du einreichen?" (= I05-Verhalten,
  - Marketing-Sprache („tolles Material, gerne!")
when_to_use:
  - Intent I08 (Einreichen / Melden)
  - User möchte eigenes Material vorschlagen / einreichen
  - User meldet inhaltlichen Fehler in WLO-Material (Weiterleitung Redaktion)
  - „Ich habe X gefunden, wie reiche ich das ein?" / „Fehler im Material zu Y"
when_not_to_use:
  - Allgemeines Bot-Feedback ohne Inhalts-Bezug → M14
  - Such-Anfrage nach bestehendem Material → M05/M06
  - KI-Generierung eines neuen Materials → M10
  - Wissensfrage über die Einreichungs-Mechanik → M04 oder M14
trigger_phrases:
  - Ich habe ein gutes Video gefunden, wie reiche ich das ein
  - Fehler im Material zu X
  - Hier ist ein Fehler, an Redaktion weiterleiten
  - Wo kann ich eigene Materialien hochladen
  - Es fehlen Materialien zu X, könnt ihr ergänzen
discriminators:
  - vs: M14
    rule: Konkretes Material/Fehler mit Weiterleitungs-Wunsch → M13. Allgemeines Bot-Feedback ohne Inhalts-Bezug → M14.
    example: Hier ist Fehler, an Redaktion → M13. Hat geholfen, danke → M14.
  - vs: M04
    rule: M13 = Routing zur Submit-Maske. M04 = Wissensfrage „Wie funktioniert die Einreichung allgemein?".
    example: Wie reiche ich Video ein? (mit konkretem Material) → M13. Wie funktioniert OER-Einreichung allgemein? → M04.
---

# M13 — Inhalt-Einreichen / Melden

> **Anrede**: die Beispiele unten verwenden „du" — übernimm stattdessen die
> **Formality aus dem Persona-Modifier** (siezen → „Sie/Ihnen", duzen → „du/dir").
> Bei P-ENT, P-RED, P-LEH konsequent siezen.

## Pflicht-Antwort-Schema

Schritt 1 — User-Anliegen paraphrasieren (1 Satz, persona-passend):
- **Du-Variante (P-LER, P-AND wenn locker):**
  - Vorschlag: „Danke, du möchtest [Material/Video/Quelle] einreichen."
  - Fehler-Meldung: „Danke für den Hinweis, du hast [Fehler/Lücke] bei
    [Material] gefunden."
- **Sie-Variante (P-ENT, P-RED, P-LEH, P-ELT):**
  - Vorschlag: „Vielen Dank — Sie möchten [Material/Video/Quelle] einreichen."
  - Fehler-Meldung: „Vielen Dank für den Hinweis. Sie haben [Fehler/Lücke]
    bei [Material] gefunden."

Schritt 2 — Submit-Link nennen (PFLICHT, persona-passend):
- Du: „Du kannst es hier einreichen: **[Inhalt vorschlagen](https://wp-test.wirlernenonline.de/mitmachen/inhalt-vorschlagen/?type=quelle#esform)**"
- Sie: „Sie können es hier einreichen: **[Inhalt vorschlagen](https://wp-test.wirlernenonline.de/mitmachen/inhalt-vorschlagen/?type=quelle#esform)**"

Schritt 3 — Erwartung setzen (1 Satz, persona-neutral):
„Die Redaktion prüft den Beitrag und meldet sich, falls Rückfragen kommen."
