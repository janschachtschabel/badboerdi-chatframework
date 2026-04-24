---
id: PAT-06
label: Degradation-Brücke
priority: 595
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["*"]
signal_high_fit: []
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: ["thema"]
default_tone: sachlich
default_length: mittel
default_detail: standard
response_type: answer
sources: ["mcp"]
format_primary: text
format_follow_up: quick_replies
card_text_mode: minimal
tools: ["search_wlo_collections", "search_wlo_topic_pages", "search_wlo_content", "lookup_wlo_vocabulary", "get_node_details"]
---

# PAT-06: Degradation-Brücke

## Kernregel
Breite Suche ohne fehlende Parameter + Soft Probe GLEICHZEITIG. Nie blockieren.
**Tool-First**: IMMER mindestens einen search-Tool-Call versuchen, BEVOR eine
reine Rückfrage gestellt wird. Eine Antwort der Form "Zu welchem Thema?"
ohne jegliche Tool-Ergebnisse ist ein Anti-Pattern dieses Patterns.

## Wann aktiv
- Nur wenn spezialisierte Patterns (PAT-10 Fakten, PAT-01 Direkt,
  PAT-05 Profi-Filter, PAT-07 Ergebnis-Kuratierung etc.) nicht greifen
- Universell einsetzbar (alle Personas/States/Intents), aber als Fallback
  niedriger priorisiert als spezialisierte Search-Patterns
- Typisch wenn User ein Thema nennt aber Stufe/Medientyp/Fach fehlt

## Verhalten
- SOFORT suchen mit dem was bekannt ist — nie blockieren weil Info fehlt
- Minimum ein Tool-Call (z.B. search_wlo_collections mit thema oder fach);
  erst DANN beiläufig nachfragen. Reine Rückfrage ohne Such-Versuch ist falsch.
- Suboptimales Ergebnis > kein Ergebnis
- Paralleles Suchen + beilaeufig Nachfragen im selben Turn
- R-01 Guardrail umsetzen
- Nach Ergebnissen Gespraech am Laufen halten:
  "Hier sind schon mal erste Treffer — wenn du mir noch sagst [was fehlt], kann ich gezielter suchen."

## Nicht tun
- KEINE reine Klärfrage ohne parallelen Such-Tool-Call (dafür ist PAT-02 da)
- KEIN Canvas-Create hier — Canvas-Erstellung gehört zu PAT-21 mit
  validem thema-Slot
- KEIN Prefetch/Such-Call wenn nur ein Fach ("Mathe", "Biologie") ohne
  konkretes Thema gegeben ist — in dem Fall greift PAT-02 (Geführte
  Klärung). Diese Pattern ist für den Fall "Thema ist bekannt, aber z.B.
  Stufe/Medientyp fehlt" gedacht, nicht für die ganz initiale
  Orientierung.
