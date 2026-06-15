---
element: persona
id: P-ENT
label: Entscheider
description: Verwaltung / Politik / Schulleitung / Bildungsberatung — formell, evidenz-basiert, immer siezen.
tone: formell
length_bias: 0.1
formality: siezen
card_text_mode: minimal
override: true
positive_markers:
  - Schulamt
  - Ministerium
  - Schulaufsicht
  - amtliche Daten
  - KPI
  - Quartalsbericht
  - evidenzbasiert
  - Wahlkreis
  - Fraktion
  - Parlamentsanfrage
  - Positionspapier
  - ich bin Politikerin
  - als Abgeordneter
  - als Schulleitung
  - Schulentwicklung
  - Schulträger
  - Schulberatung
anti_markers:
  - phrase: mein Kind
    redirect_to: P-ELT
    rationale: Eltern-Pronomen
  - phrase: meine Klasse
    redirect_to: P-LEH
    rationale: Lehrkraft-Sprache
  - phrase: für meinen Artikel
    redirect_to: P-RED
    rationale: Redaktions-/Presse-Bezug
  - phrase: Statistik
    rationale: Allein kein P-ENT-Signal — auch Lehrkräfte/Eltern/Schüler:innen fragen nach Statistiken
  - phrase: Bildungspolitik
    rationale: Allein kein P-ENT-Signal (Thema, keine Persona) — nur mit Politik-Kontextwort wie Wahlkreis/Fraktion/Plenum
discriminators:
  - vs: P-LEH
    rule: amtliche Statistik / KPI / Schulleitung (P-ENT) vs Klassenraum / Stundenplanung (P-LEH)
    example_a: Bezirksauswertung der Schulen → P-ENT
    example_b: Materialien für meine Klasse 7 → P-LEH
  - vs: P-LEH
    rule: Edit-Anfragen ohne neuen Klassenbezug bleiben in der Persona des Vor-Turns (P-ENT bleibt P-ENT).
    example_a: Könnten Sie den Lernpfad kürzer fassen (Vor-Turn P-ENT) → P-ENT bleibt
    example_b: Könnten Sie den Lernpfad für meine Klasse 7 kürzer fassen → P-LEH
  - vs: P-RED
    rule: amtliche Daten / Wahlkreis (P-ENT) vs eigene Außen-Publikation (P-RED)
    example_a: Statistik für die Schulkonferenz → P-ENT
    example_b: Statistik für meinen Artikel → P-RED
  - vs: P-ELT
    rule: Verwaltungs-Statistik (P-ENT) vs persönliche Kindes-Daten (P-ELT)
    example_a: Statistik zur Bezirksauswertung → P-ENT
    example_b: Statistik zu Hausaufgaben meiner Tochter → P-ELT
goals:
  - Belastbare Daten + Statistik / KPI-Übersichten beschaffen
  - Berichte als Entscheidungs-Grundlage erstellen
rules:
  - Konkrete Eckdaten/Zahlen statt Allgemeinplätzen — Antworten müssen substanziell sein, nicht nur einladend
  - Belastbare Zahl → mit Quelle + Stand angeben. KEINE belastbare Zahl vorhanden → das ehrlich benennen und auf eine konkrete Quelle/Seite verweisen (z. B. /oer-statistik, passendes Fachportal, /mitmachen) statt vager Floskeln
  - Sachlich-formelle Verwaltungssprache, keine Marketing-Sprache, keine Wertung
  - Bullet-Listen statt langer Prosa
  - Bei Berichts-/Statistik-Wunsch → M10 (KI-Inhalt-Generierung)
typical_intents:
  - I02
  - I03
  - I05
---

# P-ENT — Entscheider

Formell, sachlich, evidenz-basiert. **Immer siezen** — auch wenn der User
duzt (override=true). Diese Persona bündelt Verwaltung, Politik,
Schul-/Bildungsberatung, Schulleitung und Schulträger in einer Rolle.

Erkennbar an amtlich-strategischer Sprache (KPI, Quartalsbericht,
Schulentwicklung) oder Politik-Kontext (Wahlkreis, Fraktion, Positionspapier).
„Wie funktioniert WLO für die Bildungspolitik?" allein ist NICHT ableitbar
→ P-AND; erst mit Selbst-ID oder Politik-Kontextwort wird es P-ENT.

Edit-Anfragen ohne neuen Persona-Hinweis bleiben in der Persona des
Vor-Turns: „Könnten Sie den Lernpfad kürzer fassen" nach einem P-ENT-Turn
bleibt P-ENT — erst ein expliziter Klassenbezug kippt zu P-LEH.
