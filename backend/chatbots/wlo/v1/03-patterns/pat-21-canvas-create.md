---
id: PAT-21
label: Canvas-Create
priority: 470
gate_personas: ["*"]
gate_states: ["state-5", "state-6", "state-8", "state-12"]
gate_intents: ["INT-W-11"]
signal_high_fit: ["zielgerichtet", "erfahren"]
signal_medium_fit: ["unsicher", "neugierig"]
signal_low_fit: []
page_bonus: []
precondition_slots: ["thema", "material_typ"]
default_tone: sachlich
default_length: mittel
default_detail: standard
response_type: answer
sources: ["llm"]
format_primary: text
format_follow_up: quick_replies
card_text_mode: none
tools: ["query_knowledge"]
---

# PAT-21: Canvas-Create

## Kernregel
Neues Bildungsmaterial wird KI-generiert und im Canvas-Bereich des Widgets präsentiert.
Format ist strukturiertes Markdown, passend zum gewählten Material-Typ.

## Wann aktiv
- Nutzer:in äußert expliziten Erstellungswunsch (INT-W-11)
- Thema UND Material-Typ sind bekannt (sonst Degradation auf Typ-Auswahl)

## Verhalten
- LLM erzeugt Markdown-Inhalt via `canvas_service.generate_canvas_content()`
- Response-Text für den Chat bleibt kurz (1-2 Sätze: "Ich habe ein Arbeitsblatt zum Thema X erstellt. Du siehst es im Canvas rechts. Sag mir, was ich ändern soll.")
- Der eigentliche Inhalt wandert ins `page_action.payload.markdown` mit `action: "canvas_open"`
- Bei fehlendem Material-Typ: Quick-Replies mit 12 Typen anbieten (Degradation)
- Follow-up: "Möchtest du noch Lösungen ergänzen?" / "Soll ich es einfacher formulieren?" / "Zusätzliche Übungen?"

## Material-Typen (unterstützt)

### Didaktische Typen (primär für LK / SuS / Eltern)
- 🤖 Automatisch (KI wählt passenden Typ)
- 📝 Arbeitsblatt
- 📄 Infoblatt
- 📊 Präsentation
- ❓ Quiz/Test
- ✅ Checkliste
- 📖 Glossar
- 🗺️ Strukturübersicht
- ✏️ Übungsaufgaben
- 📚 Lerngeschichte
- 🔬 Versuchsanleitung
- 💬 Diskussionskarten
- 🎭 Rollenspielkarten

### Analytische Typen (primär für Verwaltung / Politik / Presse / Beratung / Redaktion)
- 📊 Bericht
- 📈 Factsheet
- 🪪 Projektsteckbrief
- 📰 Pressemitteilung
- ⚖️ Vergleich

Die Reihenfolge in den Quick-Reply-Chips wird pro Persona sortiert
(`canvas_service.material_type_quick_replies_for_persona()`): analytische
Personas sehen analytische Typen zuerst, alle anderen die didaktischen.
