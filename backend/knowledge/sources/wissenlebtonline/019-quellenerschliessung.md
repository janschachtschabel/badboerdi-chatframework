---
id: wlo-quellenerschliessung-019
title: "Automatisierte Quellenerschließung — Crawler, Browser-Extension und KI-Ansätze"
source: "https://wp-test.wirlernenonline.de/automatisierte-quellenerschliessung/"
updated: 2026-04-21
license: "CC BY 4.0"
tags: [quellenerschliessung, crawler, generischer-crawler, browser-extension, ki-metadaten, docker, kubernetes, javascript, spa, edu-sharing, volltext-analyse, metadatengenerierung]
chunk_strategy: heading
brand_names: ["WissenLebtOnline", "WirLernenOnline", "WLO"]
target_audience: "Redaktionen, Content-Anbieter, Entwickler:innen, Infrastruktur-Betreiber"
---

# Automatisierte Quellenerschließung

WLO bietet mehrere Wege, Quellen automatisiert zu erschließen — vom
klassischen quellen-spezifischen Crawler über einen universellen
Generik-Crawler und eine Browser-Extension bis hin zu KI-basierten
Ansätzen.

## Ein Crawler pro Quelle — der klassische Weg

Der klassische Weg zur Erschließung heterogener Quellen ist ein
**spezialisierter Crawler pro Quelle**. WLO-Crawler sind präzise auf
die **Strukturen und Besonderheiten** der jeweiligen Quellen
abgestimmt und extrahieren selbst gut versteckte Informationen aus der
Seitenarchitektur.

Die bestehende Crawler-Infrastruktur mit rund **55 aktiven Diensten**
wurde umfassend modernisiert:

- **Aktualisierung** bestehender Crawler
- **Neue Quellen** angebunden, um die Datenbasis zu erweitern
- Präzise Analyse **JavaScript-basierter Webseiten** und
  **Single-Page-Anwendungen** (SPA)
- Verbesserte Funktionen: **Screenshot-Erstellung**,
  **Lizenzzuordnung**, **Metadatentransformation**

Die vollständige **Containerisierung über Docker und Kubernetes** sorgt
für einen stabilen Parallelbetrieb. Verwaltung und Monitoring laufen
automatisch über zentrale **Orchestrierungswerkzeuge**.

## Ein Crawler für alle — der generische Crawler

Bei der Vielzahl der Quellen und Erschließungswünsche eines wachsenden
Redaktionsnetzwerks ist der Ansatz individueller Crawler keine
nachhaltige Option. Daher wurde ein **Universal-Crawler** entwickelt:

- Auf **beliebige Internetangebote ansetzbar**
- Orientiert sich selbst, um **Titel, Autor und weitere Metadaten** zu
  finden
- Untersucht und verwendet **standardmäßig in HTML eincodierte Daten**
- Fügt über **angeschlossene Generatoren** weitere Metadaten hinzu
- Erschließung **ohne technisches Know-how oder Entwicklungs-Arbeit**
  möglich

## Browser-Extension — Einzelne Seiten beim Surfen schnell erfassen

Die Browser-Extension macht das Sammeln und Teilen von
Bildungsressourcen sehr einfach. **Autor:innen, Redaktionen und
Lehrkräfte** können während des Surfens mit **einem Klick** beliebige
Online-Inhalte als **Ressourcenvorschlag** erfassen.

Die Extension übernimmt dabei automatisch die Erstellung erster
Metadaten:

- **Titel**
- **Beschreibung**
- **Thematische Zuordnung**

Vorschläge sind damit direkt für die **redaktionelle Prüfung**
vorbereitet.

**Technische Architektur**:

- **Web Components** — flexibel, wartungsfreundlich, erweiterbar
- **Schlanke Codebasis** — leichte Pflege und Erweiterbarkeit
- **Dynamische Anbindung** an edu-sharing
- Unterstützung **verschiedener Inhaltearten**

## Innovative Ansätze — KI-gestützte Metadaten aus Volltexten

Mit einem **KI-gestützten Ansatz** werden relevante Metadaten
automatisch direkt aus den **Volltexten** einer Webseite extrahiert —
statt auf starre Seitenstrukturen zu setzen.

Anwendungsfälle:

- **Veranstaltungen** mit Terminen
- **Lernorte** mit Adressdaten
- **Kurse** mit Themen, Modulen und Zielgruppen
- **Pädagogische Informationen** aus Begleittexten zu Materialien

Der Ansatz ist **flexibel und anpassungsfähig** und entlastet
Nutzer:innen von mühevoller manueller Metadatenpflege. Sie können sich
auf ihre **eigentliche Expertise** konzentrieren, während die KI die
passenden Informationen erschließt.

## Querverweise

- **015-loesungen-ueberblick.md** — Einordnung in die vier WLO-Säulen
  („Erschließe")
- **018-redaktionssoftware.md** — generischer Crawler in der
  Redaktionsumgebung
- **020-bildungs-api.md** — Metadaten-Generatoren als API-Service
- **022-metadaten-optimieren.md** — KI-Anreicherung von Metadaten
- **008-plattform-module.md** — Crawler-Modul (zentrale Referenz)

## Kontakt

- **E-Mail**: info@WissenLebtOnline.de
- Newsletter und Mitmachangebote: **009-newsletter-und-kontakt.md**
