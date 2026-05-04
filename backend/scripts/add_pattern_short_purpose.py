"""
One-shot script: insert `short_purpose:` field into all pattern .md files.

Each pattern gets a 1-2 sentence "WANN: ... WOFÜR: ..." description that
lands in the classifier prompt as a compact pattern hint. Re-running is safe:
files that already have `short_purpose:` are skipped.

Source of truth for the descriptions is the dict below. To update a single
pattern's hint later, edit the .md file directly.

Usage:
    python add_pattern_short_purpose.py
"""

from __future__ import annotations
import re
import sys
from pathlib import Path

SHORT_PURPOSES: dict[str, str] = {
    "pat-01-direkt-antwort.md":
        "WANN: User signalisiert Ungeduld/Effizienz und stellt eine direkt beantwortbare Frage. WOFÜR: Max. 2 Sätze + Gesprächshaken, kein Smalltalk.",
    "pat-02-gefuehrte-klaerung.md":
        "WANN: User formuliert vage und liefert nicht genug Info für eine konkrete Antwort/Suche (Slot-Lücken). WOFÜR: 1-2 gezielte Rückfragen mit konkreten Optionen, statt offen wirken zu lassen.",
    "pat-03-transparenz-beweis.md":
        "WANN: Nutzer fragt nach Daten/Stats/Bewertungen, die der Bot NICHT haben kann (interne Schul-/Klassen-Daten, Privates, externe Reports). WOFÜR: Ehrlich sagen 'habe ich nicht', sinnvolle Adjacent-Daten als Alternative anbieten.",
    "pat-04-inspiration-opener.md":
        "WANN: Erst-Begegnung mit der Plattform, User fragt offen 'Was kann ich hier?' WOFÜR: Inspirations-Beispiele aus 2-3 Bereichen zeigen, statt Plattform-Theorie zu erklären.",
    "pat-05-profi-filter.md":
        "WANN: Erfahrene Lehrkraft sucht Material mit konkreten Filter-Kriterien (Fach, Stufe, Medientyp, Lizenz). WOFÜR: Mehrstufige Filter-Pipe abarbeiten und kuratiertes Set zurückgeben.",
    "pat-06-degradation-bruecke.md":
        "WANN: Anfrage liegt am Rand/außerhalb der Bot-Domäne (Bildung/OER/WLO) ODER Slot fehlt strukturell. WOFÜR: Sanfte Domain-Brücke — sagen was nicht geht und Rückführung auf Bildungs-Adjacent.",
    "pat-07-ergebnis-kuratierung.md":
        "WANN: Suche hat viele Treffer (>5), User braucht Kurations-Hilfe. WOFÜR: Top-3 nach Relevanz + Diversitäts-Kriterium auswählen, jedes mit kurzer Begründung warum.",
    "pat-08-null-treffer.md":
        "WANN: MCP-Suche zu konkretem Thema lieferte 0 oder unbrauchbare Treffer. WOFÜR: Re-Search mit gelockerten Filtern, dann 2-3 alternative Wege anbieten.",
    "pat-09-redaktions-recherche.md":
        "WANN: Redaktion/Presse/Politik/Beratung sucht Material/Fakten für eigene Publikationen. WOFÜR: MCP-Suche durchführen, zitierfähige Quellenangaben, sachliche Aufbereitung — kein didaktisches Anpreisen.",
    "pat-10-fakten-bulletin.md":
        "WANN: Faktenfrage von Verwaltung/Politik/Presse mit Statistik-/Reporting-Bedarf (INT-W-09 oder INT-W-06 mit Zahlen). WOFÜR: Bullet-Liste mit Eckdaten, Quellenhinweis, ohne Marketing-Sprech.",
    "pat-11-nachfrage-schleife.md":
        "WANN: Vorherige Antwort war nicht verstanden oder unklar formuliert (User fragt nach). WOFÜR: Aufhellen statt wiederholen — anderes Beispiel, anderes Format, kürzer.",
    "pat-12-ueberbrueckungs-hinweis.md":
        "WANN: Bot kann gerade nicht direkt antworten (z.B. Tool-Lag, Backend-Issue, Crawl-Wartezeit). WOFÜR: Kurzer Status-Hinweis + Schätzdauer + Alternative, damit User nicht im Leeren wartet.",
    "pat-13-schritt-fuer-schritt.md":
        "WANN: Schüler:in oder Eltern stehen einer Lern-/Verstehens-Aufgabe ratlos gegenüber (INT-W-03b/c oder 08/12, Signale: unsicher/unerfahren). WOFÜR: Kleine sequenzielle Schritte mit je einer Frage/Aktion statt Komplettlösung.",
    "pat-14-eltern-empfehlung.md":
        "WANN: Eltern (P-ELT) suchen Material/Empfehlung für ihr Kind (INT-W-01/02/03a-c/06/08/10). WOFÜR: 2-3 vertrauenswürdige Material-Empfehlungen mit Kindorientierung, kein didaktischer Jargon.",
    "pat-15-analyse-ueberblick.md":
        "WANN: Profi-Persona (Verwaltung/Politik/Presse/Redaktion/Beratung/Lehrkraft) braucht analytischen Überblick zu Plattform/Statistik/Faktenfrage (INT-W-01/06/09). WOFÜR: Strukturierte Analyse aus RAG-Wissen, ohne Material-Suche.",
    "pat-16-themen-exploration.md":
        "WANN: User möchte ein Thema entdecken/erkunden, hat aber noch keinen konkreten Lerngegenstand. WOFÜR: 3-5 Sub-Themen anbieten als Drilldown-Optionen, kein Material-Bombardement.",
    "pat-17-sanfter-einstieg.md":
        "WANN: Erst-Begegnung mit dem Bot, User wirkt zögerlich oder leicht überfordert. WOFÜR: Warm anfangen, EINE konkrete Mini-Frage als Einstiegsangebot, kein langer Begrüßungs-Monolog.",
    "pat-18-unterrichts-paket.md":
        "WANN: Lehrkraft braucht ein KOMPLETTES Material-Bundle für eine Stunde/Reihe (kein Single-Item). WOFÜR: Gepacktes Set aus Einstieg + Aufgaben + Vertiefung mit klarer Zeit-Struktur.",
    "pat-19-unterrichts-lernpfad.md":
        "WANN: Lehrkraft (P-W-LK) plant strukturiert einen Lernpfad/Stundenentwurf zu konkretem Thema (INT-W-10 oder INT-W-03b mit Plan-Sprache). WOFÜR: Sequenzieller Lernpfad mit MCP-Materialien an passenden Stellen.",
    "pat-20-orientierungs-guide.md":
        "WANN: User fragt offen nach Plattform-Möglichkeiten oder Themenseiten (INT-W-03a oder generic Orientierung). WOFÜR: Strukturierter Guide durch verfügbare Themenseiten/Sammlungen, mit Klick-Pfaden.",
    "pat-21-canvas-create.md":
        "WANN: User will explizit ein NEUES Material erstellt bekommen (INT-W-11, Verben: erstelle/generiere/bau/schreib mir). WOFÜR: KI-Generation eines strukturierten Material-Markdowns im Canvas-Bereich.",
    "pat-22-feedback-echo.md":
        "WANN: User gibt Feedback zur Bot-Antwort/Plattform-UX (INT-W-04). WOFÜR: Feedback bestätigend wiedergeben, danken, ggf. Routing zur Redaktion anbieten.",
    "pat-23-redaktions-routing.md":
        "WANN: User meldet Fehler/Lücke, möchte Material einreichen oder an Redaktion weiterleiten (INT-W-05). WOFÜR: Klares Routing zur richtigen Stelle mit Erwartungs-Management.",
    "pat-24-download-hinweis.md":
        "WANN: User will ein konkretes Material runterladen oder öffnen (INT-W-07). WOFÜR: Download-Link explizit nennen, plus Lizenz-Hinweis und ggf. Alternative bei DRM-Schutz.",
    "pat-25-canvas-edit-dialog.md":
        "WANN: Canvas-Inhalt existiert und User möchte ihn ändern/verfeinern (INT-W-12, state-12). WOFÜR: Edit-Anweisung auf das vorhandene Markdown anwenden, Ergebnis im Canvas updaten.",
    "pat-26-fachportale-uebersicht.md":
        "WANN: User fragt nach ALLEN verfügbaren Fachportalen/Schulfächern als Übersicht (INT-W-13, Plural-Frage). WOFÜR: get_subject_portals aufrufen und Karten-Liste der Top-Level-Fachportale rendern.",
    "pat-27-themen-drilldown.md":
        "WANN: User will Sub-Themen/Bereiche eines KONKRETEN Fachs/Sammlung sehen (INT-W-14, Singular-Fach + Drilldown-Verb). WOFÜR: browse_collection_tree für die Sub-Sammlungen, NICHT Material-Suche.",
    "pat-crisis-empathie.md":
        "WANN: Krisensignale in der Anfrage (Suizid, Selbstverletzung, akute psychische Not) — durch Safety-Layer enforced. WOFÜR: Empathische Antwort + Hilfsnummern (Telefonseelsorge etc.), keine Bildungs-Antwort.",
    "pat-refuse-threat.md":
        "WANN: Drohung/Verbalattacke/Bedrohung in der Anfrage — durch Safety-Layer enforced. WOFÜR: Klare Zurückweisung ohne Eskalation, Hinweis auf Hausordnung/Meldewege.",
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    here = Path(__file__).resolve().parent
    patterns_dir = here.parent / "chatbots" / "wlo" / "v1" / "03-patterns"
    if not patterns_dir.exists():
        print(f"ERR: patterns dir not found: {patterns_dir}")
        return 1

    edited = 0
    skipped = 0
    failed = 0
    for fname, sp in SHORT_PURPOSES.items():
        path = patterns_dir / fname
        if not path.exists():
            print(f"SKIP (missing file): {fname}")
            failed += 1
            continue
        text = path.read_text(encoding="utf-8")
        if "short_purpose:" in text:
            print(f"SKIP (already set): {fname}")
            skipped += 1
            continue
        # Insert after `label:` line, before next field
        new_text, n = re.subn(
            r"^(label:[^\n]+)\n",
            rf'\1\nshort_purpose: "{sp}"\n',
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if n != 1:
            print(f"FAIL (label-line not found): {fname}")
            failed += 1
            continue
        path.write_text(new_text, encoding="utf-8")
        edited += 1
        print(f"  + {fname}")

    print(
        f"\nEdited {edited}, skipped {skipped}, failed {failed} "
        f"(of {len(SHORT_PURPOSES)} patterns).",
    )
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
