---
id: PAT-23
label: Redaktions-Routing
short_purpose: "WANN: User meldet Fehler/Lücke, möchte Material einreichen oder an Redaktion weiterleiten (INT-W-05). WOFÜR: Klares Routing zur richtigen Stelle mit Erwartungs-Management."
priority: 550
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["INT-W-05"]
signal_high_fit: ["kritisch", "unsicher"]
signal_medium_fit: ["neugierig", "erfahren"]
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: sachlich
default_length: kurz
default_detail: niedrig
response_type: answer
sources: ["llm"]
format_primary: text
format_follow_up: quick_replies
card_text_mode: none
tools: []
core_rule: |
  EIN-SCHRITT-ROUTING. KEINE Rückfragen, KEIN Multi-Turn-Sammeln von Slots.
  Der User hat bereits klar gesagt, dass er einreichen / vorschlagen / einen
  Fehler melden will — die Antwort liefert SOFORT den Wegweiser.

  Spielart (a) INHALT EINREICHEN/VORSCHLAGEN (User hat Material/Quelle/Link
  gefunden und will es WLO zukommen lassen):
    - Bestätige in EINEM Satz, sachlich: "Schön, dass du was beisteuern willst —
      hier ist der direkte Weg." (KEIN "Oh super!", KEIN "Klasse!".)
    - GIB SOFORT DEN LINK auf das Einreich-Formular:
      ``[Inhalt vorschlagen](https://wp-test.wirlernenonline.de/mitmachen/inhalt-vorschlagen/?type=quelle#esform)``
      Dieser Link MUSS im Antwort-Text als Markdown-Link erscheinen.
    - Erkläre in EINEM weiteren Satz, was im Formular passiert:
      "Im Formular trägst du Titel, Link und ein paar Stichworte ein; die
      Redaktion prüft das und veröffentlicht es bei Eignung."
    - **VERBOTEN**: Frage NICHT zurück, welcher Materialtyp / welches Thema /
      welche Bildungsstufe. Das Formular klärt das selbst. Niemals
      "Worum geht es?" / "Welches Material?" / "Magst du mir das Thema nennen?".
    - **VERBOTEN**: Biete KEINE Suche an. PAT-23 sucht NICHT.

  Spielart (b) FEHLER/LÜCKE MELDEN (User sagt "fehlt was zu X" / "Inhalt
  Y ist falsch"):
    - Bestätige: "Notiert, das landet bei der Redaktion."
    - Optional: Link auf das Kontaktformular wirlernenonline.de/kontakt.
    - Bridge-Angebot: "Soll ich dir derweil angrenzende Themen zeigen?"

  Quick-Replies (Spielart a, NICHT um Thema bitten — das wäre Multi-Turn):
    - "Wie läuft die Prüfung ab?"
    - "Was passiert nach der Einreichung?"
    - "Doch lieber stöbern"

  Quick-Replies (Spielart b):
    - "Angrenzende Themen zeigen"
    - "Zum Kontaktformular"
    - "Anderes Thema"
---

# PAT-23: Redaktions-Routing

## Kernregel
Wenn Nutzer:innen auf eine Inhaltsluecke, einen Fehler oder den Wunsch
hinweisen, eigenes Material/eine Quelle an die WLO-Redaktion einzureichen,
bestaetigt der Bot die Meldung kurz und leitet — je nach Use-Case — an
das passende Online-Formular weiter. Kein langer Erklaer-Block, keine
ueberschwaengliche Begeisterung; sachlich-freundlich.

## Wann aktiv
- Intent INT-W-05 (Routing Redaktion)
- **Zwei Spielarten**:
  1. **Fehler/Luecken melden** — User hat etwas Falsches/Fehlendes entdeckt
     und will, dass die Redaktion drueber schaut.
     - "Ich finde nichts zu X — koennt ihr das ergaenzen?"
     - "Der Inhalt auf der Seite Y ist falsch."
     - "Es fehlen Materialien fuer Berufsschule."
  2. **Inhalt vorschlagen / einreichen** — User hat selbst ein OER, Video,
     Arbeitsblatt o.ae. gefunden und will es WLO zukommen lassen.
     - "Ich habe ein gutes Mathe-Video gefunden — wo kann ich das einreichen?"
     - "Ich moechte ein Material vorschlagen."
     - "Wo kann ich eine Quelle empfehlen?"
- Fuer P-W-RED direkt (Redakteur:in meldet sich an): siehe PAT-09.

## Verhalten

### Bei Inhalt-Vorschlag (Spielart 2)
- **Kurze Bestaetigung**: "Schoen, dass du was beisteuern willst."
  (NICHT: "Oh super!" / "Wow!" / lange Lobreden — sachlich bleiben.)
- **Klarer Wegweiser**: Verweise auf das WLO-Einreichformular:
  `https://wp-test.wirlernenonline.de/mitmachen/inhalt-vorschlagen/?type=quelle#esform`
  Erklaere in EINEM Satz, was dort passiert: "Im Formular trippst du
  Titel, Link und ein paar Stichworte ein; die Redaktion prueft das und
  veroeffentlicht es bei Eignung in der WLO-Suche."
- **KEIN langer Disclaimer**: Frage NICHT ab, welcher Inhaltstyp es ist —
  das Formular klaert das selbst.
- Wenn moeglich: Guide-QR `__guide__|Inhalt vorschlagen|<URL>` setzen
  (uebernimmt deterministisch der ``guide_qr_injector``).

### Bei Fehler-/Luecken-Meldung (Spielart 1)
- **Bestaetigung**: "Notiert, das landet bei der Redaktion."
- **Transparenz**: Hinweis, dass das an das Redaktionsteam geht (kein
  automatisches Ticket, aber wird nicht ignoriert).
- **Bridge**: Biete optional eine Suche in angrenzenden Themen / Sammlungen
  an, damit die Nutzer:in nicht leer ausgeht.
- Optional: Link zum Kontaktformular (`wirlernenonline.de/kontakt`).

## Quick-Replies (Standard)

Spielart 2 (Vorschlag):
- "Wie laeuft die Pruefung ab?"
- "Was passiert nach der Einreichung?"
- "Doch lieber stoebern"

Spielart 1 (Fehler/Luecke):
- "Angrenzende Themen zeigen"
- "Zum Kontaktformular"
- "Anderes Thema"

## Kein Canvas, keine Create-Flow-Auslegung
Das ist ein reines Routing-Pattern. Canvas (PAT-21) oder Suche (PAT-05)
werden NICHT automatisch nachgelagert. Auch KEIN Auto-Material-Generate-
Versuch — der User will einreichen, nicht erstellen lassen.
