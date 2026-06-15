# Bereich `faq` — Häufig gestellte Fragen der Zielgruppen

Dieser Bereich sammelt **zielgruppenspezifische FAQ-Einträge** für den Assistenten.
Im Unterschied zu den anderen Bereichen (Plattform-, Projekt-, Produkt-Dokumentation)
sind die Einträge hier **frage-zentriert** und typischerweise kurz:
eine konkrete Nutzerfrage plus eine präzise, direkt verwertbare Antwort.

- **Slug**: `faq`
- **Mode**: `on_demand` (wird erst bei FAQ-artigen Anfragen aktiviert)
- **Sprache**: primär Deutsch
- **Lizenz**: CC BY 4.0 (sofern nicht anders angegeben)

## Vorgeschlagene Ordnung der Dateien

Wir ordnen nach **Zielgruppe**, damit eine Anfrage vom Assistenten
schnell der passenden Rolle zugeordnet werden kann. Pro Zielgruppe
eine Datei mit mehreren Frage/Antwort-Paaren (Paragraph-Chunking).

| Datei | Zielgruppe | Typische Fragen |
|---|---|---|
| `001-lehrende.md` | Lehrende / Dozierende | "Wie finde ich OER zu einem Lehrplanthema?", "Wie binde ich edu-sharing in meinen Moodle-Kurs ein?" |
| `002-lernende.md` | Lernende / Studierende | "Wo finde ich freie Übungsmaterialien?", "Darf ich OER für meine Hausarbeit weiterverwenden?" |
| `003-autorinnen.md` | OER-Autor:innen | "Welche CC-Lizenz passt zu meinem Material?", "Wie lade ich ein Material hoch und attribuiere korrekt?" |
| `004-redaktionen.md` | Redaktionen / Fachredaktionen | "Wie starte ich eine WLO-Fachredaktion?", "Welche Qualitätskriterien gelten?" |
| `005-content-anbieter.md` | Content-Anbieter / Quelleninhaber | "Wie wird meine Quelle angebunden (OAI-PMH / Crawler)?", "Was erwartet WLO an Metadaten?" |
| `006-betreiber.md` | Betreiber / IT-Services / Rechenzentren | "Wie installiere ich edu-sharing per Docker?", "LDAP/Shibboleth-Anbindung?" |
| `007-entwicklerinnen.md` | Entwickler:innen | "Wo ist die REST-API-Doku?", "Wie trage ich auf GitHub bei?" |
| `008-politik-und-foerderer.md` | Politik / Ministerien / Fördermittelgeber | "Wie ist WLO finanziert?", "Wie passt WLO zur OER-Strategie?" |
| `009-oer-grundlagen.md` | Allgemein / Einsteiger:innen | "Was ist OER?", "Was ist der Unterschied zu OEP?" |
| `010-ki-und-datenschutz.md` | KI-Interessierte / Datenschutzfragende | "Welche Inhalte werden für KI-Training verwendet?", "Wo wird gehostet?" |

> Die Nummerierung ist ein Vorschlag — Dateien können nach Bedarf hinzugefügt
> oder umgegliedert werden. Wichtig ist das **frage-zentrierte Format**.

## Empfohlenes Datei-Format

```markdown
---
id: faq-<zielgruppe>-<NNN>
title: "FAQ für <Zielgruppe>"
source: "<URL oder manuell>"
updated: YYYY-MM-DD
license: "CC BY 4.0"
attribution: "<Quelle>"
tags: [faq, <zielgruppe>, ...]
chunk_strategy: paragraph
lang: de
status: active
---

# FAQ für <Zielgruppe>

## Frage 1: <konkrete Nutzerfrage>

<Antwort in 2–6 Sätzen, ggf. mit Link auf ausführliche Dokumente aus anderen Bereichen.>

## Frage 2: ...
```

## Wann welchen Eintrag nehmen?

- **FAQ-Eintrag** → wenn Nutzer eine **konkrete, wiederkehrende Frage** stellt, die sich in 1–2 Absätzen beantworten lässt.
- **Detail-Dokument** in `wissenlebtonline/`, `edu-sharing-com/` etc. → wenn **ausführliche Dokumentation** oder **Referenz** benötigt wird.

FAQ-Einträge sollen bei Bedarf **auf Detail-Dokumente verlinken**, statt Inhalte zu duplizieren.
