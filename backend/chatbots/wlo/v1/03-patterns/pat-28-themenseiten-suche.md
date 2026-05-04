---
id: PAT-28
label: Themenseiten-Suche
short_purpose: "WANN: User sucht GEZIELT eine Themenseite/Sammlung zu EINEM konkreten Fach oder Thema (INT-W-03a, Singular). WOFÜR: search_wlo_topic_pages mit Query aus thema/fach aufrufen — liefert kuratierte Themenseiten-Cards (mit 🌐-Button) statt einer Fachportal-Übersicht oder roher Material-Liste."
priority: 500
gate_personas: ["*"]
gate_states: ["state-1", "state-4", "state-5", "state-6", "state-7", "state-8"]
gate_intents: ["INT-W-03a"]
signal_high_fit: ["neugierig", "validierend", "ungeduldig", "effizient", "erfahren", "entscheidungsbereit", "vergleichend"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: sachlich
default_length: kurz
default_detail: standard
response_type: cards
sources: ["mcp"]
rag_areas: []
format_primary: cards
format_follow_up: quick_replies
card_text_mode: minimal
tools: ["search_wlo_topic_pages", "search_wlo_collections"]
force_tool_use: true
requires_all_tools: false
core_rule: |
  EIN-SCHRITT-FLOW (Themenseiten-Suche zu KONKRETEM Thema/Fach):
  1. PRIMÄR: ``search_wlo_topic_pages(query: <thema oder fach>, maxResults: 10)``
     — die Query setzt sich zusammen aus ``entities.thema`` (Vorrang) bzw.
     ``entities.fach`` (Fallback). Wenn beide gesetzt sind, kombiniere sie:
     ``query = "<thema> <fach>"`` (z.B. "Bruchrechnung Mathematik").
  2. OPTIONAL als Ergänzung: ``search_wlo_collections(query=<gleicher Wert>,
     maxResults: 5)`` — falls keine Themenseite existiert (search_wlo_topic_pages
     liefert leere Liste), zeige stattdessen die passenden Sammlungen. Die
     Backend-Pipeline dedupliziert automatisch nach nodeId.

  RENDER-SEMANTIK: Die zurückgegebenen Cards rendern automatisch als
  Topic-Page-Cards (mit dem 🌐 „Themenseite öffnen"-Button), wenn
  ``search_wlo_topic_pages`` aufgerufen wurde — das ist der entscheidende
  Unterschied zu PAT-05/PAT-07, die zwar auch Material liefern, aber
  ohne die kuratierte Themenseiten-Variante.

  NEGATIV-ABGRENZUNG:
  - NICHT PAT-26 (Fachportale-Übersicht) — das ist die Plural-Frage „welche
    Fächer gibt es?". Hier hat der User EIN konkretes Fach/Thema genannt.
  - NICHT PAT-27 (Themen-Drilldown) — das ist „Sub-Themen UNTER Fach X
    sehen". Hier sucht der User die Themenseite SELBST, nicht ihre
    Untergliederung.
  - NICHT PAT-05 (Profi-Filter) — das liefert breit Materialien aller Art;
    hier will der User explizit die KURATIERTE Themenseite, nicht eine
    Material-Liste.
---

# PAT-28: Themenseiten-Suche

## Kernregel
User sucht eine **konkrete Themenseite** zu einem Fach oder Thema — also
die kuratierte Einstiegsseite, die WLO-Redaktion zu dem Themengebiet
gepflegt hat. **PFLICHT**: Zuerst `search_wlo_topic_pages` mit der Query
aus `thema`/`fach` aufrufen — das liefert die Topic-Page-Variants
inklusive der Sub-Group-spezifischen URLs (Lehrkraft / Schüler:in /
allgemein), und die Frontend-Card rendert sie korrekt mit dem
„🌐 Themenseite"-Button.

## Wann aktiv
- Intent `INT-W-03a Themenseite entdecken`
- Typische User-Inputs:
  - „Themenseite zu Mathematik"
  - „Ich suche die Themenseite zu Photosynthese"
  - „Hauptseite zu Klimawandel"
  - „Sammlung zu Bruchrechnung"
  - „Wo finde ich was zu Eiszeit?"
  - „Zeig mir die Übersicht zu Goethe"

## Verhalten
- **Pflicht-Reihenfolge**:
  1. `search_wlo_topic_pages(query=<thema|fach|kombiniert>, maxResults=10)`
     — der einzige Tool-Call, der Topic-Page-Cards mit korrektem
     Render-Verhalten produziert.
  2. **Falls Schritt 1 leer ist**: `search_wlo_collections(query=<gleich>,
     maxResults=5)` als Fallback. Im Antworttext kennzeichnen, dass es
     keine eigene Themenseite gibt, dafür aber passende Sammlungen.

### Antworttext-PFLICHT
**Du MUSST mindestens 2 der zurückgelieferten Karten-Titel TEXTUELL
im Antwort-Body erwähnen** — sonst filtert das Backend
(`_filter_cards_used_in_text`) sie raus, und der User sieht eine
„keine Treffer"-Antwort obwohl Cards da sind.

**Bei Themenseiten-Treffer (Schritt 1 lieferte Karten)**:
- 1 einleitender Satz: „Hier sind die Themenseiten zu **{Thema}**: *{Card-1}*, *{Card-2}* …"
- Dann die Cards (Frontend rendert sie mit „🌐 Themenseite"-Button).

**Bei kein-Themenseiten-Treffer (nur Sammlungen aus Schritt 2)**:
- Klare Aussage: „Eine eigene Themenseite zu **{Thema}** gibt es
  gerade nicht."
- Direkt anschließend prominenten Sammlungs-Hinweis: „Aber ich habe
  passende Sammlungen für dich: *{Card-1}* und *{Card-2}* — beide sind
  ein guter Einstieg, weil {kurze inhaltliche Begründung}."
- KEINE zaghafte Frage „möchten Sie Sammlungen sehen?" — die Cards
  WERDEN gezeigt, der Bot soll sie aktiv vorstellen, nicht
  abfragen. Frage am Ende ist OK als Folge-Vorschlag, aber nicht als
  einziger Inhalt.
- Quick-Replies: „Sammlung *{Card-1}* öffnen", „Material zu {Thema}
  zeigen" → INT-W-03b, „Anderes Thema".

**Bei kein Treffer überhaupt** (sehr selten):
- Dann ehrlich sagen, plus ein konkretes Material-Such-Angebot
  (degradiert auf INT-W-03b / PAT-05). NICHT einfach „nichts
  gefunden" und Schluss.

- Quick-Replies (Standard, wenn Cards da): 2–3 Drilldown-Optionen
  („Bereiche unter Mathematik" → INT-W-14, „Konkrete Materialien zeigen"
  → INT-W-03b).

## Folge-Aktion
- Klick auf die Themenseiten-Card → externe Navigation zur kuratierten Seite.
- Klick auf „📋 Inhalte" auf einer Sammlungs-Card → INT-W-14 (Drilldown)
  oder browse_collection (Files).
- Klick auf einen Quick-Reply → entsprechender Folge-Intent.

## Nicht tun
- KEIN `get_subject_portals` — das ist PAT-26 (Plural, alle Fächer). Hier
  hat der User EIN konkretes Anliegen.
- KEIN `browse_collection_tree` — das ist PAT-27 (Drilldown unter EINEM
  Fach). Hier sucht der User die Themenseite, nicht ihre Sub-Struktur.
- Keine Material-Bombardement-Suche mit `search_wlo_content` — das wäre
  INT-W-03b (Material-Suche), nicht INT-W-03a.
- Wenn `search_wlo_topic_pages` leer zurückkommt: NICHT einfach behaupten
  „es gibt nichts" — Fallback auf `search_wlo_collections` mit gleichem
  Query, damit der User wenigstens eine Sammlung als Einstieg bekommt.
