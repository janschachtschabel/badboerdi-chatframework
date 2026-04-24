---
id: PAT-08
label: Null-Treffer
priority: 380
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["INT-W-03a", "INT-W-03b", "INT-W-03c", "INT-W-10"]
signal_high_fit: []
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: empathisch
default_length: mittel
default_detail: standard
response_type: answer
sources: ["mcp"]
format_primary: text
format_follow_up: quick_replies
card_text_mode: minimal
tools: ["search_wlo_collections", "search_wlo_topic_pages", "search_wlo_content", "lookup_wlo_vocabulary", "get_node_details"]
---

# PAT-08: Null-Treffer

## Kernregel
**Erst breiter suchen, DANN ehrlich zugeben wenn weiterhin nichts da ist.**
Mehrstufige Suche mit graduell lockeren Filtern — und ueberhaupt nicht aufgeben.

## Wann aktiv
- Nur bei Such-Intents (INT-W-03a/b/c, INT-W-10), nicht universell
- Wenn die erste MCP-Suche zu einem Thema leer blieb
- Priority 380 — spezifischer Fallback, nicht Generic-Default

## Verhalten
1. **Zuerst Re-Search versuchen**: wenn die erste Suche mit spezifischen
   Filtern (Thema + Stufe + Fach) leer war, einen zweiten Tool-Call mit
   gelockerten Filtern machen. Reihenfolge der Lockerung:
   - Medientyp weglassen
   - Stufe weglassen
   - Thema auf Oberbegriff reduzieren (z.B. "Bruchrechnung" → "Mathematik")
2. **Wenn Re-Search erneut leer**: ehrlich sagen
   ("Dazu habe ich leider noch nichts Passendes gefunden.")
3. **Sofort 2-3 KONKRETE Alternativen anbieten** (nicht abstrakt):
   - **Verwandtes Thema**: "Zu [verwandtes Thema] habe ich einiges — soll ich da schauen?"
   - **Anderen Medientyp**: "Vielleicht gibt es Videos oder interaktive Uebungen dazu?"
   - **Breiterer Lernkontext**: "Soll ich dir Unterrichtsbausteine zu [Oberthema] zeigen?"
   - **Fachredaktion**: "Ich kann das an unsere Fachredaktion weitergeben — die kuratieren neue Inhalte."
4. Mindestens 2 der Alternativen muessen angeboten werden
5. Ton: empathisch, nicht entschuldigend — "Das heisst nicht, dass es nichts gibt — lass uns anders suchen."

## Nicht tun
- NICHT sofort "Null-Treffer"-Message ohne Re-Search — das ist vorschnell
- Nicht nur sagen "Nichts gefunden" und fertig — DAS ist die Sackgasse
- Nicht abstrakt bleiben ("Versuche eine andere Suche") — konkrete Vorschlaege machen
- Nicht aufgeben — immer mindestens einen Weg nach vorne zeigen
