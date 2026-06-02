---
element: knowledge
variant: platform
id: knowledge.wlo-plattform
layer: 2
priority: 800
version: "2.0.0"
---

# WLO — Plattform-Wissen

> Quelle: https://wp-test.wirlernenonline.de/ (Stand 03/2026)
> Details/Volltext via RAG (`wirlernenonline.de-webseite` etc.).

## Was ist WLO?
"Wissen Lebt Online" (WLO, ehemals WirLernenOnline) — **offene Infrastruktur
für Bildung**: erschließt, verschlagwortet und verbreitet Bildungsinhalte
mit KI. Kein einzelnes Produkt, sondern Ökosystem (Infrastruktur, Standards,
Datenräume, Services, Community).

Redaktionssoftware **edu-sharing** = Open Source, im Einsatz in 10
Bundesländern + Schweiz.

## Kernzahlen (zitierfähig)
- 400.000+ erschlossene Bildungsinhalte
- 316.865 Inhalte in der WLO-Suche
- 25.178 geprüfte Inhalte in 2.970 Themensammlungen
- 29 Fachportale mit ~3.500 Themenseiten
- 170.000 OER in DE (2025, Verdreifachung seit 2022): HS 102.643 / Schule 61.775 / Berufl. 7.820 / Elementar 915

OER-Statistik: https://wp-test.wirlernenonline.de/oer-statistik/

## Träger
- **GWDG** — leitet Projekt, betreibt Infrastruktur (ISO 27001, DIN EN ISO 9001)
- **edu-sharing.net e.V.** — initiierte WLO, Verein
- **metaVentis GmbH** — entwickelt edu-sharing-Software

## Kontakt
- Jason Mansour (IT, KI-Infra) / Anna-Lisa Neuenfeld (Community, Presse) / Matthias Hupfer (Entwicklung)
- info@WissenLebtOnline.de

## 6 Zielgruppen
Redaktionen | Contentanbieter | OER-Community | Infrastruktur-Betreiber | Softwarehersteller | Politik/Rahmensetzer

## Souveränität
GWDG-Rechenzentrum Göttingen, KI-Modelle lokal, Daten in DE, ISO 27001.
Open Source, CC BY 4.0 für Inhalte.

## Filter-Logik (wichtig für Bot)
WLO filtert auf **Bildungsstufen-Ebene** (`educationalContext`):
Grundschule / Sek I / Sek II / Berufliche Bildung / Hochschule / Erwachsenenbildung.
Klassenstufen (z.B. "Klasse 6") **intern still mappen**, nicht nachfragen.

Weitere Filter: `discipline` (Fach), `lrt` (Ressourcentyp), `license`, `userRole`, `targetGroup`.

## FAQs (Kurz-Antworten)

**„Was kann ich hier?"** Nach Lernmaterial suchen — Thema eingeben, WLO zeigt Videos, Arbeitsblätter, Übungen.

**„Muss ich mich anmelden?"** Nein — Suche ohne Account, sofort nutzbar.

**„Sind die Materialien kostenlos?"** Die meisten ja (OER, CC BY 4.0). Bei manchen ist Anmeldung auf Originalseite nötig (wird angezeigt).

**„Was sind Themenseiten?"** Kuratierte Schaufenster pro Thema mit den besten geprüften Materialien. 29 Fachportale × ~50–200 Themenseiten.

**„Wie wird geprüft?"** Mehrstufig: Basis-Sichtung durch Redakteur:innen → KI-Erschließung → Stichproben vor Freigabe.

**„Eigenes Material einreichen?"** Über `https://wp-test.wirlernenonline.de/mitmachen/inhalt-vorschlagen/?type=quelle#esform`

## Relevante URLs
- Startseite: https://wp-test.wirlernenonline.de/home/
- Bildungsinhalte / Fachportale: https://wp-test.wirlernenonline.de/bildungsinhalte/
- Redaktionen: https://wp-test.wirlernenonline.de/redaktionen/
- Mitmachen: https://wp-test.wirlernenonline.de/mitmachen/
- FAQ: https://wp-test.wirlernenonline.de/faq/
- Suche: https://suche.wp-test.wirlernenonline.de/search/de/search
