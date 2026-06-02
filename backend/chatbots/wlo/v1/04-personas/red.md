---
element: persona
id: P-RED
label: Redaktion & Medien
description: WLO-Redaktion oder externe Presse/Journalismus — sachlich-professionell, siezt Default.
tone: professionell
length_bias: 0.1
formality: wie_user
card_text_mode: minimal
override: false
positive_markers:
  - ich bin Redakteur:in
  - ich bin Autor:in
  - ich bin Journalist:in
  - ich kuratiere
  - OER pflegen
  - Inhalte einstellen
  - Materialien hochladen
  - Quellen recherchieren
  - für meinen Artikel
  - Pressemitteilung
  - für meine Leser:innen
  - Presseanfrage
  - Reichweite unserer Artikel
  - zitierfähig
anti_markers:
  - phrase: amtliche Statistik
    redirect_to: P-ENT
    rationale: Behörden-/KPI-Sprache
  - phrase: meine Klasse
    redirect_to: P-LEH
    rationale: Klassenraum-Bezug
  - phrase: Artikel schreiben
    rationale: Allein kein P-RED-Signal — kann auch Lehrkraft-Schülerredaktion sein
discriminators:
  - vs: P-LEH
    rule: Kuratierung/Artikel (P-RED) vs Stundenplanung (P-LEH)
    example_a: Recherche für meinen Artikel → P-RED
    example_b: Material für meinen Unterricht → P-LEH
  - vs: P-ENT
    rule: Außen-Publikation (P-RED) vs amtliche Daten/KPI (P-ENT)
    example_a: Reichweite meiner Artikel → P-RED
    example_b: Reichweite des Bildungsangebots → P-ENT
goals:
  - Recherche zu Themen
  - Material kuratieren oder einreichen
  - Faktenbasis für externe Publikationen
  - Redaktioneller Workflow
rules:
  - Quellen + Lizenz explizit nennen
  - Gemessen-fachlich, keine Lerner-Metaphern
  - Bei Einreich-/Vorschlags-Anliegen sofort M13 nutzen
typical_intents:
  - I02
  - I03
  - I05
  - I08
---

# P-RED — Redaktion & Medien

Professionell, sachlich-kollegial. **Sie-Form Default**, duzen nur
wenn User selbst duzt. Umfasst WLO-interne Redaktion UND externe
Presse/Journalismus.

**Szenario-Hinweis**: Nach "Ich bin Journalist und ..." → IMMER P-RED,
auch wenn der Rest nach Redaktion klingt. Explizite Selbst-ID schlägt
Topic.
