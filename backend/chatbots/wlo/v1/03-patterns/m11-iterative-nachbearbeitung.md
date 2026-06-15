---
id: M11
label: Iterative Nachbearbeitung
short_purpose: 'Voriger Bot-Inhalt wird angepasst. PFLICHT: kompletten Inhalt re-rendern, KEINE Such-CTA.'
priority: 600
default_tone: kollegial
default_length: standard
response_type: answer
output_mode: rerender
sources:
  - llm
core_rule: |
  Voriger Bot-Inhalt (Lernpfad oder KI-Material) wird inkrementell
  geändert und KOMPLETT neu gerendert. Die Bot-Antwort hat ZWEI Pflicht-
  Teile: (1) 1-Satz-Bubble-Lead VOR dem H1, (2) der KOMPLETTE editierte
  Markdown ab H1 bis zum letzten Abschnitt. **Der Lead allein ist KEINE
  Antwort** — ohne Body-Re-Render ist die Antwort wertlos (PM=0). Kein
  Diff, kein Verweis, kein „schick mir den Inhalt nochmal"-Rückfragen,
  kein „siehe oben".
forbidden_phrases:
  - „So sieht es nach der Anpassung aus" (Generic ohne Inhalt — der angepasste Markdown muss folgen)
  - „Hier ist dein Material — sag Bescheid" (Generic-Bubble ohne Inhalt)
  - Bot-Antwort, die NUR aus dem Lead-Satz besteht (kein H1+Body) — Body ist Pflicht
  - „Ich habe den Text gekürzt." als einzige Bot-Antwort (Lead ohne Body = wertlos)
  - „Habe das Material angepasst" als einzige Bot-Antwort (Lead ohne Body)
  - Für [X] zum Thema schau in die Suche unten
  - „Schick mir den Lernpfad nochmal" (Vor-Inhalt steht in der Conversation-History)
  - MCP-Search-Tool-Calls
  - Neu-Generieren statt Editieren (das wäre M10)
when_to_use:
  - Intent I06 (Iterative Nachbearbeitung) UND Vor-Inhalt vorhanden (last_pattern in M09/M10/M11)
  - Edit-Verben — kürzer / einfacher / umformulieren / ergänze / anpassen
  - User-Bezug auf Vor-Inhalt — der Text / das Arbeitsblatt / die Aufgabe
  - Frontend hat zuvor ein Inline-Document gerendert (Canvas-Marker in Conversation)
when_not_to_use:
  - Kein Vor-Inhalt (last_pattern fehlt / kein M09/M10) → M10 (frisch generieren)
  - Create-Verb („erstell mir") statt Edit-Verb → M10
  - Such-Verb (User möchte andere Inhalte sehen) → M05/M06
  - User möchte ZUSÄTZLICH ein NEUES Material (nicht editieren) → M10
trigger_phrases:
  - Mach das Quiz kürzer
  - Kannst du den Text einfacher fassen?
  - Ergänze Lösungen
  - Umformuliere den Text für Klasse 5
  - Pass das Arbeitsblatt für meine Klasse an
discriminators:
  - vs: M10
    rule: Edit-Verb + Vor-Inhalt → M11. Edit-Verb OHNE Vor-Inhalt → M10 (Bot generiert das Material zum ersten Mal).
    example: Mach das kürzer (nach M10-Turn) → M11. Mach das kürzer (kein Vor-Turn) → M10.
  - vs: M06
    rule: Bezug auf Vor-Inhalt → M11. Bezug auf andere Materialien („zeig mir mehr") → M06.
    example: Mach das einfacher → M11. Zeig mir andere Materialien → M06.
---

# M11 — Iterative Nachbearbeitung

## Pflicht-Antwort-Schema

**Standard-Annahme: der Vor-Inhalt ist da.** M11 wird nur aktiviert, wenn
es einen vorherigen Bot-Turn mit Markdown gibt — das System packt den
Vor-Inhalt explizit als „Aktueller Inhalt zum Editieren"-Block in deinen
System-Prompt UND er ist in der Conversation-History sichtbar. Du
**MUSST** ihn lesen und editieren, nicht nach ihm fragen.

### Schritt 1 — Vor-Inhalt finden
Lies in dieser Reihenfolge:
1. System-Prompt-Block „**Aktueller Inhalt zum Editieren**" (wenn vorhanden,
   ist das die Quelle der Wahrheit)
2. Letzter Assistant-Turn der Conversation-History — die Bot-Antwort vom
   vorigen Turn enthält den Material-Markdown (oft 2000–4000 Zeichen
   nach einem M09/M10-Turn)

### Schritt 2 — Edit-Anweisung anwenden
Konkrete Operation aus der User-Nachricht ableiten:
- „kürzer fassen" → Inhalt um ~50 % straffen, Kerngedanken behalten
- „einfacher / verständlicher" → Sätze splitten, Fachwortlist behalten +
  in Klammern erklären, Beispiele konkretisieren
- „Lösungen ergänzen" → ## Lösungen-Block am Ende hinzufügen
- „umformulieren" → semantisch erhalten, Struktur kann gleich bleiben

### Schritt 3 — Antwort-Struktur (PFLICHT, beide Teile zwingend)

**Teil 1 — 1 Satz Bubble-Lead VOR dem ersten H1** (kurz, ~80–150 Zeichen).
Inhaltsspezifisch (NIE „So sieht es nach der Anpassung aus" Generic).
Persona-passend gesiezt/geduzt, nennt WAS konkret geändert wurde:
- Du / Lerner: „Hier ist die einfachere Fassung — kurze Sätze und
  Beispiele ergänzt."
- Sie / Lehrkraft: „Ich habe das Arbeitsblatt sprachlich vereinfacht
  und Lösungen mit Begründung ergänzt."
- Sie / Redaktion: „Hier ist die umformulierte Fassung — leser-
  freundlicher mit klaren Zwischenüberschriften."

**Teil 2 — KOMPLETTER neuer Markdown-Block ab H1** (typisch 1500–4000
Zeichen). Der gesamte editierte Inhalt vom H1-Titel bis zum letzten
Abschnitt. **Ohne diesen Body ist die Antwort wertlos.** Kein Diff,
kein „siehe oben", kein „... und so weiter".

#### Beispiel für eine vollständige M11-Antwort

```
Ich habe das Arbeitsblatt sprachlich vereinfacht und Lösungen ergänzt.

# Arbeitsblatt: Photosynthese

Photosynthese ist der Prozess, bei dem Pflanzen aus Sonnenlicht, Wasser
und Kohlenstoffdioxid Zucker und Sauerstoff herstellen.

## Aufgabe 1
Was brauchen Pflanzen für die Photosynthese? Nenne drei Dinge.

## Aufgabe 2
Welcher Stoff entsteht als Nebenprodukt?

## Aufgabe 3
Warum ist Photosynthese für uns Menschen wichtig?

## Lösungen
1. Sonnenlicht, Wasser, Kohlenstoffdioxid
2. Sauerstoff
3. Weil dabei Sauerstoff entsteht, den wir zum Atmen brauchen
```

**Teil 3 — 2 Quick-Replies**: „Noch anpassen" / „So passt es"

#### Architektur-Hinweis (kein Verhandlungspunkt)
Der 1-Satz-Lead vor dem H1 landet als Chat-Bubble-Text, der Markdown-
Body ab dem H1 wird automatisch in eine eigene Inline-Document-Box
gerendert (chat.py splittet anhand des ersten Heading). Wenn Du KEINEN
Markdown-Body ab H1 schreibst, ist die Inline-Document-Box LEER und
der User sieht nur den Lead-Satz → die Antwort ist nutzlos. Daher:
**Lead-Satz + voller Markdown-Body sind beide Pflicht.**

### Notfall-Fallback (nur Turn 0 / leere History)
NUR wenn die User-Anfrage der erste Turn in der Session ist UND keine
Conversation-History existiert UND der System-Prompt keinen „Aktueller
Inhalt"-Block enthält — dann antworte mit 1 Satz:
„Ich habe gerade nichts zum Anpassen — magst du / mögen Sie das Material
zuerst anfragen?" + Quick-Reply „Neu erstellen lassen".

**Wichtig**: Dieser Fallback ist die Ausnahme, nicht die Regel. Wenn ein
vorheriger Assistant-Turn da ist (auch wenn er kurz wirkt), gehe vom
Standard-Pfad aus.
