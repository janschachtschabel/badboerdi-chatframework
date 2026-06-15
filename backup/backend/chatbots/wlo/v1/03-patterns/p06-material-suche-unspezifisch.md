---
id: P6
label: Material-Suche unspezifisch (Kuratiert-Cascade)
short_purpose: "WANN: User hat ein Thema, aber ohne konkrete Filter oder mit Erkundungs-Sprache ('was habt ihr zu Klima?'). WOFÜR: Cascade — zuerst Themenseiten → bei null Treffer Sammlungen → bei null Treffer Einzelinhalte. Kuratierte Treffer vor algorithmischen."
priority: 500
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["*"]
precondition_slots: ["thema"]
default_tone: sachlich
default_length: mittel
default_detail: standard
response_type: answer
sources: ["mcp"]
tools: ["search_wlo_topic_pages", "search_wlo_collections", "search_wlo_content", "lookup_wlo_vocabulary"]
rag_areas: []
format_primary: cards
format_follow_up: quick_replies
card_text_mode: reference
force_tool_use: true
requires_all_tools: false
---

# P6: Material-Suche unspezifisch (Cascade)

## Kernregel
User hat Thema, aber keine konkrete Filter — er erkundet. Antworte mit
einer **3-Stufen-Cascade**:

1. **Themenseiten** (`search_wlo_topic_pages`) zuerst — wenn es eine
   kuratierte Themenseite zum Thema gibt, ist das die beste Antwort.
2. **Sammlungen** (`search_wlo_collections`) wenn keine Themenseiten —
   redaktionell zusammengestellte Inhalts-Listen.
3. **Einzelinhalte** (`search_wlo_content`) nur als letzte Stufe.

Output ist 3–6 Cards der höchsten erreichten Cascade-Stufe.

## Verhalten
- Cascade wird **vom Tool-Layer** entschieden: wenn Stufe N null
  Treffer hat, automatisch Stufe N+1 versuchen.
- In der Bot-Antwort transparent benennen: „Ich habe dir
  **Themenseiten** zum Thema X herausgesucht" oder „Ich habe **drei
  Sammlungen** dazu gefunden".
- Wenn der User klar Material („Videos", „Arbeitsblätter") nennt →
  P5, nicht P6.
- Wenn auch Stufe 3 null Treffer → System routet zu P16.

## Nicht tun
- KEIN Mischen der Stufen in einer Antwort (verwirrt den User).
- KEINE Lernpfad-Erstellung — das ist P9.
- KEINE Sammlung als Single-Card durchklicken — User soll die Liste
  sehen und selbst wählen.
