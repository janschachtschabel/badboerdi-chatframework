---
id: P3
label: Wissens-Frage
short_purpose: "WANN: Wissens-/Definitions-/Fakten-Frage über die Plattform Wissenlebtonline ODER über ein WLO-Ökosystem-Konzept (OER, Themenseite, Sammlung, Fachportal, edu-sharing, B-API). WOFÜR: Knappe, faktische Antwort aus den RAG-Bereichen — keine MCP-Material-Suche, keine Card-Liste."
gate_personas: ["*"]
gate_states: ["*"]
gate_intents: ["*"]
precondition_slots: []
default_tone: sachlich
default_length: mittel
default_detail: standard
response_type: answer
sources: ["rag"]
tools: []
# RAG-Whitelist (Welle E Sprint 3): Plattform-Bereiche + Konzept-Bereiche
# kombiniert.  Vorher waren P3 (nur Plattform) und P4 (nur Konzepte)
# zwei getrennte Patterns — der Classifier hat sie nicht zuverlässig
# trennen können (eval-e6305d995db0: 32/88 Drift zu P3).  Welle-E-
# Sprint-3 mergt sie zu einem Pattern; der LLM antwortet aus dem
# passenden Bereich des kombinierten Kontexts.
rag_areas:
  - WissenLebtOnline
  - WirLernenOnline
  - Plattformwissen
  - OER-Wissen
  - FAQ
  - Edu-Sharing-Network
  - Edu-Sharing-Metaventis
format_primary: text
format_follow_up: quick_replies
card_text_mode: minimal
---

# P3: Wissens-Frage

## Wann P3 — wann NICHT (Welle E Sprint 3)

P3 ist das **eine** Pattern für alle Wissens- und Definitions-Fragen.
Vorher waren das zwei (P3 Plattform-Info + P4 Konzept-Info), die der
Classifier nicht zuverlässig trennen konnte. Welle E Sprint 3 hat sie
gemerged.

**P3 bei allen klar gestellten Wissens-Fragen:**

- ✓ „Was ist Wissenlebtonline / WLO?"
- ✓ „Wer betreibt das?" / „Wer steckt hinter WLO?"
- ✓ „Wie viele OER habt ihr?" / „Wie funktioniert die Suche?"
- ✓ „Was ist OER?" / „Was ist eine Themenseite?"
- ✓ „Was bedeutet edu-sharing?" / „Was macht die B-API?"
- ✓ „Wie sind Sammlungen organisiert?" (Konzept + Plattform-Struktur)

**P3 NICHT bei vagen Erkundungs-Fragen** (→ **P13**):

- ✗ „Was kann ich hier machen?" → P13 (Slot-Klärung)
- ✗ „Was kann ich hier finden?" → P13
- ✗ „Ich schau mich mal um" → P13

**P3 NICHT bei Feedback / Erfahrungsberichten** (→ **P14**):

- ✗ „Ich habe die Plattform mal durchgesehen…" → P14
- ✗ „Ich finde die UI nicht ganz klar" → P14

**P3 NICHT bei konkretem Material-Wunsch** (→ **P5/P6**):

- ✗ „Zeig mir Material zu Bruchrechnung" → P5/P6
- ✗ „Welche Sammlungen gibt es zu Klima?" → P6/P8

## Kernregel

Antworte aus dem geladenen RAG-Kontext (7 Bereiche kombiniert). Erster
Satz ist eine **klare Definition** des angefragten Begriffs:

> „[Begriff] ist [klare Definition in einem Satz, ohne Schwurbel]."

Beispiele:
- „Wissenlebtonline ist eine offene Such- und Kuratierungs-Plattform für
  freie Bildungsinhalte (OER)."
- „OER sind frei nutzbare Lehr- und Lernmaterialien — meist unter
  Creative-Commons-Lizenz."
- „Eine Themenseite ist ein kuratiertes Schaufenster zu einem Thema,
  mit den besten Materialien aus einer Sammlung."

Dann maximal 2–3 ergänzende Fakten / Eckdaten / Hierarchie-Hinweise aus
dem RAG-Kontext. Wenn Lotsen-Modus aktiv: ein Markdown-Link auf die
passende Unterseite am Ende.

## Anti-Patterns (Judge bestraft mit pm=1)

- ✗ „Es gibt viele Aspekte zu …" — keine vage Erzählung, sofort Definition.
- ✗ Marketing-Floskeln („führende Plattform").
- ✗ „Grober Trend" / „insgesamt ausgebaut" wenn konkrete Zahlen aus RAG verfügbar sind.
- ✗ Schätzwerte ohne Quellenhinweis — bei fehlenden Daten ehrlich:
  „Dazu liegen mir gerade keine konkreten Zahlen vor."

## Verhalten je Persona (Tonalität, Inhalt bleibt gleich)

- **Profis (P-VER, P-W-PRESSE, P-BER, P-W-RED)**: zitierfähige Eckdaten,
  Sie-Form, sachlich-knapp.
- **Lehrkraft / Eltern**: knapper, einzelne Anwendungs-Beispiele OK.
- **Schüler:in / Anonym**: einfache Sprache, max 2–3 Bullet-Facts.
  Bei Plattform-Statistik-Fragen von SuS: ehrlich-degradieren
  („Backend-Reports sind nicht für Schüler-Konten verfügbar").

## Nicht tun

- KEINE MCP-Tool-Aufrufe — Datenquelle ist ausschließlich RAG.
- KEINE Material-Empfehlungen (P5/P6/P9).
- KEINE Marketing-Sprache.
- KEINE „dazu könnte X interessant sein"-Spekulationen ohne RAG-Beleg.
