---
id: wlo-module-008
title: "Plattform-Module von WissenLebtOnline: zentrale Referenz"
source: "https://wp-test.wirlernenonline.de/ (zusammengeführt aus Redaktionen, Content-Anbieter, OER-Community, Infrastruktur-Betreiber, Entwickler, Politik)"
updated: 2026-04-20
license: "CC BY 4.0"
tags: [module, referenz, redaktionsumgebung, bildungs-api, themenseiten, automatisierung, monitoring, oekosystem, gwdg, edu-sharing]
chunk_strategy: heading
brand_names: ["WissenLebtOnline", "WirLernenOnline", "WLO"]
cross_reference_for:
  - "002-redaktionen.md"
  - "003-content-anbieter.md"
  - "004-oer-community-akteure.md"
  - "005-infrastruktur-betreiber.md"
  - "006-entwickler-software-ki.md"
  - "007-politik-rahmensetzer.md"
---

# Plattform-Module von WissenLebtOnline — zentrale Referenz

Diese Datei beschreibt die wiederkehrenden Plattform-Module, die aus
mehreren Zielgruppen-Seiten (Redaktionen, Content-Anbieter,
OER-Community, Infrastruktur-Betreiber, Entwickler, Politik) heraus
angesprochen werden. Jede Zielgruppen-Datei nennt die Module nur kurz
und verweist auf diese Referenz für die ausführliche Beschreibung.

## Redaktionsumgebung / Redaktionssoftware

**Slogan**: „Das ist Redaktionswissen in Software gegossen."

In der WissenLebtOnline-Redaktionsumgebung ist das Wissen aus
**Informationswissenschaft**, **30 Fachredaktionen** und
**KI-Fachleuten** einprogrammiert — damit der Sprung ins KI-Zeitalter
gelingt. Die Umgebung beantwortet strukturell vier Leitfragen:

1. Wie entsteht eine im KI-Zeitalter gut verwertbare Inhalte- und
   Wissenssammlung?
2. Wie kommen erschlossene Inhalte in die Plattformen der
   Bildungsbereiche und werden Basis für KI-Mehrwertfunktionen?
3. Wie werden Inhalte effizient gesammelt, verschlagwortet und mit
   Kompetenzrastern, Lehrplänen und Weltwissen verlinkt?
4. Welche Frage-Antwort-Paare und anderen Guidelines sollen Chatbots
   oder andere KI-Funktionen lenken?

**Varianten**:

- **Klassische Redaktionsumgebung** — für pädagogische Zentren,
  Fachgesellschaften, Behörden, Forschung, Bibliotheken, Verlage
- **OER-Cockpit** — spezialisierte Variante für OER-Communities
- **Beantragung** per Kooperationsvertrag: info@WissenLebtOnline.de

## Automatisierung

**Slogan**: „Generierst du schon oder schreibst du noch?"

In jedem Fach- oder Lehrgebiet gibt es hunderte Dokumente und Quellen.
Manuelle Erfassung ist unwirtschaftlich. KI-Crawler und Generatoren
erzeugen automatisiert:

- **Themenbäume** — hierarchische Strukturen für den Fachbestand
- **Metadaten** — Verschlagwortung mit aktuellen Vokabularen
- **Kompendien** — thematische Zusammenfassungen aus mehreren Quellen
- **Frage-Antwort-Paare** — als Lenkung für KI-Assistenten

Der Mensch **lenkt und beaufsichtigt** die technischen Helfer — das
schafft Zeit für Lehre, Kreatives und Zwischenmenschliches.

## Themenseiten — interaktive Schaufenster

Redaktionen pflegen generierte Themenbäume mit Sammlungen. Aus Vorlagen
generieren sich automatisch **Themenseiten** — informative Schaufenster
für den redaktionellen Bestand eines Themas oder einer pädagogischen
Zusammenstellung für eine Zielgruppe.

**Widgets** auf Themenseiten zeigen Inhalte oder Untersammlungen. Sie
sind mit Erlaubnis der Redaktion in **Drittwebseiten oder Lernportale
einbettbar** — Redaktionsarbeit wird sofort in den Zielgruppen-Portalen
wirksam.

## Lernplattform-Integration (IMS-LTI, Plugins, WebCMS)

Mit WissenLebtOnline verwaltete Inhalte können in **allen modernen
Lernplattformen** nachgenutzt werden — einschließlich MediaWiki und
diverser WebCMS.

### Standardisierte Schnittstelle

- **IMS-LTI** — Branchen-Standard für LMS-Integration
- **Plugins** — Portal-spezifische Erweiterungen
- Konnektoren sind für alle LMS möglich, die IMS-LTI unterstützen

### Automatische Darstellung

- **Lizenz- und Urheberangaben** werden automatisch angezeigt
- **Medien** werden vom Renderingservice passend dargestellt und skaliert
- **Nutzungsinteraktionen** werden automatisch und datenschutzkonform
  erfasst — Feedback an Content-Anbieter

Voraussetzung ist jeweils die Erlaubnis der Redaktion.

## KI-Assistenten-Datenbasis und MCP

Gut sortierte Redaktions-Sammlungen werden automatisiert in eine
**maschinenlesbare Wissensbasis** transformiert. Über Schnittstellen der
Bildungs-API kann diese Wissensbasis für KI-Anbieter oder eigene
Entwickler freigegeben werden.

Das WissenLebtOnline-Team vermittelt bei Bedarf KI-Anbieter, die aus dem
Bestand zeitgemäße Angebote für die Zielgruppe erstellen.

Als Middleware zwischen KI-Modellen und API stehen **MCP-Server**
bereit (Model Context Protocol).

## Bildungs-API

Die verteilte Service-Infrastruktur und die Daten sind über die
**Bildungs-API** nutzbar. Eigene Services sind integrierbar.

### Bereitgestellte Services

- **KI-Modelle** — lokal betrieben in der GWDG
- **Metadaten-Generatoren** — basierend auf aktuellen
  Verschlagwortungssystematiken
- **Rendering-Service** — Abspielen und Skalieren von Medien und
  E-Learning-Formaten
- Weitere Services aus dem vernetzten Ökosystem — kontinuierlich erweitert

### Erweiterbarkeit

Softwarehersteller können eigene Services in das Ökosystem einbringen.
Die API-Dokumentation ist über wissenlebtonline.de verfügbar.

## Crawler für Webportale

Für Quellen, die ein Webportal ohne standardisierte Metadaten-Schnittstelle
sind, erzeugen Crawler automatisch **Metadatensätze pro Seite**.

- **Ausschluss-Regeln**: Seiten wie Impressum oder Datenschutz können per
  Konfiguration ausgeschlossen werden.
- **Rohdaten-Prüfung**: Ergebnisse werden in der Redaktionsumgebung
  geprüft, überarbeitet und freigeschaltet.
- **Rück- und Weitergabe**: Nach Freigabe sind Rücktransport an die
  Quelle und Weitergabe an Drittsysteme möglich.

## Quelle anschließen (OAI-PMH, REST)

Content-Anbieter halten ihre Bildungsinhalte oft in eigenen Datenbasen.
Per Schnittstelle werden sie nach WissenLebtOnline transferiert, mit
pädagogischen Metadaten ergänzt und anschließend:

- **zurückgegeben** an die eigene Datenbasis, oder
- **verbreitet** über WissenLebtOnline und angeschlossene Plattformen

Unterstützte Schnittstellen:

- **OAI-PMH** — Open Archives Initiative Protocol for Metadata Harvesting
- **REST**

## Aktuelle, gute Metadaten

Begriffe, Schlagwortkataloge, Kompetenz- und Lehrpläne und
Sachgebietssystematiken ändern sich ständig. Damit Inhalte weiterhin
auffindbar und nutzbar bleiben, müssen Metadaten laufend angepasst
werden.

**KI-Vorschläge** empfehlen kontinuierlich Metadaten-Ergänzungen und
-Verbesserungen — auf Basis aktualisierter Verschlagwortungs­systematiken
(„**Metadatenvokabulare**").

## Fortschrittsmonitoring

Die Redaktionsumgebung liefert:

- **Füllstandsübersichten** — wie weit ist der Bestand pro Themenbereich?
- **Qualitätsübersichten** — wie vollständig und konsistent sind die
  Metadaten?

Im **Zeitverlauf** ist sichtbar, wie Redaktionen vorankommen. Damit
lassen sich Berichte für Geldgeber und Stakeholder effizient erstellen.

## Ökosystem für Bildung — GWDG-Infrastruktur

Das souveräne Ökosystem läuft in einem **Kubernetes-Cluster** bei der
GWDG. Hersteller stellen ihre Anwendungen als **Docker-Container** bereit.

### Bestandteile des Ökosystems

- Ein **Datenraum**
- Die **Bildungs-API**
- **Hintergrund-Services** (API-nutzbar, erweiterbar)
- Verschiedene **KI-Modelle** (API-nutzbar, erweiterbar)
- **MCP-Server** — Middleware für KI-Modelle, die die API nutzen
- Eine **KI-Lernbasis / Qualitätssicherung** — Lern- und Steuerungsdaten
  für KI-Reaktionen

### Betriebliche Eigenschaften

- **Lokal, souverän, zertifiziert** — Datenspeicherung in der GWDG
- **Lokale KI-Modelle** — lokal überwacht, kein Drift nach außen
- **Zukunftsfähig, skalierbar, hochverfügbar** — Kubernetes-basierte
  Plattform

### Varianten

- **PaaS** in der Academic Cloud — Mandanten mit eigenen Redaktionsbereichen
- **SaaS** — dedizierte Instanz für Großanwender
- **Self-Hosting** — Open-Source-Module in eigener Infrastruktur

## Verhältnis WissenLebtOnline ↔ edu-sharing

WissenLebtOnline ist die für Redaktionen und KI optimierte
**Lab-Version der edu-sharing-Software**. Die in Forschungs- und
Entwicklungsprojekten entstandenen Funktionen werden derzeit
qualitätsgesichert und in das Angebotsportfolio der GWDG übernommen.

### Transferweg in die Standardsoftware

- **edu-sharing-Standardsoftware** läuft in **10 Bundesländern** zentral
  — entweder selbst gehostet oder als SaaS bei der GWDG.
- Bundesländer und Anwender **lenken die Lab-Version** über Kreativ- und
  Feedbackformate.
- In **Transferprojekten** werden reife Funktionen aus der Lab-Version in
  die Standardsoftware überführt — die Standardsoftware ist damit für
  pädagogische Einsatzszenarien und OER-Redaktionsarbeit optimiert.

## Anbindung von Suchmaschinen und Metadaten-Sammelstellen

Zwei Anbindungsmuster:

### Harvesting / Datenaustausch

Automatischer Austausch zwischen WissenLebtOnline und anderen Systemen
über **OAI-PMH** oder **REST** — Import und Export in beide Richtungen.

### Föderierte Suche

Die Such-Funktion von WissenLebtOnline wird in bestehende Suchsysteme
eingebunden. Bei einer Suchanfrage werden **live** auch Inhalte aus
WissenLebtOnline eingeblendet.

## Service für KI-Projekte und -Anwendungen

KI-Projekte entwickeln vielerorts Bildungsanwendungen. Viele nutzen für
erste Prototypen **Big-Tech-Modelle und -Infrastrukturen im Ausland**.

Für den Transfer in die Bildungspraxis ist der **Wechsel in
zertifizierte lokale Infrastrukturen** empfehlenswert — das
WissenLebtOnline-Team bietet hierfür:

- **Beratung** und **Transferunterstützung**
- Zugang zur **KI-Infrastruktur der GWDG**
- **Onboarding-Webinare** und Hands-on-Formate

## OER-Cockpit (Spezialisierung für OER-Communities)

Das OER-Cockpit ist die zielgruppen-spezifische Redaktionsumgebung für
OER-Communities. Ausführliche Beschreibung siehe
**004-oer-community-akteure.md** — kurz:

- OER **auffindbar** machen (Metadaten erfassen)
- OER **erstellen** und kollaborativ daran arbeiten
- OER **prüfen** / Qualität sichern
- OER-**Sammlungen** zusammenstellen
- OER und Sammlungen **verbreiten**
- **Redaktionelle Verantwortung** für einen Themenbereich übernehmen

## OER-Statistik (Plattform-Beitrag)

WissenLebtOnline zählt jährlich OER im deutschsprachigen Raum. Alle über
die Redaktionsumgebung oder das OER-Cockpit bereitgestellten Inhalte
fließen automatisch in die OER-Statistik ein.

Ausführlich: **001-oer-grundlagen.md**.

## Compliance und Datenschutz

Je nach Einsatz in den Bundesländern und Bildungsbereichen sind Vorgaben
zu **Datenschutz**, **Sicherheit** und **weiteren Compliance-Anforderungen**
einzuhalten und nachzuweisen.

- **Lokale Datenspeicherung** in der GWDG
- **Nutzungsinteraktionen** werden datenschutzkonform erfasst
- **Vertrags- und Abrechnungssysteme** werden zwischen
  Softwareherstellern und Betriebsinfrastruktur vereinbart

Ein interdisziplinäres Team aus Anwälten, UX-Fachleuten für Zero UI,
IT- und Sicherheitsexpert:innen sowie KI-Fachleuten begleitet den
Transfer.

## Kontakt und Dokumentation

- **E-Mail**: info@WissenLebtOnline.de
- **API-Dokumentation**: über wissenlebtonline.de
- **Newsletter & Community**: **009-newsletter-und-kontakt.md**
