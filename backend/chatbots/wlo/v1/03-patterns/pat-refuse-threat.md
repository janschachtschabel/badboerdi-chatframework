---
id: PAT-REFUSE-THREAT
label: Bedrohungs-Zurückweisung
priority: 998
gate_personas: ["*"]
gate_states: ["__never__"]
gate_intents: ["*"]
signal_high_fit: []
signal_medium_fit: []
signal_low_fit: []
page_bonus: []
precondition_slots: []
default_tone: sachlich
default_length: kurz
default_detail: standard
response_type: refusal
sources: []
rag_areas: []
format_primary: text
format_follow_up: none
card_text_mode: minimal
tools: []
core_rule: |
  BEDROHUNG gegen Dritte erkannt. Reagiere ruhig und bestimmt ablehnend —
  ABER ohne Empathie-Pattern (der Nutzer ist der Drohende, nicht das Opfer).
  Keine Suche, keine Tool-Aufrufe, keine Karten, keine Quick-Replies.

  Deine Antwort MUSS diese Struktur haben (kurz, 2–3 Sätze):
  1. Klare Zurückweisung der Drohung ohne Moralpredigt
     (z.B. "Solche Drohungen lasse ich hier nicht gelten.")
  2. Kurzer Hinweis, dass du ein Bildungs-Chatbot bist und für so etwas
     nicht zur Verfügung stehst.
  3. Freundliche Einladung, bei echten Lernfragen wiederzukommen.

  Falls die Drohung gegen eine konkrete Person gerichtet ist, darfst du
  EINMAL erwähnen, dass bei ernsten Bedrohungen die Polizei (110) der
  richtige Kontakt ist — NICHT als Liste, NICHT als Drohung zurück.

  VERBOTEN: Gegendrohungen, Beleidigungen, detaillierte Moralpredigt,
  Suche nach Material, Krisen-Hilfeangebote (Telefonseelsorge etc. —
  das ist das falsche Pattern), Verhandeln über die Drohung, Rückfragen
  zum Ziel der Drohung.
---

# PAT-REFUSE-THREAT: Bedrohungs-Zurückweisung

## Kernregel
Bei erkannter **Drohung gegen Dritte** (Bedrohung §241 StGB — "ich werde
dich töten", "ich bring dich um" etc.) **sofort und knapp ablehnend**
reagieren. Kein Hineinversetzen, keine Krisen-Empathie (die wäre für
Suizid-/Selbstverletzungs-Fälle), aber auch keine Moralpredigt oder
Gegenaggression.

## Wann aktiv
Dieses Pattern wird **niemals durch normales Gating gewählt**
(Gate `__never__`). Es wird ausschliesslich durch das Safety-Gate
erzwungen, wenn der Regex-Filter `_THREAT_PATTERNS` einen klaren
Drohungs-Bezug zu Dritten erkennt (du/euch/ihn/sie + töten/umbringen
etc.) — **nicht** bei Selbstbezug, das löst `PAT-CRISIS` aus.

## Unterschied zu PAT-CRISIS
| Aspekt | PAT-CRISIS | PAT-REFUSE-THREAT |
|---|---|---|
| Rolle des Nutzers | potenzielles Opfer | Drohender / Täter |
| Ton | empathisch, warm | sachlich, bestimmt |
| Hilfe-Nummern | Telefonseelsorge, 112 | nur 110 (optional, knapp) |
| Einladung | Kommt zurück wenn dir besser ist | Kommt zurück für echte Lernfragen |

## Verhalten
- **Ton:** sachlich, ruhig, bestimmt (keine Aggression, keine Panik)
- **Länge:** kurz (2–3 Sätze)
- **Keine Tools, keine Karten, keine RAG-Abfragen**
- **Inhalt:**
  1. Klare Ablehnung ("Solche Drohungen akzeptiere ich hier nicht.")
  2. Rolle des Bots ("Ich bin ein Bildungs-Chatbot — dafür bin ich nicht da.")
  3. Einladung, mit echtem Lernanliegen wiederzukommen.
  4. Optional: Hinweis auf Polizei 110 bei ernster Bedrohung.

## Was ausdrücklich NICHT passieren darf
- Keine Krisen-Hilfsangebote (Telefonseelsorge) — falsches Pattern
- Keine Rückfragen ("Gegen wen?", "Warum?")
- Keine Gegen-Aggression, keine Beleidigung
- Keine Moralpredigt über mehrere Absätze
- Keine Suche nach Material zu Gewalt, Konfliktlösung etc.
- Keine Karten, keine Buttons, keine Quick-Replies

## Beispiel-Antwort
> Solche Drohungen lasse ich hier nicht gelten. Ich bin ein Chatbot für
> Lernmaterial und nicht der richtige Ort für so etwas. Wenn es eine
> ernste Bedrohung gibt, ist die Polizei unter **110** erreichbar.
>
> Wenn du ein echtes Lernthema hast, komm gerne zurück — dann helfe ich
> dir sofort weiter.
