---
id: wlo-content-anbieter-003
title: "WissenLebtOnline für Anbieter von Wissens- und Bildungsinhalten"
source: "https://wp-test.wirlernenonline.de/contentanbieter/"
updated: 2026-04-20
license: "CC BY 4.0"
tags: [content-anbieter, zielgruppe, datenbasen, oai-pmh, rest, crawler, metadaten]
chunk_strategy: heading
brand_names: ["WissenLebtOnline", "WirLernenOnline", "WLO"]
target_audience: "Anbieter von Wissens- und Bildungsinhalten, die bestehende Content-Datenbasen auffindbarer und nutzbarer machen wollen"
---

# WissenLebtOnline für Anbieter von Wissens- und Bildungsinhalten

## Wertversprechen

Es gibt viele gute Lern- und Wissensinhalte, Bildungsangebote, Lernorte
und Lerngruppen. Manches ist bereits in Datenbanken kartiert, findet
aber nicht bis zu den Nutzenden — und kann noch nicht durch einen
KI-Assistenten erklärt werden.

**Um das zu ändern, braucht es gute Metadaten und einen Transfer, der
Inhalte in maschinenlesbares Wissen überführt.**

WissenLebtOnline importiert vorhandene Inhalte-Datenbasen, verschlagwortet
sie gemeinsam mit dem Anbieter und verbreitet sie — in Bildungsnetzwerken
oder auf Wunsch gezielt an definierte Drittsysteme.

## Schnittstellen zur Inhaltebereitstellung

### Quelle anschließen (Datenbasen importieren)

Content-Anbieter halten ihre Bildungsinhalte und -angebote oft für
eigene Zwecke gut sortiert in Datenbasen vor. Um sie in Bildungsnetzwerken
besser **auffindbar und nutzbar** zu machen, werden sie per Schnittstelle
zu WissenLebtOnline transferiert, mit pädagogischen Metadaten ergänzt
und zurückgegeben — oder auf Wunsch durch WissenLebtOnline verbreitet.

Unterstützte Schnittstellen:

- **OAI-PMH** (Open Archives Initiative Protocol for Metadata Harvesting)
- **REST**

Der Datenfluss ist **bidirektional**: Import, Anreicherung in der
Redaktionsumgebung, Rücktransport oder Weitergabe an Drittsysteme.

### Crawler für Webportale (Metadaten-Generierung für Webseiten)

Wenn eine Quelle ein Webportal ohne standardisierte Metadaten-Schnittstelle
ist, kommen **Crawler** zum Einsatz. Der Crawler generiert je Seite
des Webauftritts einen Metadatensatz. Über definierbare Regeln können
bestimmte Seiten — zum Beispiel das Impressum — ausgeschlossen werden.

Die Rohdaten werden in der Redaktionsumgebung geprüft, überarbeitet und
für Rücktransport oder Weitergabe an Drittsysteme freigeschaltet.

## Aktuelle, gute Metadaten

Begriffe, Schlagwortkataloge, Kompetenz- und Lehrpläne sowie
Sachgebietssystematiken ändern sich ständig. Damit Inhalte weiterhin
auffindbar und nutzbar bleiben, müssen Metadaten laufend angepasst
werden.

An die Redaktionsumgebung sind Services zur **Metadaten-Generierung**
angeschlossen. KI-Vorschläge empfehlen kontinuierlich Ergänzungen und
Verbesserungen — auf Basis aktualisierter Verschlagwortungssystematiken
("Metadatenvokabulare").

## Wie WissenLebtOnline-Module Content-Anbieter unterstützen

Die weiteren Funktionsbausteine der Plattform sind für Content-Anbieter
ebenso nutzbar wie für redaktionelle Organisationen:

- **Redaktionssoftware** für Sichtung, Kuration und Qualitätssicherung
- **Automatisierung**: KI-Crawler und -Generatoren für Themenbäume,
  Metadaten, Kompendien, Frage-Antwort-Paare
- **Themenseiten**: redaktionelle Schaufenster mit einbettbaren Widgets
- **Lernplattform-Integration** über IMS-LTI / Plugins
- **KI-Assistenten**-Datenbasis über die Bildungs-API
- **Fortschrittsmonitoring** für Stakeholder-Berichte

Ausführliche Modul-Beschreibungen: **008-plattform-module.md**.

## Typischer Arbeitsablauf für einen Content-Anbieter

1. **Quelle anschließen** — OAI-PMH oder REST konfigurieren, oder Crawler
   für ein Webportal aufsetzen
2. **Metadaten prüfen und ergänzen** — automatische KI-Vorschläge
   akzeptieren, ergänzen, korrigieren
3. **Freigabe konfigurieren** — Rücktransport zur eigenen Datenbasis,
   Weitergabe an Bildungsnetzwerke oder beides
4. **Verbreitung beobachten** — Nutzungsstatistiken zur eigenen
   Sichtbarkeit in WissenLebtOnline und angeschlossenen Plattformen

## Kontakt

- **E-Mail**: info@WissenLebtOnline.de
- Newsletter und Mitmachangebote: **009-newsletter-und-kontakt.md**
