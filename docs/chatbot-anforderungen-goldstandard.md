# BadBoerdi Chatbot — Gold-Standard-Gesprächsabläufe & Anforderungen

> Confluence-kompatibles Markdown. Direkt einfügbar (Pipe-Tabellen, `- [ ]`-Checklisten werden
> zu Häkchen, Code-Blöcke, keine HTML-Tags / keine verschachtelten Tabellen).

**Zweck:** Vordenk- und Mess-Dokument für den Chatbot. Bewusst **drei getrennte Teile**:

- **Teil 1 — Gold-Standard-Gesprächsabläufe (Persona × Intent):** vollständige, mehrstufige
  Dialoge, die als **optimaler Ablauf** gelten. Geprüft wird über den **ganzen Gesprächsverlauf**
  (nicht nur eine Einzelaktion), ob die Persona in der **richtigen Tonalität** angesprochen und
  mit den **richtigen Angeboten/Inhalten** versorgt wird.
- **Teil 2 — Web-Tour-Gold-Standard:** auf Basis der Website-Funnel-Flows (A1–D2).
- **Teil 3 — Technische ToDos:** getrennt von den Gesprächs-Gold-Standards.

---

## 0. Konventionen

### 0.1 Status-Legende
🟡 Idee · 🔵 spezifiziert · 🟢 in Umsetzung · ✅ umgesetzt & getestet

### 0.2 Glossar — Personas & Intents (Stand Welle E)

| Persona | Rolle | Anrede / Ton |
|---|---|---|
| `P-LEH` | Lehrkraft | **siezt**, kollegial-professionell |
| `P-LER` | Lernende:r / Schüler:in | **duzt**, ermutigend |
| `P-ELT` | Eltern | freundlich, alltagsnah |
| `P-ENT` | Entscheider / Verwaltung / Politik / Schulleitung | **formell**, sachlich, evidenzbasiert |
| `P-RED` | Redaktion / Presse | sachlich, quellenorientiert |
| `P-AND` | Andere / unbekannt | neutral, einladend |

| Intent | Bedeutung |
|---|---|
| `I01` | Orientierung („Was ist/bietet WLO?", Mitmachen) |
| `I02` | Wissensfrage / Fakten |
| `I03` | Inhalte-Suchen (Material / Sammlung / Themenseite) |
| `I04` | Lernpfad |
| `I05` | Inhalt-Generieren (KI-Material) |
| `I06` | Inhalt-Nachbearbeiten |
| `I07` | Bot-Feedback |
| `I08` | Einreichen / Melden |

### 0.3 Bewertungsrubrik je Gesprächsablauf

Bewertet wird der **gesamte Dialog** (nicht ein einzelner Turn). Kriterien mit **[K]** sind
kritisch (KO).

| Kriterium | Frage |
|---|---|
| [K] Tonalität | Durchgängig korrekte Anrede/Ton für die Persona (siehe 0.2 / 0.4)? |
| [K] Richtige Angebote | Bekommt die Persona die für sie passenden Angebote/Inhalte (siehe 0.4)? |
| [K] Ablauf-Ziel | Wird das Gesprächsziel im Verlauf erreicht (nicht nur eine Einzelaktion)? |
| Klassifikation | Persona + Intent je Turn korrekt erkannt? |
| Kontext-Erhalt | Thema/Slots über die Turns gehalten (Folgeantworten passen)? |
| URL-Korrektheit | Links existieren, richtiges Repo/Host, `?bsid=` angehängt? |
| Ausgabestruktur | Boxen/Material sauber, Quick-Replies korrekt (keine kaputten QRs)? |

**Score** = erfüllte Kriterien ÷ Gesamt. **Bestanden** = alle [K] erfüllt **und** Score ≥ 90 %.
Pro Durchlauf protokollieren: Datum · Build/Commit · Umgebung · Modell · Tester · Score · Notizen
(Vorlage im Anhang).

### 0.4 Persona → richtige Tonalität & richtige Angebote (Referenz)

| Persona | Anrede | „Richtige Angebote / Inhalte" (Soll) |
|---|---|---|
| `P-LEH` | siezt | Unterrichtsmaterial, Sammlungen, Themenseiten, Lernpfade, Material-Erstellung (Arbeitsblatt/Quiz), Fach-/Stufen-Filter |
| `P-LER` | duzt | Lernmaterial, Erklärungen, Übungen, Lernpfade — altersgerecht, ermutigend |
| `P-ELT` | freundlich | Material für das Kind, Lerntipps, altersgerechte Inhalte |
| `P-ENT` | formell | OER-Statistiken/Zahlen (oder ehrliche Datenlage), WLO-Angebote/Produkte (z.B. Bildungs-API, Integrationen, Souveränes KI-Ökosystem), `/angebote/`, `/mitmachen/` |
| `P-RED` | sachlich | Einreichen/Melden, redaktionelle Angebote, Quellen/Zahlen für Artikel |
| `P-AND` | neutral | Orientierung, Suche, „Mitmachen", Verweis auf passende Zielgruppen-Seite |

---

## Teil 1 — Gold-Standard-Gesprächsabläufe (Persona × Intent)

> Jeder Ablauf: **Ausgangslage → idealer Dialog (mehrere Turns) → Bewertung**. Diese Abläufe
> dienen als manuelle Abnahme **und** als Seed für die automatische Eval.

### Abdeckungs-Matrix

`GS-x` = durch diesen Ablauf abgedeckt · `GS-x↩` = als **Folge-Turn** in GS-x abgedeckt ·
`–` = kein primärer Gold-Standard für diese Kombination (untypisch; Tonalität/Angebote folgen
dem Persona-Profil 0.4 und können bei Bedarf analog ergänzt werden). `I07` (Bot-Feedback) ist
**persona-übergreifend** in GS-12 abgebildet.

| Persona | I01 | I02 | I03 | I04 | I05 | I06 | I07 | I08 |
|---|---|---|---|---|---|---|---|---|
| P-LEH | – | – | GS-1 | GS-1 | GS-1 | GS-1↩ | GS-12 | GS-8 |
| P-LER | – | GS-2 | GS-2 | GS-11 | – | – | GS-12 | – |
| P-ELT | – | – | GS-3 | – | – | – | GS-12 | – |
| P-ENT | GS-4 | GS-4 | – | – | GS-9 | GS-9↩ | GS-12 | – |
| P-RED | – | – | GS-10 | – | – | – | GS-12 | GS-5 |
| P-AND | GS-6 | – | GS-7 | – | – | – | GS-12 | – |

Jede **Persona** (Tonalität + Angebote) und jeder **Intent** ist mindestens einmal abgedeckt.
Die mit `–` markierten Kombinationen sind bewusst nicht als eigener Ablauf ausgeführt — sie sind
für die jeweilige Persona untypisch; bei Bedarf nach demselben Template ergänzbar.

### Template (mehrstufig)

```
GS-x · <Persona> × <Intent-Arc> — <Titel>
Ausgangslage: <Start-Seite, Persona-Signal>
Turn 1 — User: "<Eingabe>"
  Erwartete Bot-Reaktion: <Klassifikation, Ton, Inhalt/Angebot, Quick-Replies>
Turn 2 — User: "<Folge-Eingabe>"
  Erwartete Bot-Reaktion: ...
...
Bewertung: Checkliste nach Rubrik 0.3
```

---

### GS-1 · P-LEH × I03 → I04 → I05 — Lehrkraft: von der Suche zum eigenen Material

**Ausgangslage:** Lehrkraft, neue Session auf `wp-test.wirlernenonline.de`.

**Turn 1 — User:** „Ich bereite eine Mathe-Stunde für meine Klasse 3 zum Thema Brüche vor und suche passendes Material."
- Erwartete Bot-Reaktion: erkennt `P-LEH` + `I03`; **siezt**; liefert Ergebnis-Boxen (Themenseiten/Sammlungen/Material) zu *Brüche, Grundschule*; bietet sinnvoll einen Lernpfad oder Fach-/Stufen-Filter an; „Treffer zur Suche"-Button.

**Turn 2 — User:** „Hast du dazu einen fertigen Lernpfad?"
- Erwartete Bot-Reaktion: `I04`; bleibt **siezend**; liefert/erstellt einen Lernpfad zum gehaltenen Thema (Kontext *Brüche/Klasse 3* erhalten); Material-Links korrekt.

**Turn 3 — User:** „Erstelle mir bitte noch ein kurzes Arbeitsblatt dazu."
- Erwartete Bot-Reaktion: `I05`; generiert Arbeitsblatt als **InlineDocument-Box**; bietet Nachbearbeitung an („kürzer", „mit Lösungen").

**Abschluss:** Bot fasst zusammen / bietet Absprung (Treffer-Button) oder „Mitmachen" an, ohne aufdringlich zu sein.

**Bewertung:**
- [ ] [K] Tonalität: durchgängig **gesiezt**
- [ ] [K] Richtige Angebote: Grundschul-/Mathe-Material + Lernpfad-Option + Material-Erstellung
- [ ] [K] Ablauf-Ziel: am Ende hat die Lehrkraft passendes Material **und** ein erstelltes Arbeitsblatt
- [ ] Klassifikation je Turn: P-LEH / I03→I04→I05
- [ ] Kontext-Erhalt: Thema *Brüche/Klasse 3* über alle Turns gehalten
- [ ] URL-Korrektheit: Sammlungen `/components/collections/…`, Material `/components/render/…`, `?bsid=`
- [ ] Ausgabestruktur: Material-Box sauber, Quick-Replies korrekt

---

### GS-2 · P-LER × I02 → I03 — Schüler:in: verstehen, dann üben (Prüfungsvorbereitung)

**Ausgangslage:** Lernende:r, Session auf wp-test.

**Turn 1 — User:** „Ich schreibe bald eine Mathe-Arbeit und kapier Bruchrechnung nicht so richtig."
- Erwartete Bot-Reaktion: `P-LER` + `I02`; **duzt**, ermutigend; gibt eine verständliche Kurz-Erklärung und fragt/leitet zu Übungsmaterial über.

**Turn 2 — User:** „Hast du Übungen dazu?"
- Erwartete Bot-Reaktion: `I03`; **duzt**; liefert altersgerechtes Übungsmaterial/Sammlungen zu Brüchen; „Treffer zur Suche"-Button.

**Abschluss:** ermutigender Ausklang, ggf. Lernpfad-Hinweis.

**Bewertung:**
- [ ] [K] Tonalität: durchgängig **geduzt**, ermutigend (kein Siezen!)
- [ ] [K] Richtige Angebote: altersgerechtes Lern-/Übungsmaterial, Erklärung
- [ ] [K] Ablauf-Ziel: Schüler:in hat Erklärung **und** Übungsmaterial
- [ ] Klassifikation: P-LER / I02→I03
- [ ] Kontext-Erhalt: Thema *Bruchrechnung* gehalten
- [ ] URL-Korrektheit + Ausgabestruktur

---

### GS-3 · P-ELT × I03 — Eltern: Material für das Kind

**Ausgangslage:** Elternteil, Session auf wp-test.

**Turn 1 — User:** „Mein Kind ist in der 5. Klasse und tut sich mit Englisch-Vokabeln schwer — gibt es da was?"
- Erwartete Bot-Reaktion: `P-ELT` + `I03`; freundlich, alltagsnah; liefert altersgerechtes Material/Übungen Englisch Sek I; ggf. Lerntipp.

**Turn 2 — User:** „Gibt es etwas zum spielerischen Üben?"
- Erwartete Bot-Reaktion: `I03`; verfeinert auf interaktives/spielerisches Material; Kontext *Englisch/Klasse 5* gehalten.

**Bewertung:**
- [ ] [K] Tonalität: freundlich, **nicht** fachjargon-lastig; keine Lehrkraft-Ansprache
- [ ] [K] Richtige Angebote: altersgerechtes Material fürs Kind + ggf. Lerntipp
- [ ] [K] Ablauf-Ziel: passendes Übungsmaterial fürs Kind gefunden
- [ ] Klassifikation: P-ELT / I03 (Abgrenzung zu P-LEH beachten — „mein Kind", nicht „meine Klasse")
- [ ] URL-Korrektheit + Ausgabestruktur

---

### GS-4 · P-ENT × I02 → I01 — Entscheider: Zahlen & Angebote

**Ausgangslage:** Entscheider/Schulträger/Politik, Session auf wp-test.

**Turn 1 — User:** „Als Schulträger interessieren mich Zahlen zur OER-Nutzung auf WLO."
- Erwartete Bot-Reaktion: `P-ENT` + `I02`; **formell**, sachlich; liefert verfügbare Statistiken/Quellen **oder** sagt ehrlich, dass keine belastbaren Zahlen vorliegen (**kein erfundener Wert**); verweist auf passende Seite (z.B. OER-Statistik).

**Turn 2 — User:** „Welche Angebote/Produkte bietet WLO für die Integration in unsere Systeme?"
- Erwartete Bot-Reaktion: `I01`/`I02`; **formell**; verweist auf passende `/angebote/`-Seiten (z.B. Bildungs-API, Integrationen, Souveränes KI-Ökosystem); valide Links.

**Bewertung:**
- [ ] [K] Tonalität: durchgängig **formell/siezt**, sachlich
- [ ] [K] Richtige Angebote: Statistik-Quelle **oder** ehrliche Datenlage + passende Produkt-/Angebots-Seiten
- [ ] [K] Ablauf-Ziel: Entscheider bekommt belastbare Orientierung zu Zahlen + Angeboten
- [ ] [K] Keine halluzinierte Statistik / kein erfundener Link
- [ ] Klassifikation: P-ENT / I02→I01
- [ ] URL-Korrektheit (`/angebote/…`)

---

### GS-5 · P-RED × I08 — Redaktion: Inhalt einreichen / Fehler melden

**Ausgangslage:** Redakteur:in/Presse, Session auf wp-test.

**Turn 1 — User:** „Ich habe in einem Lehrplan-Dokument einen inhaltlichen Fehler gefunden — wie melde ich das?"
- Erwartete Bot-Reaktion: `P-RED` + `I08`; sachlich; erklärt den Einreich-/Melde-Weg und bietet den passenden Pfad/Link (Mitmachen/Redaktion) an.

**Turn 2 — User:** „Und wie kann ich selbst Material beisteuern?"
- Erwartete Bot-Reaktion: `I08`/`I01`; verweist auf den Mitmach-/Beitrags-Weg; valide Links.

**Bewertung:**
- [ ] [K] Tonalität: sachlich, korrekt
- [ ] [K] Richtige Angebote: konkreter Einreich-/Melde-Weg + Link (z.B. `/mitmachen/`)
- [ ] [K] Ablauf-Ziel: Nutzer weiß, wie er meldet **und** beiträgt
- [ ] Klassifikation: P-RED / I08
- [ ] URL-Korrektheit

---

### GS-6 · P-AND × I01 — Anonyme:r Nutzer:in: Orientierung & Mitmachen

**Ausgangslage:** kein Rollensignal, Session auf wp-test (oder eingebettet im edu-sharing).

**Turn 1 — User:** „Was ist WissenLebtOnline eigentlich?"
- Erwartete Bot-Reaktion: `P-AND` + `I01`; neutral, einladend; kurze Orientierung; bietet sinnvolle nächste Schritte (suchen / Zielgruppe wählen / Mitmachen) als Quick-Replies.

**Turn 2 — User:** „Wie mache ich bei WLO mit?"
- Erwartete Bot-Reaktion: `I01`; verweist auf den **validen** Link `https://wp-test.wirlernenonline.de/mitmachen/`; bei Cross-Origin: `?bsid=` mitgegeben.

**Bewertung:**
- [ ] [K] Tonalität: neutral, einladend (keine falsche Rollen-Annahme)
- [ ] [K] Richtige Angebote: Orientierung + „Mitmachen"-Weg
- [ ] [K] Ablauf-Ziel: Nutzer weiß, was WLO ist **und** wie man mitmacht
- [ ] [K] `/mitmachen/`-Link valide + `?bsid=`
- [ ] Klassifikation: P-AND / I01

---

### GS-7 · P-AND × I03 — Generische Suche + Absprung (Basis-Suchfall)

**Ausgangslage:** kein Rollensignal, Session auf wp-test.

**Turn 1 — User:** „Ich suche Material zum Thema Klimawandel."
- Erwartete Bot-Reaktion: `P-AND` + `I03`; neutral; Ergebnis-Boxen (Themenseiten/Sammlungen/Material) + „Treffer zur Suche"-Button.

**Turn 2 — User:** „Hast du auch was für die Sekundarstufe?"
- Erwartete Bot-Reaktion: `I03`; grenzt auf die Stufe ein; Kontext *Klimawandel* gehalten.

**Bewertung:**
- [ ] [K] Tonalität: neutral (keine falsche Rollen-Annahme)
- [ ] [K] Richtige Angebote: passende Treffer + Absprung-Möglichkeit
- [ ] [K] Ablauf-Ziel: Material gefunden und abspringbar
- [ ] Klassifikation: P-AND / I03 (beide Turns)
- [ ] URL-Korrektheit: collections / render / search + `?bsid=`
- [ ] Session-Reload vollständig (Begrüßung, Eingaben, Boxen, Treffer-Button, Quick-Replies)

---

### GS-8 · P-LEH × I08 — Lehrkraft: Fehler melden / Material beisteuern

**Ausgangslage:** Lehrkraft, Session auf wp-test.

**Turn 1 — User:** „Ich habe in einem Arbeitsblatt einen fachlichen Fehler entdeckt — wie melde ich das?"
- Erwartete Bot-Reaktion: `P-LEH` + `I08`; **siezt**; erklärt den Melde-Weg und nennt den passenden Pfad/Link.

**Turn 2 — User:** „Und wie kann ich eigenes Material beisteuern?"
- Erwartete Bot-Reaktion: `I08`/`I01`; verweist auf den Beitrags-/Mitmach-Weg (`/mitmachen/`); valide Links.

**Bewertung:**
- [ ] [K] Tonalität: **gesiezt**
- [ ] [K] Richtige Angebote: konkreter Melde- **und** Beitrags-Weg
- [ ] [K] Ablauf-Ziel: Nutzer weiß, wie melden **und** beisteuern
- [ ] Klassifikation: P-LEH / I08
- [ ] URL-Korrektheit (`/mitmachen/`)

---

### GS-9 · P-ENT × I05 → I06 — Entscheider: Bericht/Factsheet generieren & kürzen

**Ausgangslage:** Entscheider/Schulträger, Session auf wp-test.

**Turn 1 — User:** „Erstellen Sie mir ein Factsheet zur Bedeutung von OER für Schulträger."
- Erwartete Bot-Reaktion: `P-ENT` + `I05`; **formell**; generiert Factsheet als **InlineDocument-Box**; gibt **Quellen/Zeitstand** an bzw. macht die Datenlage transparent — **keine erfundenen Zahlen**.

**Turn 2 — User:** „Fassen Sie es bitte auf eine halbe Seite zusammen."
- Erwartete Bot-Reaktion: `I06`; kürzt die bestehende Box, bleibt **formell**; Struktur sauber.

**Bewertung:**
- [ ] [K] Tonalität: durchgängig **formell**
- [ ] [K] Richtige Angebote: brauchbares Factsheet, evidenzorientiert
- [ ] [K] Keine halluzinierten Zahlen / Quellen transparent
- [ ] [K] Ablauf-Ziel: verwertbares, gekürztes Dokument
- [ ] Klassifikation: P-ENT / I05→I06
- [ ] Ausgabestruktur: Material-Box + Nachbearbeitung sauber (keine Format-Brüche)

---

### GS-10 · P-RED × I03 — Redaktion: Material zum Kuratieren recherchieren

**Ausgangslage:** Redakteur:in, Session auf wp-test.

**Turn 1 — User:** „Ich stelle eine Sammlung zum Thema Demokratie zusammen und suche gute Materialien."
- Erwartete Bot-Reaktion: `P-RED` + `I03`; sachlich; liefert Sammlungen/Material + „Treffer zur Suche"-Button.

**Turn 2 — User:** „Welche Anbieter/Quellen stecken dahinter?"
- Erwartete Bot-Reaktion: `I03`/`I02`; liefert Quellen-/Anbieter-Hinweise zu den Treffern.

**Bewertung:**
- [ ] [K] Tonalität: sachlich, quellenorientiert
- [ ] [K] Richtige Angebote: kuratierbares Material + Quellen/Anbieter-Infos
- [ ] [K] Ablauf-Ziel: belastbare Recherche-Basis für eine Sammlung
- [ ] Klassifikation: P-RED / I03
- [ ] URL-Korrektheit

---

### GS-11 · P-LER × I04 — Schüler:in: Lernpfad zusammenstellen

**Ausgangslage:** Lernende:r, Session auf wp-test.

**Turn 1 — User:** „Kannst du mir einen Lernweg für Bruchrechnung zusammenstellen?"
- Erwartete Bot-Reaktion: `P-LER` + `I04`; **duzt**, ermutigend; erstellt einen Lernpfad mit nachvollziehbaren Schritten + Material.

**Turn 2 — User:** „Womit fange ich am besten an?"
- Erwartete Bot-Reaktion: zeigt den ersten Schritt konkret; bleibt **geduzt**, motivierend.

**Bewertung:**
- [ ] [K] Tonalität: durchgängig **geduzt**, ermutigend
- [ ] [K] Richtige Angebote: Lernpfad + zugehöriges Material, altersgerecht
- [ ] [K] Ablauf-Ziel: klarer Lernweg mit Startpunkt
- [ ] Klassifikation: P-LER / I04
- [ ] Ausgabestruktur: Lernpfad-Box sauber, Material-Links valide

---

### GS-12 · I07 (persona-übergreifend) — Bot-Feedback aufnehmen

**Ausgangslage:** Nach einer vorherigen Bot-Antwort (beliebige Persona).

**Turn 1 — User:** „Das hat mir leider nicht weitergeholfen." *(bzw. 👎-Klick, → T2)*
- Erwartete Bot-Reaktion: `I07` (Pattern M14); nimmt das Feedback an, fragt knapp nach dem fehlenden Punkt und bietet einen sinnvollen alternativen nächsten Schritt — **kein** versehentlicher neuer Such-/Generier-Start (Abgrenzung I07 ↔ I03).

**Turn 2 — User:** „Ich hätte gern konkrete Materialien statt Erklärungen."
- Erwartete Bot-Reaktion: reagiert passend (z.B. Suche/Material), Ton bleibt zur Persona passend.

**Bewertung:**
- [ ] [K] Feedback korrekt erkannt (I07, nicht als Suche I03 missverstanden)
- [ ] [K] Tonalität passt zur aktiven Persona
- [ ] [K] Ablauf-Ziel: Feedback aufgenommen **und** sinnvolle Alternative angeboten
- [ ] Verknüpfung mit Feedback-UI (T2) konsistent

---

## Teil 2 — Web-Tour-Gold-Standard (Basis: Website-Funnel-Flows)

Die geführte Web-Tour soll die **typischen Besucher-Flows** abbilden und je nach Einstiegsseite
am richtigen Schritt einsteigen. Diese Flows sind die **Test-Basis** für die Tour.

### Besucher-Flows (Konzept 4.2)

| Flow | Weg | Bedeutung | Tour-Einstieg |
|---|---|---|---|
| A1 | Startseite → Zielgruppen-Landingpage → Produktdetails → Anfrage | Klassischer Zielgruppenflow (Selbstzuordnung) | `intro` |
| A2 | Startseite → Produktseite → Anfrage | Nutzer kennen grob ihr Produkt | `intro` |
| A3 | Startseite → Lösungsübersicht → Produktseite → Anfrage | Brauchen erst Angebotsüberblick | `intro` |
| B1 | Zielgruppen-Landingpage → Produktdetails → Anfrage | Landen direkt auf Zielgruppenseite | `solutions` |
| C1 | Produktdetails → Anfrage | Landen direkt auf Produktseite | `solutions` |
| D1 | Angebots-/Mitmachseite → Anfrage/Formular | Fast konversionsbereit, Ablenkung reduzieren | `contact` |
| D2 | Anfrage-Seite → Formular absenden | Im Abschluss, nur Prozesssicherheit | `contact` |

Diese Flows sind in `website-tour.yaml` redaktionell pflegbar (Schritte, Ziel-URLs, Zielgruppen,
Gruppe→Angebot-Mapping) — ohne Code-Deploy; neue Zielgruppe/Flow ergänzbar.

### Gold-Standard-Tourablauf (mehrstufig, Beispiel A1)

**Ausgangslage:** Tour-Start (Eulen-Klick / „Tour starten") von einer fremden/Demo-Seite.

1. **Start:** Tour begrüßt, nennt **„WissenLebtOnline"**, bietet „Zur Startseite"-Button.
2. **Ankunft Startseite (`group`):** fragt nach Zielgruppe, bietet Gruppen als Quick-Replies.
3. **Zielgruppe gewählt (`group_page`):** „Bring mich hin"-Button zur Zielgruppenseite.
4. **Bildungsinhalte (`content`) → Lösungen (`solutions`):** passende Angebote zur Gruppe.
5. **Anfrage (`contact`, `/mitmachen/`):** Abschluss, Prozesssicherheit.

**Bewertung:**
- [ ] [K] Einstieg passt zum Besucher-Flow (A1–D2 → richtiger Tour-Schritt)
- [ ] [K] Nach jedem Seitenwechsel läuft die Tour weiter (cross-origin via `bsid`, kein Stillstand)
- [ ] [K] Jeder Schritt liefert einen „Bring mich hin"-Button
- [ ] Funnel bis `contact` (`/mitmachen/`) erreichbar
- [ ] Start-Nachricht nennt „WissenLebtOnline" (nicht „WirLernenOnline")
- [ ] Tour ist mid-chat startbar und über „Tour beenden" sauber abbrechbar
- [ ] Tour-Texte/Ziele stammen aus `website-tour.yaml` (keine erfundenen Ziele)

> Varianten je Einstieg testen: Start auf Demo/extern → A1 (`intro`→Startseite); Start auf
> Zielgruppenseite → B1 (`solutions`); Start auf `/mitmachen/` → D1 (`contact`).

---

## Teil 3 — Technische ToDos (getrennt von den Gesprächs-Gold-Standards)

> Diese Punkte sind **infrastruktur-/qualitätsseitig**, kein Bestandteil der Dialog-Bewertung.

### T1 🟡 Feste URL-Zuordnung für RAG-Chunks/Dokumente via Metadaten (gegen URL-Halluzination)
**Problem:** Die KI kann im Freitext URLs erfinden. **Ist-Stand:** Karten + „Treffer zur Suche"
nutzen bereits Metadaten-URLs (`wlo_url`/`topic_page_url`/`search_url`, nicht LLM-generiert);
Risiko = Freitext-Links + RAG-Snippet-URLs.
**Anforderung:** Pflichtfeld `canonical_url` je Chunk/Dokument; Antwort-Builder zieht Links nur
aus Karten-Metadaten oder `canonical_url`; fehlt sie → kein Link statt erfundener Link.
- [ ] [K] Kein Link ohne kontrollierte Quelle.
- [ ] Negativtest: „Gib mir die direkte URL zu X" erzeugt keinen halluzinierten Link.

### T2 🟡 Feedback-UI pro Bot-Antwort (👍/👎)
Pro Bot-Bubble Daumen hoch/runter (optional Freitext); Speicherung mit Turn-Kontext; Auswertung
im Studio. *(Inhaltlicher Feedback-Dialog I07/M14 existiert bereits — hier das UI-Element.)*
- [ ] Klick persistiert, erscheint in Quality-Auswertung. - [ ] Quote je Pattern/Persona sichtbar.

### T3 🟡 Positionierung & Verschiebbarkeit des Widgets
Liegt u.U. **vor** einem zweiten Chatbot (Themenbaum-Generator, Seitenleiste) → Kollision
vermeiden. Position per `position`-Attribut konfigurierbar; zusätzlich Snap-Positionen /
Drag-&-Drop; Position merken (localStorage).
- [ ] Position wechselbar + bleibt nach Reload. - [ ] Kein Überdecken des zweiten Chatbots.

### T4 🟡 Rate-Limits / Kostenschutz
Rate-Limits pro Session/IP (Requests/min + /Tag), Backoff, freundliche Drossel-Antwort; Schutz
gegen „Ja-Straße"/Endlos-Generierung.
- [ ] Lasttest zeigt Deckelung. - [ ] Kosten pro Session begrenzt.

### T5 🟡 Link-Checker + Sitemap-Abgleich
Cron/CI prüft alle ausspielbaren URLs (Karten-Metadaten, `canonical_url`, Web-Tour-Ziele) auf
Existenz + Aktualität; Quelle/Abgleich `https://wp-test.wirlernenonline.de/sitemap_index.xml`.
Bei Webseiten-Umzug: `base_host` (`website-tour.yaml`), `REPO_BASE_URL`, Wissens-URLs neu schreiben.
- [ ] Report listet tote/abweichende Links. - [ ] Web-Tour-Ziele Teil der Prüfung.

### T6 🟡 Modell-Evaluierung & -Auswahl
**Beobachtung:** `gpt-5.4-nano` erkennt **Persona & Pattern gut**, hält aber die
**Ausgabestruktur nicht immer ein** und macht **Fehler bei Schnellantwort-Buttons**
(Quick-Replies). → systematischer Modell-Vergleich über die Gold-Standard-Abläufe.
- [ ] Vergleichsmatrix *Modell × {Persona-Treffer, Pattern-Treffer, **Ausgabestruktur-Konformität** [K], **Quick-Reply-Korrektheit** [K], Latenz, Kosten}*.
- [ ] Empfehlung je Aufgabe dokumentiert (ggf. Hybrid: kleines Modell für Klassifikation, größeres für Antwort/Struktur).
- [ ] Modellwechsel wird vor Live-Gang gegen die Gold-Standard-Abläufe gemessen.

**Vergleichsmatrix (Vorlage):**

| Modell | Persona | Pattern | Struktur | Quick-Replies | p95 Latenz | Kosten/Turn | Empfehlung |
|---|---|---|---|---|---|---|---|
| gpt-5.4-nano | gut | gut | schwach | fehlerhaft |  |  |  |
| gpt-5.4-mini |  |  |  |  |  |  |  |

### T7 🟡 Last-/Performance-Tests (Skalierung, gleichzeitige Nutzende)
**Hypothese:** Engpass bei vielen gleichzeitigen Nutzenden = **lokaler RAG-Reranker auf dem
kleinen vServer** (CPU+RAM) → wahrscheinlich **mehr RAM nötig** oder Reranker auslagern.
- [ ] Stufen **1 / 5 / 10 / 25** gleichzeitige Sessions; je p50/p95-Latenz, Fehler-/Timeout-Rate, **RAM-Peak/OOM** [K], CPU.
- [ ] [K] Engpass benannt + Maßnahme (mehr RAM / Reranker auslagern / `RAG_RERANKER_ENABLED=false` / Caching).
- [ ] Ziel-SLA dokumentiert (z.B. p95 < X s bei N Nutzern, 0 OOM-Kills) + Re-Test nach Maßnahme.

**Lastmatrix (Vorlage):**

| Parallel | p50 | p95 | Fehler % | RAM-Peak | OOM | Engpass |
|---|---|---|---|---|---|---|
| 1 |  |  |  |  |  |  |
| 5 |  |  |  |  |  |  |
| 10 |  |  |  |  |  |  |
| 25 |  |  |  |  |  |  |

### T8 🟡 Backup-Überprüfung (Snapshots / Werkseinstellung / DB)
Sichern **und** Wiederherstellen müssen verlässlich funktionieren — regelmäßig testen, nicht nur annehmen.
- [ ] [K] Restore-Test: ein Config-Snapshot (`chatbots/wlo/v1`-Tree) lässt sich vollständig zurückspielen.
- [ ] Werkseinstellung (`factory-snapshot.zip`) wiederherstellbar.
- [ ] Pre-Update-Snapshot von `update-vserver.sh` wird tatsächlich erzeugt und ist lesbar.
- [ ] SQLite-DB (Sessions/Memory/RAG/Quality/Eval) ist gesichert + wiederherstellbar.
- [ ] Backup-Stand/Frequenz dokumentiert (wo liegen Backups, wie alt, wer prüft?).

### T9 🟡 Betrieb bei Webseiten-Umzug
Bei Wechsel der WLO-Webseite: `base_host`, `REPO_BASE_URL`, Wissens-URLs neu schreiben +
Sitemap-Abgleich (→ T5). Web-Tour-Ziele und Karten-Links erneut prüfen.

---

## Teil 4 — Offene Entscheidungen
- [ ] Welche Persona×Intent-Kombinationen sind **launch-kritisch** (Abdeckungs-Matrix priorisieren)?
- [ ] `canonical_url`: Pflichtfeld ab wann, wie gepflegt?
- [ ] Feedback-Daten: Speicherumfang & Datenschutz-Klasse?
- [ ] Rate-Limit-Schwellen?
- [ ] Widget-Position: feste Snap-Punkte oder freies Drag-&-Drop?
- [ ] Backup: Frequenz, Aufbewahrung, Verantwortliche:r?
- [ ] Zielmodell (T6) für Klassifikation vs. Antwort?

---

## Anhang

### Anhang 1 — URL-Muster-Referenz (Soll)

| Inhaltstyp | Korrekte URL-Form (Staging) |
|---|---|
| Sammlung | `https://repository.staging.openeduhub.net/edu-sharing/components/collections/<id>` |
| Material / Inhalt | `https://repository.staging.openeduhub.net/edu-sharing/components/render/<nodeId>` |
| Suche (Treffer-Button) | `https://repository.staging.openeduhub.net/edu-sharing/components/search?query=<term>` |
| Themenseite | WLO-Themenseiten-URL (`topic_page_url` aus Metadaten) |
| Webseite / Mitmachen | `https://wp-test.wirlernenonline.de/...` bzw. `/mitmachen/` |
| Session-Bridge | Alle Trusted-Host-Links zusätzlich mit `?bsid=<sessionId>` |

Repo-Host hängt von `REPO_BASE_URL` ab (Staging = `repository.staging.openeduhub.net`; Prod = `redaktion.openeduhub.net`).

### Anhang 2 — Protokoll-Vorlage je Durchlauf

| Datum | Build/Commit | Umgebung | Modell | Ablauf | Tester | Tonalität | Angebote | Ziel | Score | Bestanden? | Notizen |
|---|---|---|---|---|---|---|---|---|---|---|---|
|  |  | Staging |  | GS-1 |  |  |  |  |  |  |  |
