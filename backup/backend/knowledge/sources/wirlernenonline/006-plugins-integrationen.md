---
id: wlo-alt-plugins-006
title: "WLO Plug-ins und Plattform-Integrationen (Legacy)"
source: "https://wirlernenonline.de/plugins/"
updated: 2025-01-01
license: "CC BY 4.0"
attribution: "edu-sharing.net e.V. — WLO / edu-sharing Open Source"
tags: [wirlernenonline, wlo, plugins, integration, moodle, ilias, openolat, opal, mahara, wordpress, typo3, mediawiki, onyx, onlyoffice, edu-sharing, lms, cms, metadaten-mapping, lizenzangaben-automatisch, landesmediensammlungen]
chunk_strategy: paragraph
lang: de
status: legacy
---

# WLO Plug-ins

**URL**: <https://wirlernenonline.de/plugins/> | **Lizenz**: CC BY 4.0 | **Technologische Basis**: edu-sharing Open Source

---

## Grundprinzip: Metadaten frei, Inhalte bei den Quellen

> WirLernenOnline.de stellt **gesammelte und qualitativ geprüfte Metadaten frei zur Verfügung**. **Die Inhalte bleiben bei den Quellen.**

### Selektiver Inhalte-Pool-Abruf

> **Länder, Schulen und andere Partner** können selektiv bestimmte Inhalte-Pools abrufen und dabei Metadaten auf **eigene Strukturen mappen**.

### Zweiwege-Integration

- **WLO-Inhalte in deine Plattform** einbinden (über Plug-ins)
- **Eigene Inhalte deiner Plattform** bei WLO bereitstellen (über Schnittstellen)
- → Links gelangen in alle angeschlossenen Plattformen und in **Landesmediensammlungen**

---

## Unterstützte Plattformen

### e-Learning-Systeme (LMS)

| Plattform | Status |
|---|---|
| **Moodle** | Dokumentation verfügbar |
| **ILIAS** | Plug-in verfügbar |
| **OpenOlat** | Plug-in verfügbar |
| **Opal** | Plug-in verfügbar (mit `*` markiert) |
| **Mahara** | Plug-in verfügbar |

### Weitere Plattformen (CMS + Office)

| Plattform | Status |
|---|---|
| **WordPress** | Plug-in verfügbar |
| **Typo3** | Plug-in verfügbar |
| **MediaWiki** | Plug-in verfügbar (mit `*` markiert) |
| **Onyx** | Plug-in verfügbar |
| **OnlyOffice** | Plug-in verfügbar (mit `*` markiert) |

> **Hinweis**: Dokumentation aktuell nur für **Moodle** auf der Seite einsehbar. Für andere Plug-ins: **per Anfrage**.

---

## Moodle-Plug-in (Referenz-Implementierung)

### Funktionalität

> Die WirLernenOnline-Suche wird direkt in deiner Moodle-Plattform verfügbar. Gefundene Lerninhalte kannst du mit **wenigen Klicks in Kursseiten einbetten**.

### Automatische Lizenzangaben

> Die rechtlich vorgeschriebenen **Urheber- und Lizenzangaben ergänzt das Plug-in automatisch**. Lehrenden und Lernenden erspart das viel Arbeit bei der Kursvorbereitung.

### Technologische Basis

> Wir nutzen für WirLernenOnline die **edu-sharing Open-Source-Software**. Daher startest du die WLO-Suche mit dem **edu-sharing-Symbol**.

**Verfügbarkeit der Such-Schaltfläche**:
- Im Editor der Moodle-Kursseiten
- An einigen anderen Stellen im System

### Dokumentation

Zwei Rollen getrennt:

- **Für Nutzende** (Lehrende, die Inhalte suchen und einbetten)
- **Für Admins** (Installation, Konfiguration)

---

## WordPress-Plug-in

> Weitere Dokumentation angekündigt (auf der Seite referenziert, Details per Anfrage).

---

## Anwendungsfälle

### Für Schulen

> Du möchtest das Angebot von WirLernenOnline in der **Lernplattform deiner Schule** nutzen? Binde die WLO-Suche und WLO-Inhalte ganz einfach als Plug-in in deine Lernplattform ein.

### Für Bundesländer / Bildungsinstitutionen

- Inhalte-Pools selektiv abrufen
- Eigene Metadatenstrukturen beibehalten (Mapping)
- Landesweite Bildungs-Infrastruktur mit WLO-Metadaten anreichern

---

## Querverweise

- `001-startseite.md` — WLO als Suchmaschine + Community
- `005-quellenerschliessung.md` — Wie Quellen in WLO kommen (Gegenrichtung zu Plug-ins)
- `wissenlebtonline/017-lms-cms-connect.md` — Aktualisierte LMS/WebCMS-Anbindung (4 Bundesländer / 9 Plattformen / 500 k User)
- `wissenlebtonline/018-redaktionssoftware.md` — edu-sharing + WLO-Software-Varianten
- `wissenlebtonline/020-bildungs-api.md` — Bildungs-API als moderner Integrationsweg

## Einordnung

Diese Seite dokumentiert **die Integrations-Seite der WLO-Wertschöpfung**: WLO ist nicht nur Endkunden-Suche, sondern eine **B2B-Metadaten-Infrastruktur** für Bildungsplattformen. Das Angebot umfasst:

- **10 unterstützte Plattformen** (5 LMS + 5 CMS/Office)
- **edu-sharing als gemeinsame OSS-Basis**
- **Automatische Lizenzangaben** als USP für Lehrende
- **Selektive Metadaten-Pools** mit Mapping-Option für Länder/Institutionen

Die neuere Plattform-Kommunikation (siehe `wissenlebtonline/017-lms-cms-connect.md`) konkretisiert Zahlen und erweitert um Serlo, GeoGebra, dBildungscloud.

