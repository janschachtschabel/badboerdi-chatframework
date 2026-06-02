---
id: PAT-28
label: Themenseiten-Suche
short_purpose: "WANN: User sucht GEZIELT eine Themenseite/Sammlung zu EINEM konkreten Fach oder Thema (INT-W-03, Singular). WOFÜR: search_wlo_topic_pages mit Query aus thema/fach aufrufen — liefert kuratierte Themenseiten-Cards (mit 🌐-Button) statt einer Fachportal-Übersicht oder roher Material-Liste."
priority: 500
gate_personas: ["*"]
gate_states: ["state-1", "state-4", "state-5", "state-6", "state-7", "state-8"]
gate_intents: ["INT-W-03"]
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
- Intent `INT-W-03 Themenseite entdecken`
- Typische User-Inputs:
  - „Themenseite zu Mathematik"
  - „Ich suche die Themenseite zu Photosynthese"
  - „Hauptseite zu Klimawandel"
  - „Sammlung zu Bruchrechnung"
  - „Wo finde ich was zu Eiszeit?"
  - „Zeig mir die Übersicht zu Goethe"

## Verhalten

### Slot-Vor-Check (Welle C Sprint 6 — kritisch)
**Bevor du irgendein Tool aufrufst**: Prüfe, ob ``entities.thema`` ODER
``entities.fach`` gefüllt ist. Wenn BEIDE leer sind:
- Rufe KEIN Tool auf (leere Query → unscharfe oder leere Treffer)
- Antworte direkt: „Zu welchem Thema oder Fach soll ich die
  Themenseite zeigen?"
- Quick-Replies: 3 plausible Themen-Beispiele („Bruchrechnung",
  „Klimawandel", „Photosynthese") + „Anderes Thema eingeben"

Das Pre-Route-System (siehe ``rule_topic_switch_needs_clarification`` in
``routing-rules.yaml``) fängt den ``turn_type=topic_switch``-Fall vor
diesem Pattern schon ab, aber Welle C Sprint 6 zeigt: bei
Reguläranfragen kann ``entities.thema`` trotzdem leer landen
(LLM-Klassifikator hat es nicht extrahiert). Dann gilt der Pre-Check
hier.

### Tool-Aufruf-Pflicht-Reihenfolge (wenn Slots gefüllt)
  1. `search_wlo_topic_pages(query=<thema|fach|kombiniert>, maxResults=10)`
     — der einzige Tool-Call, der Topic-Page-Cards mit korrektem
     Render-Verhalten produziert.
  2. **Falls Schritt 1 leer ist**: `search_wlo_collections(query=<gleich>,
     maxResults=5)` als Fallback. Im Antworttext kennzeichnen, dass es
     keine eigene Themenseite gibt, dafür aber passende Sammlungen.

### Folge-Filter respektieren (Welle C Sprint 6)
Wenn der User in einem Folge-Turn einen Medientyp-Filter eingrenzt
(„nur Videos", „nur Audio", „nur Arbeitsblätter") und
``entities.medientyp`` gesetzt ist, **soll diese Antwort KEINE
Themenseiten-/Sammlungs-Cards mehr ausspielen**. Stattdessen
übergibt die Engine an PAT-07 / PAT-05 (Einzelinhalts-Suche) — das
Frontend filtert Cards ohne passenden Medientyp raus, sonst sieht
der User „mehr vom alten" und denkt der Filter ignoriert ihn.

### Antworttext-PFLICHT
**Du MUSST mindestens 2 der zurückgelieferten Karten-Titel TEXTUELL
im Antwort-Body erwähnen** — sonst filtert das Backend
(`_filter_cards_used_in_text`) sie raus, und der User sieht eine
„keine Treffer"-Antwort obwohl Cards da sind.

**Bei Themenseiten-Treffer (Schritt 1 lieferte Karten)** — der NORMALFALL:
- **Erster Satz MUSS direkt liefern**, ohne Rückfrage davor:
  „Hier ist die Themenseite zu **{Thema}**: *{Card-1-Titel}* — sie
  bündelt {1 Satz: was die Themenseite abdeckt}."
- Wenn mehr als 1 Card: zweiter Satz mit *{Card-2-Titel}* und
  Differenzierung.
- Dann die Cards (Frontend rendert sie mit „🌐 Themenseite"-Button).
- **NIE als ersten Satz**: „Für welche Bildungsstufe?" / „Suchen Sie
  Lehrkraft- oder Schüler-Variante?" / „Kann ich mehr Details
  bekommen?" — das ist ein hartes Anti-Pattern. Erst LIEFERN, dann
  am Ende OPTIONAL eine präzise Folge-Frage anbieten.

**Bei kein-Themenseiten-Treffer (nur Sammlungen aus Schritt 2)**:
- **Erster Satz MUSS** Klare Aussage: „Eine eigene Themenseite zu
  **{Thema}** habe ich gerade nicht — passende **Sammlung** ist
  aber: *{Card-1-Titel}*."
- Zweiter Satz: warum diese Sammlung ein guter Einstieg ist + ggf.
  Card-2.
- KEINE zaghafte Frage „möchten Sie Sammlungen sehen?" — die Cards
  WERDEN gezeigt, der Bot soll sie aktiv vorstellen, nicht
  abfragen.
- KEIN Verzicht auf den Hinweis „keine eigene Themenseite" — die
  Eval-Judge bestraft, wenn der Bot Sammlungen als Themenseiten
  präsentiert, ohne den Unterschied transparent zu machen.
- Quick-Replies: „Sammlung *{Card-1}* öffnen", „Material zu {Thema}
  zeigen" → INT-W-03, „Anderes Thema".

**Bei kein Treffer überhaupt** (sehr selten):
- Dann ehrlich sagen, plus ein konkretes Material-Such-Angebot
  (degradiert auf INT-W-03 / PAT-05). NICHT einfach „nichts
  gefunden" und Schluss.

- Quick-Replies (Standard, wenn Cards da): 2–3 Drilldown-Optionen
  („Bereiche unter Mathematik" → INT-W-14, „Konkrete Materialien zeigen"
  → INT-W-03).

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
  ein Einzelinhalt-Modus; hier ist die KURATIERTE Themenseite das Ziel.
- Wenn `search_wlo_topic_pages` leer zurückkommt: NICHT einfach behaupten
  „es gibt nichts" — Fallback auf `search_wlo_collections` mit gleichem
  Query, damit der User wenigstens eine Sammlung als Einstieg bekommt.
