# BadBoerdi-Chatbot — Skalierbarkeit: Zusammenfassung für die Leitung

*Stand: 2026-06-15 · Grundlage: Studio-Lasttests `lt-e91ef209c1d6` (vorher) und `lt-e36f1e7401e8` (nach Optimierung), Testmaschine 8 physische / 16 logische CPU-Kerne.*

## 1. Skaliert das System fehlerfrei bis 32 gleichzeitige Zugriffe?

**Ja.** Im Lasttest bis 32 parallele Nutzer (Stufen 8/16/32, gemischte Anfragen):
- **0 Fehler**, Antwortzeit p95 ≤ 17 s (unter der 20-s-Zielschwelle).
- **Durchsatz steigt** mit der Last (1,0 → 1,56 → 1,86 Anfragen/s) — kein Einbruch.
- Die tatsächliche Obergrenze liegt **oberhalb von 32** (Messwerkzeug deckelt bei 32; CPU hatte noch Reserve).

> Hinweis: Ein erster Lauf *vor* der Optimierung kollabierte bei 32 (Ausreißer bis 85 s, Durchsatz −5×). Ursache war eine CPU-Überlastung im Reranker (siehe Punkt 4), die behoben wurde.

## 2. Empfohlene vServer-Hardware

| Ressource | Minimum | Empfohlen | Begründung |
|---|---|---|---|
| **CPU** | 4 vCPU | **8 vCPU** | Hauptengpass; 8 Kerne trugen 32 parallel mit Reserve |
| **RAM** | 4 GB | **8 GB** | Messung 1,5 GB Spitze; Puffer für mehrere Worker |
| GPU | — | — | nicht nötig (Reranker läuft effizient auf CPU) |
| Disk | wenige GB SSD | SSD | lokale SQLite-DB + Modelldateien |

- Mit **4 vCPU** läuft 32 ebenfalls fehlerfrei, such-/lernpfad-lastige Spitzen warten nur etwas länger.
- Ein einzelner Backend-Prozess reicht für diese Last; auf 8 GB sind später 2–3 Prozesse für höhere Lasten möglich.

## 3. Was limitiert am ehesten?

1. **CPU-Kerne (stärkster Hebel für Gleichzeitigkeit).** Der KI-Reranker, der Suchergebnisse sortiert, ist CPU-gebunden. Seine Parallelität skaliert mit der Kernzahl — mehr Kerne = mehr gleichzeitige Such-Anfragen.
2. **Externe KI-/Suchdienste (Antwortzeit pro Anfrage).** Die 7–8 s pro Anfrage entstehen fast vollständig durch Wartezeit auf das Sprachmodell (B-API) und den WLO-Suchdienst — nicht durch eigene Hardware. Das ist der Komfort-Boden, lokal nicht beschleunigbar, aber **keine** Skalierungsgrenze.
3. **RAM / Datenbank: unkritisch** (siehe Punkt 5).

## 4. Trade-off: 1 vs. alle CPU-Kerne im Reranker (ONNX)

Der Reranker kann pro Sortier-Vorgang **einen** oder **alle** Kerne nutzen:
- **Alle Kerne:** einzelner Vorgang schnell (~95 ms), **aber** bei vielen gleichzeitigen Nutzern kämpfen alle um dieselben Kerne → Überbuchung, Durchsatz-Kollaps, Ausreißer bis 85 s.
- **Ein Kern (jetzt aktiv) + Deckelung auf Kernzahl:** einzelner Vorgang langsamer (~299 ms, +200 ms), **aber** viele laufen sauber parallel.

**Ergebnis der Umstellung:** Spitzen-Antwortzeit bei 32 Nutzern von 85 s auf 17 s gesenkt, Durchsatz verfünffacht, 0 Fehler. Die +200 ms pro Vorgang fallen gegen die 7–8 s Gesamt-Antwortzeit nicht ins Gewicht (~3 %). **Bewusster, lohnender Tausch zugunsten der Mehrnutzer-Stabilität.**

## 5. Hatte die Datenbank erkennbare Auswirkungen?

**Nein.** Die lokale SQLite-Datenbank (inkl. Vektorsuche) zeigte unter Last **keine** messbare Bremswirkung: keine Fehler, kein I/O-Engpass, RAM-Verbrauch stabil bei ~1,5 GB. Die Antwortzeiten werden von den externen Diensten und der CPU bestimmt, nicht von der DB. Für das aktuelle Schreibaufkommen ist SQLite ausreichend; ein Wechsel auf einen DB-Server ist erst bei deutlich höherer Last oder Mehr-Server-Betrieb nötig.

## 6. MCP-Suchdienst selbst hosten (statt Vercel)

Der WLO-Suchdienst (MCP) läuft aktuell extern bei Vercel. Optionen, ihn auf eigene Infrastruktur zu holen:

- **A) Sidecar-Container neben dem Chatbot (empfohlen):** gleicher Server, interne Verbindung. **Vorteile:** keine externen Ausfälle/Verzögerungen, Suchanfragen verlassen die eigene Infrastruktur nicht (Datenschutz/DSGVO), gemeinsames Deployment. **Kosten:** teilt sich CPU/RAM mit dem Chatbot — ca. **+1 Kern, +0,3–0,5 GB RAM** in die Dimensionierung einplanen.
- **B) Eigener kleiner Dienst/VM:** unabhängig skalier- und wiederverwendbar (auch für andere Clients), minimaler Netz-Mehraufwand.
- **C) In denselben Prozess integrieren:** **nicht empfohlen** (zwei Laufzeiten, aufgeblähtes Image, gekoppelte Updates).

> Wichtig: Die Hauptwartezeit der Suche entsteht beim dahinterliegenden WLO-Repository und bleibt in allen Varianten gleich. Der Gewinn liegt in **Unabhängigkeit, Datenschutz und Wegfall von Vercel-Limits**, nicht primär in der Geschwindigkeit.

---

**Fazit:** Bis 32 gleichzeitige Nutzer fehlerfrei und stabil — mit einem **8-vCPU / 8-GB-vServer** mit komfortabler Reserve. Begrenzend ist die CPU-Kernzahl (für den Reranker); die Datenbank ist unkritisch. Ein eigener MCP-Dienst ist als Sidecar gut machbar und sollte mit ~1 Kern / ~0,5 GB in die Dimensionierung einfließen.
