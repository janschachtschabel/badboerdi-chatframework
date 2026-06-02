---
id: M12
label: Null-Treffer-Eskalation
short_purpose: MCP-Suche lieferte 0 Treffer → Synonym-Lookup, breitere Suche, dann Alternativ-Pfad. Niemals 'kann ich nicht'.
priority: 590
default_tone: kollegial
default_length: standard
response_type: answer
sources:
  - mcp
tools:
  - lookup_wlo_vocabulary
  - search_wlo_content
  - search_wlo_collections
core_rule: |
  Drei-Stufen-Rettung statt Verweigerung:
  1. `lookup_wlo_vocabulary` für Synonym/Oberbegriff → Retry mit anderem Wort
  2. Filter lockern (Stufe weglassen, breiteres Fach)
  3. Alternativ-Pfad: Sammlung statt Material, Themenseite statt Sammlung
forbidden_phrases:
  - „Leider habe ich nichts gefunden." (alleine, ohne Retry)
  - „Bitte gib mehr Details an" (zurückfragen statt liefern)
when_to_use:
  - M05/M06-Suche ergab 0 oder zu wenige Treffer (< 3)
  - Retry-Eskalations-Pfad nach gescheiterter MCP-Suche
  - Vorheriges Pattern enforced_pattern_id=M12 wegen leerem Such-Resultat
when_not_to_use:
  - Suche hat Treffer geliefert → M05/M06 bleiben
  - Topic fehlt → M03 (nicht M12 als blinde Klärung verwenden)
  - User-Anfrage war nicht such-bezogen → keine M12-Eskalation
trigger_phrases:
  - (intern aktivierter Pfad — kein direkter User-Trigger)
  - Such-Pattern hat empty cards zurückgegeben
discriminators:
  - vs: M06
    rule: M06 vor Such-Versuch. M12 erst NACH leerem Suchergebnis (Eskalation).
    example: "Material zu X → M06. M06 liefert leer → M12-Eskalation."
  - vs: M03
    rule: Such-Treffer leer wegen unbekanntem Begriff → M12 (Synonym-Lookup). Slot fehlt → M03 (Klärung).
    example: "Suche zu Phantasie-Begriff → M12. Suche zu (kein Topic) → M03."
---

# M12 — Null-Treffer-Eskalation

## Wann aktiv
- Vorherige MCP-Suche (M05/M06/M09) lieferte 0 Cards

## Verhalten
- 1 Satz „Zu '[term]' habe ich nichts gefunden — versuche es mit '[synonym]'"
- 1 Retry-Aufruf mit neuem Suchwort
- Bei erneut 0: 2 konkrete Alternativ-Quick-Replies anbieten
- Schluss-Option: Redaktion fragen (Quick-Reply triggert M13)
