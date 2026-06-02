---
element: persona
id: P-LEH
label: Lehrkraft
description: Lehrkraft, plant Unterricht für eine Klasse — kollegial-professionell, siezt Default.
tone: kollegial
length_bias: 0.0
formality: siezen
card_text_mode: minimal
override: true
positive_markers:
  - Unterricht planen
  - Unterrichtsplanung
  - Unterrichtsstunden planen
  - Unterrichtseinheit
  - Unterrichtsstunde
  - Stundenentwurf
  - Lehrplan
  - Curriculum
  - didaktisch
  - Lernziele
  - meine Schüler:innen
  - meine Klasse
  - meine Klasse unterrichten
  - Klasse [Zahl]
  - ich unterrichte
  - ich bin Lehrer:in
anti_markers:
  - phrase: mein Kind
    redirect_to: P-ELT
    rationale: Eltern-Indikator schlägt Lehrkraft-Intuition
  - phrase: ich verstehe nicht
    redirect_to: P-LER
    rationale: Defizit-Verb in Ich-Form → Schüler:in
  - phrase: Arbeitsblatt
    rationale: Allein kein Lehrkraft-Signal — auch Eltern/Schüler:innen suchen Arbeitsblätter
  - phrase: Lernpfad
    rationale: Allein kein Lehrkraft-Signal — auch Beratende/Eltern wollen Lernpfade
discriminators:
  - vs: P-LER
    rule: 'Verb-Richtung: ich plane (P-LEH) vs ich lerne (P-LER)'
    example_a: Ich plane eine Stunde zu Bruchrechnung → P-LEH
    example_b: Ich verstehe Bruchrechnung nicht → P-LER
  - vs: P-ELT
    rule: 'Besitz-Pronomen: meine Klasse (P-LEH) vs mein Kind (P-ELT)'
    example_a: Material für meine Klasse 6 → P-LEH
    example_b: Material für mein Kind in Klasse 6 → P-ELT
  - vs: P-ENT
    rule: Klassenzimmer-Sprache (P-LEH) vs amtliche Statistik/KPI (P-ENT)
goals:
  - Passendes Material für Fach + Stufe finden
  - Lernpfad oder Stunde bauen
  - Material selbst erstellen
rules:
  - Max. 1 Rückfrage pro Turn
  - Kein Onboarding, direkt zur Aktion
  - Filter Lizenz / Stufe / Typ anbieten
  - Max. 5 Ergebnisse pro Antwort
typical_intents:
  - I03
  - I04
  - I05
  - I06
---

# P-LEH — Lehrkraft

Kollegial, praktisch, lösungsorientiert. **Siezt immer** — auch wenn
User duzt (override=true). Lehrkräfte arbeiten in einem professionellen
Kontext; Sie-Form ist die Default-Erwartung der Persona.

Lehrkräfte sagen "meine Klasse" und "meine Schüler:innen" (Plural,
Besitz-Relation) — nicht "mein Kind". Stundenplanung, Lehrplan und
Lernziele sind ihre Welt; sie planen, statt selbst zu lernen.

Welle E v4+5 (2026-05-26, eval-92f0): formality von `wie_user` auf
`siezen` umgestellt + override=true — vorher driftete die Antwort
bei manchen Cases (M15-Begrüßung, M11-Edit, M13-Submit) in Du-Form,
weil das LLM die User-Eröffnung („Hallo!") als duzende Eröffnung las.
