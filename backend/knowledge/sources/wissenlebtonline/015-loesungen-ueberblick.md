---
id: wlo-loesungen-015
title: "WLO Lösungen, Produkte, Angebote — Open Source Infrastruktur für Bildungs- und Lerninhalte"
source: "https://wp-test.wirlernenonline.de/angebote/"
updated: 2026-04-21
license: "CC BY 4.0"
tags: [loesungen, angebote, ueberblick, erschliessen, pflegen, zeigen, verbreiten, crawler, themenseiten, bildungs-api, ki-assistent, widgets, lernpfad]
chunk_strategy: heading
brand_names: ["WissenLebtOnline", "WirLernenOnline", "WLO"]
cross_reference_for:
  - "005-infrastruktur-betreiber.md"
  - "008-plattform-module.md"
  - "016-wlo-data.md"
  - "017-lms-cms-connect.md"
  - "018-redaktionssoftware.md"
---

# WLO Lösungen, Produkte, Angebote

**Open Source Infrastruktur und Lösungen für Bildungs- und Lerninhalte —
denn Wissen lebt online, wenn es für Menschen und Maschinen zugänglich
ist.**

Das WLO-Angebot gliedert sich in vier Säulen, die den gesamten
Lebenszyklus redaktioneller Bildungsinhalte abdecken — von der
automatisierten Erschließung bis zur Verbreitung in Lernplattformen
und KI-Anwendungen.

## 1. Erschließe — Inhalte automatisiert sammeln und Metadaten generieren

Klassische Spider werden zunehmend durch **generische Crawler und
KI-Assistenten** ersetzt. Sie analysieren Webseiten und andere Quellen,
identifizieren relevante Inhalte und bereiten diese strukturiert auf.
Die Verschlagwortung erfolgt auf Basis gepflegter
**Metadatenvokabulare**.

Relevante Inhalte werden schneller gefunden, strukturiert und zugänglich
gemacht. So entstehen hochwertige, durchsuchbare Wissenssammlungen, die
sich effizient verbreiten und in unterschiedliche Anwendungen
integrieren lassen.

**Bausteine**:

- **Klassische Crawler** — quellen-spezifische Spider
- **Generischer Crawler** — Universal-Crawler für beliebige Webportale
- **Import-Schnittstellen** — OAI-PMH, REST
- **Föderierte Suchquelle** — Live-Anbindung fremder Bestände
- **Metadaten-Generatoren** — KI-gestützte Verschlagwortung
- **Metadaten-Vokabulare** — aktuelle Systematiken (SKOS, LOM)
- **Kompetenz-Raster** — für die pädagogische Zuordnung
- **Qualitäts-Prüfer** — automatisierte Sichtung
- **Datenraum** — zentrale Ablage
- **Daten verlinken** — Verknüpfungen zu Weltwissen und Lehrplänen
- **Bildungs-API und Services** — API-basierter Zugriff
- **Redaktionsprozesse** — definierte Workflows

## 2. Pflege — Inhalte in der Redaktionsumgebung

Für die Pflege von Wissens- und Lerninhalten wurde die **edu-sharing
Open-Source-Software** angepasst. Alle für Bildung relevanten
Inhaltearten können **erschlossen, erstellt, geordnet, geprüft** und in
präsentierbare Form gebracht werden.

Nach Anlegen eines Redaktionsteams können Inhalte mit Editoren
erstellt, hochgeladen, importiert oder gecrawlt werden. Zur Verwaltung
des Datenraums wird zuvor ein **Themenbaum** generiert; je Thema werden
Inhalte gesammelt und verschlagwortet. Das System generiert
**Themenseiten** für die öffentliche Präsentation auf Basis anpassbarer
Vorlagen.

Veröffentlichte Inhalte stehen in einer **Suchmaschine**, in
**Themenseiten** und via **Schnittstellen** zur Verfügung.

**Bausteine**:

- **Redaktionsteam verwalten** — Rollen, Einschreibung
- **Datenraum der Redaktion** — strukturierte Ablage
- **Upload Content** — teilautomatisiert
- **Generischer Crawler** — Erschließung fremder Quellen
- **Qualitäts-Prüfer** und **KI-Metadaten** — automatisierte Vorschläge
- **Editoren / Content erstellen** — Inhalte direkt im System erzeugen
- **Themenbaum** — hierarchische Struktur
- **Themenseiten & Vorlagen** — Schaufenster-Generator
- **Füllstands-Übersichten** — Monitoring offener Themen
- **Suchen, Sammeln** — quellenübergreifend
- **Community-Kooperationen** — Inhalte teilen zwischen Redaktionen

Details: **018-redaktionssoftware.md**.

## 3. Zeige — Präsentationen und Statistiken

Veröffentlichte Ergebnisse der Redaktionsarbeit werden über eine
**Suchmaschine** und **automatisch generierte Themenseiten**
zugänglich gemacht. **Widgets** der Themenseiten sowie komplette Seiten
können per **Embedding** auf anderen Webseiten integriert werden — so
verbreiten sich Sammlungen schnell in der Zielgruppe.

**Proof of Concepts** zeigen, welche Mehrwertfunktionen auf Basis
kuratierter Redaktionssammlungen möglich sind:

- **KI-Suchassistent**
- **Lernpfad-Generator** (POC)
- **Lerninhalte-Generator**
- **Binnendifferenzierungs-Assistent** — wissenschaftlich fundiertes
  Binnendifferenzierungswissen zur Adaption von Lerninhalten

Mit **statistischen Übersichten** werden Bestände und Wachstum sichtbar.
Die Internetgemeinschaft kann mit der Redaktion kommunizieren und
Inhalte einreichen.

**Bausteine**:

- **Themenseiten** — generiert aus Vorlagen
- **Widgets & Embedding** — einbettbar in Drittsysteme
- **Themenbaum** — Navigation über die Themenhierarchie
- **Such-Funktion** — Volltext- und Metadatensuche
- **Such-KI-Assistent** — semantische Assistenz
- **Lernpfad-Generator** (POC)
- **Binnendifferenzierungs-Assistent**
- **Lerninhalte generieren**
- **OER-Statistik** — siehe **012-oer-statistik.md**
- **Quellen-Bestände**
- **Content bei Redaktion einreichen** — Community-Beitrag

## 4. Verbreite — überall, wo gelernt wird

Redaktionelle Wissens- und Inhaltebestände verbreiten sich nicht nur
über das Portal der Redaktion. Sie gelangen auch über **Schnittstellen
und Integrationen** in die breite Bildungspraxis. Außerdem können die
Daten für **KI-Trainings** bereitgestellt werden, wenn die Redaktion mit
Entwicklern von KI-Assistenten und anderen Softwaretools kooperiert.

Für alle gängigen Lernplattformen ist die Integration via
**LTI-Schnittstelle** oder **Plugin** möglich. Auch einige **WebCMS**
können Inhalte auf diesem Weg nachnutzen. **Nutzungsaktionen** werden
datenschutzkonform als Feedback für Autor:innen und Redaktionen
gezählt. **Suchmaschinen** können die Daten importieren oder föderiert
nutzen.

**Bausteine**:

- **Widgets & Embedding** — in beliebige Webseiten
- **Lernplattformen anbinden** — Moodle, ILIAS, dBildungscloud, OpenOlat
- **WebCMS anbinden** — WordPress, MediaWiki, Drupal
- **Editoren anbinden** — OnlyOffice, MediaWiki, Serlo, Geogebra
- **Daten für Suchmaschinen** — OAI-PMH / REST
- **Föderierte Suchquelle** — Live-Abfrage
- **Lerndaten für KI-Assistenten** — WLO Data
- **KI-Qualitätssicherung** — Trainings- und Evaluationsdaten
- **Binnendifferenzierungs-Service**
- **Browser-Plugin für Redaktionen**
- **Browser-Plugin für Lehrkräfte**

Details: **017-lms-cms-connect.md** und **016-wlo-data.md**.

## Querverweise

- **016-wlo-data.md** — Daten für Bildungsanwendungen und KI-Training
- **017-lms-cms-connect.md** — LMS/WebCMS/Editor-Anbindung im Detail
- **018-redaktionssoftware.md** — Redaktionssoftware in drei Varianten
- **008-plattform-module.md** — zentrale Modul-Referenz
- **005-infrastruktur-betreiber.md** — Hosting, GWDG, Bildungs-API

## Kontakt

- **E-Mail**: info@WissenLebtOnline.de
- Newsletter und Mitmachangebote: **009-newsletter-und-kontakt.md**
