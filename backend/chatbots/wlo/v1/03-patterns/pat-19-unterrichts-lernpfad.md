---
id: PAT-19
label: Unterrichts-Lernpfad
priority: 480
gate_personas: ["P-W-LK"]
gate_states: ["state-5", "state-6", "state-12"]
# Lernpfad ist konzeptuell INT-W-10 (Unterrichtsplanung) — wird aber
# auch bei INT-W-03b (Suche nach Unterrichtsmaterial) sinnvoll, wenn
# eine Lehrkraft mit konkretem Thema kommt. Andere Intents (insbes.
# INT-W-11 Inhalt erstellen — Single-Material) sollen NICHT auf
# Lernpfad geroutet werden, sonst schlägt PAT-21 (Canvas-Create) der
# eigentlich richtige Pattern-Sieger PAT-19 nicht mehr.
gate_intents: ["INT-W-10", "INT-W-03b"]
signal_high_fit: ["zielgerichtet", "erfahren"]
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
