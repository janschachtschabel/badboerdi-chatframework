---
id: PAT-19
label: Unterrichts-Lernpfad
short_purpose: "WANN: Lehrkraft (P-W-LK) plant strukturiert einen Lernpfad/Stundenentwurf zu konkretem Thema (INT-W-10 oder INT-W-03 mit Plan-Sprache). Ab Welle D auch für P-W-SL (Schüler:in) — Selbstlern-Pfade. WOFÜR: Sequenzieller Lernpfad mit MCP-Materialien an passenden Stellen."
# Welle D Sprint 1 (2026-05-17): priority von 480 auf 530 — Eval zeigte,
# dass PAT-06 (priority 595) bei knappen Score-Races konsequent PAT-19
# verdrängt, obwohl die User-Anfrage semantisch klar ein Lernpfad ist
# ("Lernpfad zu Bruchrechnen", "Stunde zu Photosynthese planen"). Mit
# 530 + Specificity-Bonus (3 Gates × 0.01) gewinnt PAT-19 jetzt knapp
# auch ohne Tie-Breaker-Eingriff, sobald das Thema-Slot gefüllt ist.
priority: 530
# Welle D Sprint 1: P-W-SL hinzugefügt — Schüler:innen fragen genauso
# nach Lernpfaden ("ich bin in der 9. Klasse, plan mir eine Stunde zu
# Energie") und sollen NICHT durch PAT-06 (Degradation) gefangen werden.
# Tonalität greift via tone-modifiers.yaml (SL = locker, du-Form).
gate_personas: ["P-W-LK", "P-W-SL"]
# Welle D Sprint 1: gate_states geöffnet auf "*". Vorher waren state-5/6/12
# verlangt, was bei neuen Sessions (state-1) PAT-19 systematisch
# eliminierte — der User-Smoke-Test "Lernpfad zu Bruchrechnen" landete
# in einer leeren Session, state ging über state-1/2 anstatt state-5+,
# und PAT-19 war daher gar kein Kandidat. PAT-19 bleibt via Persona-Gate
# (P-W-LK/SL) und Intent-Gate (INT-W-10/03) eng genug beschränkt; das
# State-Gate war zusätzliche, unbeabsichtigte Sperre.
gate_states: ["*"]
# Lernpfad ist konzeptuell INT-W-10 (Unterrichtsplanung) — wird aber
# auch bei INT-W-03 (Suche nach Unterrichtsmaterial) sinnvoll, wenn
# eine Lehrkraft mit konkretem Thema kommt. Andere Intents (insbes.
# INT-W-11 Inhalt erstellen — Single-Material) sollen NICHT auf
# Lernpfad geroutet werden, sonst schlägt PAT-21 (Canvas-Create) der
# eigentlich richtige Pattern-Sieger PAT-19 nicht mehr.
gate_intents: ["INT-W-10", "INT-W-03"]
# Welle D Sprint 1: signal_high_fit um Lernpfad-Wendungen erweitert.
# Damit gewinnt PAT-19 bei "lernpfad/stundenentwurf/stunde planen"
# auch in Tight-Races gegen PAT-06.
signal_high_fit: ["zielgerichtet", "erfahren", "lernpfad", "stundenentwurf", "stunde planen", "planung", "didaktisch"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
# Pragma-Lockerung: nur "thema" ist Pflicht — fach und stufe können vom
# LLM aus dem Thema (z.B. "Photosynthese" → Biologie/Sek I) abgeleitet
# werden. Das verhindert dass PAT-19 bei jeder Lehrkraft-Anfrage durch
# missing-slots eliminiert wird und PAT-02 mit "zu welchem Fach?" landet.
precondition_slots: ["thema"]
default_tone: sachlich
default_length: mittel
default_detail: standard
response_type: answer
sources: ["mcp"]
# Welle B.5 (2026-05): Lernpfad-Antwort referenziert die einzelnen
# Materialien narrativ in der Prosa ("[Titel](URL)"-Markdown-Links).
# Mit diesem Flag filtert der Backend-Code die Card-Liste auf die
# tatsächlich genannten Cards — die Lehrkraft sieht nur die Kacheln,
# die der LLM in seinen Lernpfad eingewoben hat, nicht die ganze
# Such-Trefferliste.
card_text_link_required: true
format_primary: text
format_follow_up: quick_replies
card_text_mode: reference
tools: ["search_wlo_collections", "search_wlo_topic_pages", "get_collection_contents", "lookup_wlo_vocabulary", "get_node_details"]
---

# PAT-19: Unterrichts-Lernpfad

## Kernregel
Stundenentwurf mit Lernzielen, Zeitangaben, didakt. Hinweisen.

## Wann aktiv
- Lehrkräfte im Search-, Result-Curation- oder Canvas-Arbeit-State
- THEMA bekannt (Pflicht); fach + stufe optional
- Zielgerichtet, erfahren

## Verhalten
- Vollstaendiger Stundenentwurf
- Lernziele, Zeitangaben, didaktische Hinweise
- **Wenn fach/stufe fehlen**: das LLM leitet plausible Defaults aus dem
  Thema ab und nennt sie transparent: "Lernpfad zu Photosynthese,
  passend für Biologie / Sek I (Annahme — bei Bedarf gerne anpassen)".
- Nach dem Lernpfad Fortsetzung anbieten:
- Nach dem Lernpfad Fortsetzung anbieten:
  - "Soll ich den Lernpfad fuer eine andere Klassenstufe anpassen?"
  - "Brauchst du noch ergaenzende Materialien oder einen Lernpfad zu einem anderen Thema?"
