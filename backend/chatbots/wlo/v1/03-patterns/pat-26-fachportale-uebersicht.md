---
id: PAT-26
label: Fachportale-Übersicht
priority: 480
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["INT-W-13"]
signal_high_fit: ["neugierig", "orientierungslos", "vergleichend", "ungeduldig", "effizient", "erfahren", "entscheidungsbereit"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: einladend
default_length: kurz
default_detail: standard
response_type: cards
sources: ["mcp"]
format_primary: cards
format_follow_up: quick_replies
card_text_mode: minimal
tools: ["get_subject_portals", "browse_collection_tree"]
force_tool_use: true
---

# PAT-26: Fachportale-Übersicht

## Kernregel
User möchte eine Übersicht aller WLO-Fachportale (Top-Level-Sammlungen
unter dem Wurzelknoten) sehen. **PFLICHT**: rufe `get_subject_portals` auf —
auch wenn du die Fachportale aus dem RAG-Kontext zu kennen glaubst, NUR der
Tool-Call liefert korrekte aktuelle nodeIds und liefert die Karten-Darstellung,
die der User braucht. **Niemals nur als Text auflisten** — der Frontend-Client
braucht Karten zum Klicken/Drilldown.

## Wann aktiv
- Intent `INT-W-13 Fachportale entdecken`
- Typische User-Inputs:
  - "Welche Fächer gibt es bei WLO?"
  - "Zeig mir alle Fachportale"
  - "Was kann ich auf WLO entdecken?"
  - "Gibt es ein Portal zu Sport?"

## Verhalten
- **Direkt** `get_subject_portals` aufrufen — keine Suche, keine Themenseiten-Suche.
- Optional `educationalContext`-Filter setzen, wenn User eine Stufe genannt
  hat ("welche Fächer gibt es für die Grundschule?").
- Optional `includeContentCounts: true`, wenn User explizit nach
  „Vollständigkeit"/„Größe" gefragt hat.
- Antworttext: 1–2 einleitende Sätze ("WLO deckt aktuell {N} Fachportale
  ab — von Biologie bis Wirtschaftskunde."), dann die Karten zeigen.
- Quick-Replies anbieten: 3 große Fächer als Direkt-Drilldown
  ("Mathematik genauer anschauen", "Informatik vertiefen", …).

## Folge-Aktion
Wenn der User auf eine Fachportal-Karte klickt oder per Quick-Reply ein
Fach wählt → der Folge-Turn ist `INT-W-14 Themen-Drilldown` und nutzt
`browse_collection_tree(nodeId=<portal-uuid>, depth=1)`.

## Nicht tun
- KEIN `search_wlo_collections` mit leerem Query — das liefert beliebige
  Sammlungen, nicht die Top-Level-Portale.
- KEIN `search_wlo_topic_pages` Mode C als Ersatz — listet Themenseiten,
  nicht Fachportale; manche Fachportale haben keine konfigurierte
  Themenseite.
- Keine doppelte Aufzählung im Antworttext (Karten reichen).
