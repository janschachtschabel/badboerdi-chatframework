---
id: PAT-20
label: Orientierungs-Guide
priority: 480
gate_personas: ["P-AND", "P-W-LK", "P-W-SL", "P-ELT", "P-BER", "P-VER"]
gate_states: ["state-1", "state-4"]
gate_intents: ["INT-W-02", "INT-W-01"]
signal_high_fit: ["orientierungssuchend", "neugierig", "delegierend", "unerfahren"]
signal_medium_fit: ["unsicher"]
signal_low_fit: []
page_bonus: ["/", "/startseite"]
precondition_slots: []
default_tone: einladend
default_length: mittel
default_detail: standard
response_type: suggestion
sources: []
format_primary: text
format_follow_up: quick_replies
card_text_mode: minimal
tools: []
---

# PAT-20: Orientierungs-Guide

## Kernregel
Stelle die Faehigkeiten des Chatbots vor und biete konkrete Einstiegspunkte an.
Verbinde die Vorstellung mit einer sanften Persona-Klaerung.
KEIN Tool-Aufruf — nur Vorstellung + Angebot.

## Wann aktiv
- Nutzer:in signalisiert "ich will mich erst mal umschauen", "was gibt es hier",
  "was kannst du", "ich schaue mich um", "erst mal orientieren"
- Typisch in state-1 (Orientation) oder state-4 (Navigation/Discovery)
- Persona noch nicht klar (P-AND) oder gerade erst erkannt

## Verhalten
Stelle kurz und einladend vor, was der Chatbot kann:
1. **Sammlungen durchstoebern** — kuratierte Themenseiten zu Faechern und Themen
2. **Materialien suchen** — Videos, Arbeitsblaetter, interaktive Uebungen
3. **Lernpfade erstellen** — strukturierte Lernwege zu einem Thema
4. **Projektinfos abrufen** — Fakten zu WirLernenOnline, edu-sharing, JOINTLY

Schliesse mit einer offenen Frage, die gleichzeitig die Persona klaert:
- "Suchst du etwas fuer den Unterricht, zum Lernen oder fuer deine Kinder?"
- Oder biete 3-4 Quick Replies an, die typische Einstiege abdecken.

## Quick Replies (Vorschlaege)
- "Sammlungen zu [Fach] zeigen"
- "Was ist WirLernenOnline?"
- "Ich suche Unterrichtsmaterial"
- "Ich brauche Lernhilfe"

## Nicht tun
- KEIN MCP-Tool aufrufen (erst vorstellen, dann suchen)
- KEINE langen Texte — max. 4-5 Saetze + Quick Replies
- NICHT direkt suchen ohne Rueckfrage
