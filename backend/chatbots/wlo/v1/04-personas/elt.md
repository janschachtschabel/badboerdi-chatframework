---
element: persona
id: P-ELT
label: Eltern
description: Eltern eines schulpflichtigen Kindes — warmer Ton, einfache Sprache.
tone: warm
length_bias: 0.2
formality: wie_user
card_text_mode: explanation
override: false
positive_markers:
  - mein Kind
  - mein Sohn
  - meine Tochter
  - meine Kinder
  - für meinen [Alter]-Jährigen
  - Nachhilfe
  - Nachhilfe für mein Kind
  - Hausaufgaben meines Kindes
  - für zu Hause
  - ich bin Mutter
  - ich bin Vater
anti_markers:
  - phrase: meine Klasse
    redirect_to: P-LEH
    rationale: Lehrkraft-Sprache (Besitz einer ganzen Klasse)
  - phrase: Statistiken
    rationale: Allein kein Eltern-Signal — Statistik-Frage ist Intent, keine Persona
discriminators:
  - vs: P-LEH
    rule: mein Kind (P-ELT) vs meine Klasse (P-LEH)
    example_a: Arbeitsblatt für mein Kind → P-ELT
    example_b: Arbeitsblatt für meine Klasse → P-LEH
  - vs: P-LER
    rule: mein Kind versteht nicht (P-ELT) vs ich verstehe nicht (P-LER)
    example_a: Mein Kind kapiert Bruchrechnung nicht → P-ELT
    example_b: Ich check Bruchrechnung nicht → P-LER
goals:
  - Passende Inhalte für eigene Kinder finden
  - Hausaufgabenhilfe
  - Orientierung über Klassenstufen
rules:
  - Kein Fachjargon, kein didaktisches Vokabular
  - Klassenstufe immer berücksichtigen
  - Vorauswahl statt offener Filter
typical_intents:
  - I02
  - I03
  - I06
---

# P-ELT — Eltern

Freundlich, unterstützend, einfache Sprache. Siezen Default,
Sorge-Unterton.

**Sobald "mein Kind" / "mein Sohn" / "meine Tochter" fällt → P-ELT,
nicht P-LEH.** Auch wenn der Rest technisch klingt ("Arbeitsblätter
Mathe"). Lehrkräfte sagen "meine Klasse" / "meine Schüler:innen",
Eltern sagen "mein Kind".
