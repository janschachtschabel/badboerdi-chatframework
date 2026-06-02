---
id: M04
label: Wissens-Antwort
short_purpose: 'Definitions-/Konzept-/Faktenfrage aus RAG. PFLICHT: 2-4 Sätze, KEINE Material-Suche.'
priority: 520
default_tone: sachlich
default_length: kurz
response_type: answer
output_mode: knowledge
sources:
  - rag
rag_areas:
  - wlo-plattform-wissen
  - domain-rules
core_rule: |
  2–4 Sätze ODER 3–5-Bullet-Liste aus RAG. Keine MCP-Suche, keine
  Card-Liste, keine Such-CTA.
forbidden_phrases:
  - „Für [X] schau in die Suche unten" (kein Such-Übergang)
  - MCP-Tool-Calls
  - „Soll ich Material zu X suchen?" (= M06-Verhalten)
  - Marketing-Sprech („Eine wunderbare Plattform")
when_to_use:
  - Intent I02 (Wissensfrage) zu Bildungs-/Plattform-/OER-Themen
  - User stellt Was-/Wie-/Wer-/Warum-Frage ohne Material-Wunsch
  - Lerner fragt nach Erklärung eines Konzepts („Ich kapiere X nicht")
  - Faktenfrage die aus RAG-Wissen beantwortbar ist
when_not_to_use:
  - User möchte Material/Inhalte → M06 (Suche) oder M10 (KI-Create)
  - Frage AUSSERHALB Bildungsdomäne (Aktienkurse / Rezepte) → M12 oder M15-Redirect
  - User stellt Bot-Bedienungs-Frage („Wie kann ich Feedback geben?") → M14
  - Domain-Out mit harter Refusal nötig → M02
trigger_phrases:
  - Was ist X
  - Wie funktioniert Y
  - Wer hat Z entwickelt
  - Warum ist X wichtig
  - Was bedeutet OER
  - Ich kapiere X nicht (Lerner-Frage, kein Material-Wunsch)
discriminators:
  - vs: M10
    rule: Was-/Wie-Frage ohne Create-Verb → M04. Create-Verb + Material-Typ → M10.
    example: "Was ist Photosynthese? → M04. Erstell ein Quiz zu Photosynthese → M10."
  - vs: M06
    rule: Wissens-Frage (Bot erklärt selbst) → M04. Material-Wunsch (Bot sucht) → M06.
    example: "Was ist Bruchrechnung? → M04. Material zu Bruchrechnung → M06."
  - vs: M14
    rule: Wissensfrage zur Welt/Plattform → M04. Bot-Bedienungs-/Feedback-Frage → M14.
    example: "Wie funktioniert OER? → M04. Wie kann ich Feedback geben? → M14."
---

# M04 — Wissens-Antwort

## Pflicht-Antwort-Schema

Schritt 1 — RAG-Inhalt aus `wlo-plattform-wissen` + `domain-rules`
abrufen.

Schritt 2 — Antwort-Form:
- **Definitionsfrage** („Was ist OER?"): 2–3 Sätze, einfach, **ohne**
  Such-Übergang
- **Statistik-Frage** (z.B. „Wie viele OER"): Bullet-Liste mit
  Zahlen + Stand-Datum + Quellen-Link
- **Plattform-Konzept** („Was ist eine Themenseite?"): 2–4 Sätze
  mit konkretem URL-Beispiel

Schritt 3 — **PFLICHT-Link** auf relevante WLO-Unter-Seite (siehe
RAG-Frontmatter `**URL**: …`).

Schritt 4 — Bei Bewertungs-Frage zu konkretem Material: Bewertungs-
Kriterien (Lizenz / Stufe / Quelle) als Bullet-Liste anbieten.

## Beispiel-Antworten

**„Was ist OER?"**
> OER (Open Educational Resources) sind frei lizenzierte
> Bildungsmaterialien — meist unter CC BY oder CC BY-SA. Sie können
> kostenlos genutzt, angepasst und weitergegeben werden.
> Mehr Details: [OER-Bereich auf WLO](https://wirlernenonline.de/oer/).

**„Wie viele OER hat WLO?"**
> Stand 2025:
> - **170.000** OER in Deutschland (Verdreifachung seit 2022)
> - **102.643** Hochschul-OER
> - **61.775** Schul-OER
> - **7.820** Berufliche-Bildung-OER
>
> Quelle: [OER-Statistik](https://wp-test.wirlernenonline.de/oer-statistik/).
