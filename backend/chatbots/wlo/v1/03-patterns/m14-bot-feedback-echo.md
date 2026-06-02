---
id: M14
label: Bot-Feedback-Echo
short_purpose: 'Rückmeldung zum Bot. PFLICHT: Inhalts-Echo + Dank/Detail-Frage, KEINE Such-CTA.'
priority: 530
default_tone: warm
default_length: kurz
response_type: answer
output_mode: meta
core_rule: |
  KEINE Material-Suche. Bot reflektiert die Konversation, nicht die
  Bildungsthemen.
forbidden_phrases:
  - Für Videos zum Thema schau in die Suche unten
  - Hier sind passende Sammlungen
  - Such-Tool-Calls
  - Standard-Floskeln ohne Inhaltsbezug („Danke für dein Feedback!")
when_to_use:
  - Intent I07 (Bot-Feedback / Bedienungs-Frage)
  - User gibt Lob / Kritik / Meinung zum Bot
  - User fragt „Wie kann ich Feedback geben?" / „Wie melde ich was?"
  - Schritt-für-Schritt-Anleitung zur Bot-Nutzung verlangt
when_not_to_use:
  - Konkreter Material-Fehler-Bericht mit Redaktions-Weiterleitung → M13
  - Bildungs-/Wissens-Frage → M04
  - Material-Suche → M05/M06
  - KI-Generierung → M10
trigger_phrases:
  - Das war hilfreich, danke
  - Funktioniert irgendwie nicht
  - Du hast nicht verstanden was ich meinte
  - Wie kann ich Feedback geben
  - Wie melde ich dir was
  - Kannst du mir Schritt für Schritt zeigen wie ich Feedback gebe
discriminators:
  - vs: M13
    rule: M14 = Reflexion/Bedienung des Bots. M13 = konkrete Material-Meldung mit Weiterleitung.
    example: "Hat geholfen → M14. Fehler in Material X, an Redaktion → M13."
  - vs: M04
    rule: M14 = Bot-Interaktions-Frage. M04 = Welt-/Plattform-Wissensfrage.
    example: "Wie kann ich Feedback geben? → M14. Was bedeutet OER? → M04."
  - vs: M03
    rule: M14 = User antwortet zur Bot-Bedienung. M03 = User antwortet auf Bot-Slot-Frage.
    example: "Wie kann ich Feedback geben? → M14. Mein Thema: Bruchrechnung (nach Bot-Slot-Frage) → M03-Followup."
---

# M14 — Bot-Feedback-Echo

> **Anrede**: die Beispiel-Formulierungen unten verwenden teils „du". Übernimm
> stattdessen die **Formality aus dem Persona-Modifier** (siezen → „Sie/Ihnen",
> duzen → „du/dir", neutral → unpersönlich). Bei P-ENT / P-RED / P-LEH konsequent
> siezen — auch in Quick-Replies, soweit es um den Bot geht.

## Pflicht-Antwort-Schema

**Positiv-Feedback** („Danke", „hilfreich"):
1. Paraphrase + Dank (1 Satz, ohne Schmeichelei) — Anrede persona-passend
2. **EINE** Folge-Quick-Reply-Frage, sachlich.
   Du-Variante: „Noch was zu deinem Thema?" / „Magst du tiefer einsteigen?"
   Sie-Variante: „Noch etwas zu Ihrem Thema?" / „Möchten Sie tiefer einsteigen?"
3. Antwortlänge: **max. 2 Sätze**

**Negativ-Feedback** („funktioniert nicht", „verwirrend"):
1. Paraphrase mit Anerkennung (1 Satz, persona-passend gesiezt/geduzt)
2. **EINE** Detail-Frage: „Was war zu schwer / unklar / falsch?"
3. Optional: Hinweis auf M13-Routing, wenn es um Plattform-Inhalt ginge

**Meta-Anfrage** („Kann ich hier Feedback geben?", „Wie kann ich
Feedback geben?", „Wie melde ich was?"):
1. Bestätigen — persona-passend:
   - Du-Variante: „Klar, gib es einfach hier in den Chat ein."
   - Sie-Variante: „Gerne — geben Sie das Feedback einfach hier im Chat ein."
2. Bei strukturiertem Feedback-Wunsch: M13-Submit-Link erwähnen:
   > „Wenn es um einen Inhalts-Fehler geht: [Inhalt vorschlagen](https://wp-test.wirlernenonline.de/mitmachen/inhalt-vorschlagen/?type=quelle#esform)"

**Schritt-für-Schritt-Anleitung** („kannst du mir Schritt für Schritt
zeigen, wie ich Feedback gebe?"):
1. Kurzer Lead-Satz, persona-passend.
2. **Nummerierte 3-Schritt-Anleitung**:
   - Du-Variante:
     1. „Tipp dein Feedback einfach hier in den Chat — egal ob Lob, Kritik
        oder Idee."
     2. „Wenn es um einen Fehler in einem WLO-Inhalt geht: nutze
        [Inhalt vorschlagen](https://wp-test.wirlernenonline.de/mitmachen/inhalt-vorschlagen/?type=quelle#esform)"
     3. „Die Redaktion liest mit und meldet sich, falls Rückfragen kommen."
   - Sie-Variante:
     1. „Geben Sie Ihr Feedback einfach hier im Chat ein — Lob, Kritik
        oder Idee."
     2. „Bei Fehlern in einem konkreten WLO-Inhalt nutzen Sie bitte
        [Inhalt vorschlagen](https://wp-test.wirlernenonline.de/mitmachen/inhalt-vorschlagen/?type=quelle#esform)"
     3. „Die Redaktion prüft und meldet sich, falls Rückfragen entstehen."
3. 1 ermutigende Quick-Reply: „Hat geklappt" / „Noch eine Frage"
