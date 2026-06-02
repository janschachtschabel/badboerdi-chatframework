---
element: persona
id: P-AND
label: Andere / Unbekannt
description: Default-Persona ohne klare Marker — offen, neutral, weder duzen noch siezen.
tone: locker
length_bias: 0.0
formality: neutral
card_text_mode: minimal
override: false
anti_markers:
  - phrase: mein Kind|mein Sohn|meine Tochter
    redirect_to: P-ELT
    rationale: Eltern-Pronomen
  - phrase: meine Klasse|Stundenentwurf
    redirect_to: P-LEH
    rationale: Lehrkraft-Sprache
  - phrase: verstehe nicht|für meine Klausur
    redirect_to: P-LER
    rationale: Lerner-Defizit-Indikator
  - phrase: ich kuratiere|Artikel|Pressemitteilung
    redirect_to: P-RED
    rationale: Redaktions-/Presse-Bezug
  - phrase: Wahlkreis|Schulamt|KPI|Schulberatung
    redirect_to: P-ENT
    rationale: Verwaltungs-/Politik-Sprache
  - phrase: ich bin (Lehrer:in|Schüler:in|Mutter|Vater|Redakteur:in|Politikerin)
    rationale: Jede explizite Selbst-ID bricht P-AND
discriminators:
  - vs: P-LEH
    rule: P-LEH ist KEIN Default — ohne eindeutige Lehrkraft-Signale lieber P-AND
  - vs: P-ENT
    rule: '"Bildungspolitik" als Topic allein → P-AND, nicht P-ENT'
goals:
  - Vage Anfrage strukturieren
  - Plausible Persona herausfinden
  - Bei Unsicherheit offen-neutral bleiben
rules:
  - 'Bei vager Anfrage: 3 Optionen + sanfte Persona-Frage'
  - 'Bei expliziter Selbst-ID ("Ich bin Lehrerin"): turn_type = "correction" setzen, dann umklassifizieren'
typical_intents:
  - I01
  - I02
  - I03
---

# P-AND — Andere / Unbekannt

Default-Persona ohne klare Marker. Offen, neutral (weder duzen noch
siezen bis Klärung).

Sobald ein eindeutiger Marker einer anderen Persona fällt, ist es
NICHT mehr P-AND. Bei expliziter Selbst-ID umklassifizieren mit
`turn_type = "correction"`.
