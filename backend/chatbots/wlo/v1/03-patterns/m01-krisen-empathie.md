---
id: M01
label: Krisen-Empathie
short_purpose: Akute psychische Not / Selbstgefährdung → empathisch + Hilfsnummern. Vom Safety-Layer enforced.
priority: 999
default_tone: warm
default_length: kurz
response_type: empathy
core_rule: Empathisch, kurz, KEINE Bildungsantwort. Hilfsnummer immer mitliefern.
when_to_use:
  - Safety-Layer erkennt akute psychische Not / Selbstgefährdung
  - User-Text zeigt Suizid-Gedanken / -Pläne / Krisensignale
  - risk_level=high, safety.enforced_pattern=M01
when_not_to_use:
  - Bildungs- oder Materialfrage (auch wenn emotional gefärbt)
  - Wissensfrage zum Thema psychische Gesundheit ohne akute Krise → M04
  - User fragt nach Hilfsangeboten allgemein (kein akuter Notruf) → M04
trigger_phrases:
  - Ich will mich umbringen
  - Es lohnt sich nicht mehr
  - Niemand würde mich vermissen
  - Ich halte das nicht mehr aus
discriminators:
  - vs: M04
    rule: Akute Krise (Ich-Form, Gegenwart) → M01. Wissens-/Aufklärungs-Frage → M04.
    example: Wie erkenne ich Depression? → M04 (keine eigene Krise). Ich habe Suizidgedanken → M01.
  - vs: M02
    rule: Selbst-Gefährdung → M01 (Empathie). Dritt-Gefährdung/Bedrohung anderer → M02 (Refusal).
    example: Ich will mich verletzen → M01. Ich will jemand anderem schaden → M02.
---

# M01 — Krisen-Empathie

## Antwort
1. Wahrnehmung anerkennen (1 Satz)
2. Telefonseelsorge: **0800 111 0 111** / **0800 111 0 222** / **116 123** (kostenfrei, 24/7)
3. Kein Übergang zu Bildung, keine Quick-Replies
