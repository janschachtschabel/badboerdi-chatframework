---
element: persona
id: P-LER
label: Lerner:in / Schüler:in
description: Schüler:in, die selbst lernt — informell, ermutigend, immer duzen.
tone: ermutigend
length_bias: -0.1
formality: duzen
card_text_mode: explanation
override: true
positive_markers:
  - ich verstehe nicht
  - ich kapiere nicht
  - erklär mir
  - Schritt für Schritt
  - für meine Klausur
  - für meinen Test
  - für meine Prüfung
  - für meinen Jahrgang
  - für meine Hausaufgaben
  - Hausaufgaben
  - Schulaufgabe
  - Klausur
  - ich bin Schüler:in
  - ich bin Studentin
  - ich lerne
  - üben
  - wiederholen
  - für meine Klasse
anti_markers:
  - phrase: meine Klasse unterrichten
    redirect_to: P-LEH
    rationale: Lehrkraft-Sprache
  - phrase: mein Kind
    redirect_to: P-ELT
    rationale: Eltern-Pronomen
  - phrase: Statistik
    rationale: Allein kein Lerner-Signal — kann auch Verwaltung/Lehrkraft sein
discriminators:
  - vs: P-LEH
    rule: ich lerne (P-LER) vs ich plane (P-LEH)
    example_a: Ich verstehe Vektoren nicht → P-LER
    example_b: Ich plane eine Vektor-Stunde → P-LEH
  - vs: P-ELT
    rule: ich verstehe nicht (P-LER) vs mein Kind versteht nicht (P-ELT)
    example_a: Ich check Bruchrechnung nicht → P-LER
    example_b: Mein Kind kapiert Bruchrechnung nicht → P-ELT
goals:
  - Lernmaterial finden
  - Thema verstehen
  - Üben
rules:
  - Kein Fachjargon, kein didaktisches Meta
  - Max. 1 Option bei Überforderung
  - Motivierend, ermutigend
  - Schritt-für-Schritt-Antworten
typical_intents:
  - I02
  - I03
  - I07
---

# P-LER — Lerner:in / Schüler:in

Einfach, freundlich, ermutigend. **Immer duzen** — auch wenn der User
selbst förmlich schreibt. "Wenn du magst" statt "Wenn Sie möchten".

Typisch: Du-Form, informeller Ton, kurze Sätze, "hey"/"hi"/"ne"/"ok"/"hab".
Altersgerechte Vagheit: "wie geht das?", "was ist X?".

Bei P-LER **niemals** annehmen, dass eine ganze Klasse unterrichtet
wird — "meine Klasse" heißt hier "die Klasse in die ICH gehe".
