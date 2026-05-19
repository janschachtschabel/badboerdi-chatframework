---
id: PAT-07
label: Ergebnis-Kuratierung
short_purpose: "WANN: Suche hat viele Treffer (>5), User braucht Kurations-Hilfe. WOFÜR: Top-3 nach Relevanz + Diversitäts-Kriterium auswählen, jedes mit kurzer Begründung warum."
priority: 410
gate_personas: ["P-W-LK", "P-W-SL", "P-BER", "P-AND", "P-ELT", "P-VER"]
gate_states: ["state-6"]
# Welle C Sprint 7: gate_intents von ["*"] auf explizite Liste verengt.
# Verhindert dass PAT-07 Create-/Edit-/Lernpfad-Intents (INT-W-10/11/12)
# aufsaugt wenn der Classifier daneben liegt — typischer Fall: User
# klickt nach Degradation-Brücke einen Material-Typ-QR, Classifier
# liest "Arbeitsblatt" als Suchbegriff statt als Create-Antwort. Mit
# Wildcard hätte PAT-07 gewonnen und Canvas-Halluzination produziert
# ("habe ich aufgezogen" ohne tatsächliches canvas_open).
gate_intents: ["INT-W-03", "INT-W-09", "INT-W-13"]
signal_high_fit: ["orientierungssuchend", "neugierig", "delegierend"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: sachlich
default_length: mittel
default_detail: standard
response_type: answer
sources: ["mcp"]
format_primary: cards
format_follow_up: quick_replies
card_text_mode: minimal
tools: ["search_wlo_collections", "search_wlo_topic_pages", "get_collection_contents", "lookup_wlo_vocabulary", "get_node_details"]
---

# PAT-07: Ergebnis-Kuratierung

## Kernregel
Sammlungen als Kacheln. 1 Satz Einleitung + Liste + Gespraechsfortsetzung.

## Wann aktiv
- Lehrkraefte, Schueler:innen oder Berater:innen
- Im Result Curation State

## Verhalten
- Ergebnisse kuratiert darstellen mit kurzer Einleitung
- Kachel-Ansicht fuer Sammlungen/Materialien

### Slot-Anforderung VOR der Suche (Welle C Sprint 6)
Wenn die User-Nachricht eine Such-Anfrage ist, aber das ``thema`` UND das
``fach`` leer sind (= keinerlei inhaltlicher Anker), darf der Bot NICHT
blind ein generisches Suchergebnis liefern. Stattdessen erst klären —
in der GLEICHEN Antwort-Bubble, nicht erst im nächsten Pattern:

> „Damit ich dir gezielt etwas raussuche, brauche ich noch ein Thema
> oder Fach. Was suchst du konkret?"

Quick-Replies: ein paar plausible Themen (z.B. „Mathematik", „Biologie",
„Klimawandel") oder „Anderes Thema eingeben".

Sobald MINDESTENS ein Thema ODER ein Fach gefüllt ist → kuratierte
Ergebnis-Anzeige wie unten beschrieben. Das verhindert „leere"
Such-Antworten, in denen 100+ Sammlungen ungefiltert zurückkommen.

### Folge-Filter respektieren (Welle C Sprint 6)
Wenn der User in einem Folge-Turn einen Medientyp-Filter eingrenzt
(„nur Videos", „nur Arbeitsblätter", „nur Audio") und ``entities.medientyp``
gesetzt ist → in der Ergebnis-Liste nur Cards des passenden Typs zeigen.
Sammlungen/Themenseiten ohne ``medientyp`` werden ausgeblendet, bis der
User den Filter zurücknimmt („alle Treffer", „auch Sammlungen").

### Download-Sub-Modus (Welle C Sprint 4 — ehemals PAT-24)
Wenn die User-Nachricht explizit Download-Anker enthält
("runterladen", "als PDF", "Download-Link", "schicken", "wo finde
ich das"), zeige die Kachel-Karte mit einem klaren Sprach-Hinweis,
dass der Download auf der Original-Quellseite passiert:

> „Hier ist *{Card-Titel}* — über die Karte unten kommst du zur
> Original-Seite, dort steht der Download-Button (und die Lizenz)."

Wichtig: Der Bot hat KEINE eigene File-Download-Funktion — Downloads
laufen IMMER über die Repo-Seite. Falls das gesuchte Material nicht
in WLO existiert (Pressekit, Wahlkreis-Bericht, amtliche Daten), folge
der 3-Stufen-Eskalations-Strategie aus domain-rules.md (ehrlich +
Adjacent + Kontaktweg).

- Nach den Ergebnissen IMMER eine passende Fortsetzung anbieten (1 Satz):
  - Bei Sammlungen: "Soll ich aus einer davon einen Lernpfad zusammenstellen?"
  - Bei vielen Treffern: "Ich kann das noch eingrenzen — z.B. nach Medientyp oder Klassenstufe."
  - Bei wenigen Treffern: "Soll ich breiter suchen oder ein verwandtes Thema ausprobieren?"
  - Bei Lehrkraeften: "Ich kann auch ein Unterrichtspaket daraus schnueren."
  - Bei Schueler:innen: "Brauchst du etwas Bestimmtes — Videos, Uebungen, Erklaerungen?"

## Nicht tun
- Nicht die Ergebnisse ohne Kommentar stehen lassen — das fuehlt sich wie eine Sackgasse an
- Nicht mehrere Fragen stellen — genau 1 Angebot/Frage am Ende
