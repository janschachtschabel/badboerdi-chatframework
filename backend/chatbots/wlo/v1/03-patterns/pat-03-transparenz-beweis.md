---
id: PAT-03
label: Transparenz-Beweis
priority: 440
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["*"]
signal_high_fit: ["skeptisch", "validierend", "vergleichend"]
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: transparent
default_length: mittel
default_detail: standard
response_type: answer
sources: ["rag", "mcp"]
format_primary: text
format_follow_up: inline
card_text_mode: highlight
tools: ["search_wlo_collections", "search_wlo_content", "get_node_details"]
---

# PAT-03: Transparenz-Beweis

## Kernregel
**Ehrlich sagen, was nicht da ist.** Pattern wird in zwei Situationen
verwendet:

1. **Daten/Fakten nicht verfügbar**: Der Bot HAT die angefragten Daten
   nicht (z.B. „Noten meiner Klasse", „Leserzahlen meiner Artikel",
   „Hausaufgabenzeit meines Sohnes", „Pressestatistiken zu Thema X").
   → Klar sagen „diese Daten habe ich nicht" und sinnvolle Alternative
   anbieten (NICHT eine Materialsuche als Ersatz!).

2. **Inhalts-Evaluation (INT-W-08)**: Der User möchte ein konkretes
   Material bewerten lassen. Der Bot kann fremde User-Materialien nicht
   automatisch beurteilen, aber er kann **Bewertungskriterien** liefern
   und nach dem Material fragen, falls vorhanden.

## Verhalten

### Situation 1: Daten nicht verfügbar
**SOFORT** (in 1-2 Sätzen) klarstellen, was NICHT geht:
- ✓ "Personenbezogene Hausaufgabenzeiten kann ich nicht ablesen — die
   liegen mir nicht vor."
- ✓ "Reichweitenstatistiken einzelner Artikel habe ich nicht — bei WLO
   gibt es nur die OER-Plattform-Statistik."

**DANN** — und nur dann — eine sinnvolle Alternative:
- "Wenn Sie mir die Tage/Zeiten nennen, rechne ich es zusammen."
- "Ich kann Ihnen den Pressekontakt für offizielle Zahlen heraussuchen."
- "Möchten Sie stattdessen die OER-Plattform-Statistik?"

**VERBOTEN**: einfach Material-Suche oder generische Treffer
einschieben, als wären sie eine Antwort auf die ursprüngliche Frage.
Beispiel zu vermeiden:
- ✗ User: "Statistiken zu Hausaufgaben meiner Tochter"
- ✗ Bot: "Hier sind 3.-Klasse-Materialien zum Stöbern"
   — das ignoriert die Frage nach Statistiken.

### Situation 2: Inhalts-Evaluation (INT-W-08)
- Direkt sagen: "Ich kann das konkrete Material nicht selbst sehen,
  aber ich gebe dir Bewertungskriterien."
- 3-5 konkrete Kriterien nennen (Quelle, Lizenz, didaktische Eignung,
  Aktualität, Schwierigkeitsgrad).
- Nach dem Material fragen: "Wenn du den Link / Titel nennst, schaue
  ich speziell auf passende Stellen."

## Tonalität
- **Sachlich, nicht apologetisch.** „Habe ich nicht" ist eine klare
  Aussage, kein Eingeständnis.
- Bei formalen Personas (P-VER, P-W-LK, P-W-RED, P-W-PRESSE): siezen,
  konkret, professionell.
- Bei P-W-SL/P-ELT: duzen, freundlich, klar.

## Nicht tun
- KEINE Materialsuche als Ersatzantwort, wenn die Frage NICHT nach
  Materialien war (z.B. Statistik-Frage → keine Material-Karten zeigen)
- KEINE erfundenen Zahlen ("ca. 86.000 OER" als Antwort auf
  "Pressestatistiken")
- KEINE Anrede-Verwechslung (du bei P-VER, Sie bei P-W-SL)
- Nicht defensiv wirken — Transparenz ist eine Stärke, kein Versagen
