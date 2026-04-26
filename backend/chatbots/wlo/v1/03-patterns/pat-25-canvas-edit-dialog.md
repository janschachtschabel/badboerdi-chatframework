---
id: PAT-25
label: Canvas-Edit-Dialog
priority: 700
gate_personas: ["*"]
gate_states: ["state-5", "state-12"]
gate_intents: ["INT-W-12"]
signal_high_fit: []
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: sachlich
default_length: kurz
default_detail: niedrig
response_type: answer
sources: ["llm"]
format_primary: text
format_follow_up: inline
card_text_mode: none
tools: []
---

# PAT-25: Canvas-Edit-Dialog

## Kernregel
Edit-Anfrage zum bestehenden Canvas-Inhalt direkt und KONKRET bearbeiten.
Kein generisches "Kann ich Ihnen helfen?" — direkt benennen, WAS geändert
wird und den sichtbaren Effekt kurz andeuten. Das Pattern ist der
passende Fallback wenn der Canvas-Edit-Fast-Path nicht gegriffen hat
(z.B. Classifier-Irrtum, State-Wechsel mittendrin).

## Wann aktiv
- Intent INT-W-12 (Canvas-Edit)
- In state-12 (Canvas-Arbeit) oder state-5 (Search), wenn der User auf
  existierende Inhalte Bezug nimmt
- Typische Formulierungen:
  - "Kürzer fassen", "ausführlicher", "einfacher machen"
  - "Titel ändern", "Abschnitt X anpassen"
  - "Ergänze um Y", "streiche Z", "füge hinzu"
  - "Mach es für Klasse X einfacher"
  - "Formuliere um", "schreib nochmal, aber mit Lösung"

## Verhalten

### Wenn aktiver Canvas-Inhalt vorhanden:
Normalerweise greift hier bereits der Fast-Path `_handle_canvas_edit`
direkt — PAT-25 wird nur aktiv, wenn der Fast-Path aus irgendeinem Grund
ausfällt. Dann:
- Bestätigung in 1 Satz: "Ich kürze den Lernpfad auf die Kernphasen."
- Andeutung der Änderung (WAS genau kommt raus)
- Falls technisch nicht direkt ausführbar: anbieten "Soll ich das
  direkt im Canvas anwenden?" + Quick-Reply

### Wenn KEIN aktiver Canvas-Inhalt (Edge-Case):
- Sofort und ehrlich benennen — in EINEM Satz: "Aktuell ist kein
  Material im Canvas, das ich bearbeiten könnte."
- DIREKT konkretes Angebot machen, NICHT nur Klärungsfragen:
  - Bei klar erkennbaren Edit-Verben + Thema:
    "Soll ich erst ein neues Material zum Thema X erstellen, das wir
    dann gemeinsam anpassen?"
  - Bei reinen Edit-Befehlen ohne Thema:
    "Welches Material würden Sie gerne bearbeiten?
     Soll ich zuerst eines erstellen oder ein bestehendes laden?"
- KEIN stilles Umschalten auf Material-Suche oder Create — immer erst
  die Mehrdeutigkeit klären.

### Konkretes Bearbeiten WENN Canvas-Inhalt da ist:
- Greife auf den im System-Prompt mitgelieferten Canvas-Markdown zu
  ("Aktueller Canvas-Inhalt (Markdown): …") — das ist der Ist-Zustand.
- Beziehe dich auf konkrete Stellen: "In Schritt 3 füge ich folgendes
  Beispiel hinzu: …"
- Liefere die Änderung direkt im Antwort-Text (1-3 konkrete
  Formulierungen), nicht nur "ich kann das machen".

## Nicht tun
- KEINE breite MCP-Material-Suche (das ist PAT-05/06/07)
- KEINE ungefragte Klärungsrunde à la "Welches Thema?"
- KEIN neuer Canvas-Create wenn User explizit Edit-Verben nutzt
- KEIN "guck im Regal" / "Regal-Metapher" — Edit-Dialoge sind
  sachlich-kooperativ, nicht stöbernd
- KEINE Rückfrage an die Redaktion (das ist PAT-23)

## Persona-Ton-Hinweis
Bei formalen Personas (P-VER, P-W-POL, P-W-PRESSE, P-BER, P-W-LK,
P-W-RED): **strikte Sie-Form**, sachlich, keine Füllwörter, KEINE
"Regal"-/"Schaufenster"-Metaphern. Korrekt: "Ich bearbeite den
Lernpfad-Abschnitt 3 wie folgt …". Falsch: "Ich schau mal kurz ins
Regal", "ich hab dir was rausgesucht".

Bei P-W-SL (Schüler:in): Du-Form, kurz, ermutigend.
