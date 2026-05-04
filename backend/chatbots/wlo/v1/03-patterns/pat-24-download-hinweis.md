---
id: PAT-24
label: Download-Hinweis
short_purpose: "WANN: User will ein konkretes Material runterladen oder öffnen (INT-W-07). WOFÜR: Material via search_wlo_content suchen + Material-Karte mit Original-URL anbieten — KEINE reine Text-Antwort."
priority: 545
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["INT-W-07"]
signal_high_fit: ["zielgerichtet", "erfahren", "ungeduldig", "effizient", "entscheidungsbereit"]
signal_medium_fit: ["unsicher"]
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: sachlich
default_length: kurz
default_detail: niedrig
response_type: cards
sources: ["mcp", "llm"]
format_primary: cards
format_follow_up: quick_replies
card_text_mode: highlight
tools: ["search_wlo_content", "search_wlo_collections", "query_knowledge", "get_node_details"]
force_tool_use: true
---

# PAT-24: Download-Hinweis

## Kernregel
**Tool-First**: bei jedem Download-Anliegen ZUERST `search_wlo_content`
(oder `search_wlo_collections` bei Sammlungs-Bezug) aufrufen mit dem
Topic aus der User-Frage, dann die Material-Karte präsentieren — die
Karte liefert den Original-URL, das ist der einzige saubere
Download-Weg auf WLO. Eine reine Text-Antwort „direkt herunterladen
geht im Chat nicht" ohne Karte ist ein Anti-Pattern und löst das
Anliegen nicht.

## Wann aktiv
- Intent INT-W-07 (Material herunterladen)
- Beispiele:
  - „Wie lade ich das Arbeitsblatt zur Bruchrechnung runter?"
  - „Direktlink zum OER-Material zur Schulentwicklung bitte"
  - „Wo ist der Download-Button für das Pressekit?"
  - „Ist das als PDF verfügbar?"

## Verhalten

### Schritt 1: Material identifizieren + suchen
Extrahiere aus der User-Frage das Thema/Material:
- „Arbeitsblatt zur Bruchrechnung" → query=„Bruchrechnung Arbeitsblatt"
- „OER-Material zur Schulentwicklung" → query=„Schulentwicklung OER"
- „Pressekit" / „Presse-Material" → KEIN search_wlo_content (existiert
  als WLO-Material nicht) → STATTDESSEN: query_knowledge(area=„WirLernenOnline"
  oder „WissenLebtOnline") für Pressekontakt-Info

Tool-Reihenfolge:
1. **Bei konkretem Bildungsthema**: `search_wlo_content(query=…, maxResults=5)`
   → liefert Material-Cards mit Original-URLs.
2. **Wenn Sammlung gewünscht**: `search_wlo_collections(query=…, maxResults=3)`
   → liefert Sammlungen, die der User dann öffnen kann.
3. **Bei Plattform-Material (Pressekit, Logo, Handbuch)**:
   `query_knowledge(area=„WissenLebtOnline" / „WirLernenOnline")`
   für Kontaktinfo / Hinweis auf Pressekontakt-Seite.

### Schritt 2: Antwort
- **Wenn Material gefunden (Cards)**: 1–2 einleitende Sätze plus die
  Karte. Im Text das Material **mit Titel** erwähnen (sonst filtert
  ``_filter_cards_used_in_text`` die Karte raus). Beispiel:
  „Hier sind die passenden Materialien zu **{Thema}** — die Karte
  unten verlinkt direkt auf die Original-Seite mit dem Download-Button:
  *{Card-Titel-1}* und *{Card-Titel-2}*."
- **Wenn kein konkretes Material auffindbar (Pressekit etc.)**:
  Kontaktweg nennen, plus dem User eine konkrete Such-Quick-Reply
  anbieten („Nach OER zu Schulentwicklung suchen").
- **Lizenz-Hinweis** (immer, kurz): „Auf der Zielseite steht die
  Lizenz — CC, Public Domain oder proprietär. Bitte beachten, wenn du
  das Material weiterverwendest."

### Schritt 3: Quick-Replies
Drei mit Bezug zum aktuellen Anliegen:
- „Anderes Material suchen"
- „Was bedeutet CC BY?"
- „Im Unterricht/Beruf nutzen?"

## Nicht tun
- KEINE reine Text-Antwort der Form „Direkt herunterladen geht im Chat
  nicht" ohne vorhergehenden Tool-Call. Das ist ein Anti-Pattern
  dieses Patterns: der User sucht das Material, nicht eine Erklärung
  zum Bot-UX.
- Keine Aufzählung des Materials nur im Text — IMMER die Karte
  rendern, weil sie den klickbaren Link liefert.
- Bei Pressekit-/Logo-/Werbematerial-Anfragen: NICHT einfach behaupten
  „kenne ich nicht", sondern Kontakt aus query_knowledge holen
  (Pressekontakt steht in WissenLebtOnline-RAG).

## Hinweis
Aktiv wird ein technischer Download (Datei-Stream) im Widget nicht
unterstützt — das Pattern führt zur Original-Quelle, dort wird der
Download durchgeführt.
