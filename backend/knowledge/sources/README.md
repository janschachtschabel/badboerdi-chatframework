# RAG-Quelltexte — kontrollierbare Wissensbasis

Dieses Verzeichnis ist die **menschenlesbare Quelle** für alles, was der
Chatbot als RAG-Wissen liefert. Die DB-Chunks in `../badboerdi.db` sind nur
ein abgeleitetes Artefakt (Split + Embedding + Index) und können jederzeit
neu aus den Markdown-Dateien hier erzeugt werden.

## Layout

```
sources/
├── README.md                         ← diese Datei
├── <bereichs-slug>/
│   ├── _area.yaml                    ← RAG-Bereichs-Config
│   ├── 001-<kurztitel>.md
│   ├── 002-<kurztitel>.md
│   └── …
└── <anderer-bereichs-slug>/
    └── …
```

## Frontmatter-Schema pro Text

Jede `.md`-Datei beginnt mit einem YAML-Frontmatter-Block:

```markdown
---
id: wlo-oer-001                 # eindeutiger Kurz-ID (bereich + fortlfd.)
title: "Was sind OER?"          # menschenlesbarer Titel
source: "https://..."           # Original-URL, falls vorhanden
updated: 2026-04-20             # Stand des Inhalts
license: "CC BY-SA 4.0"         # Lizenz des Quelltextes
tags: [oer, grundlagen]         # Freie Tags für Filter/Suche
chunk_strategy: paragraph       # paragraph | heading | fixed_500
---
```

## Bereichs-Config (`_area.yaml`)

Pro Unterordner eine YAML-Datei mit den Metadaten des RAG-Bereichs, der im
`05-knowledge/rag-config.yaml` des Chatbots referenziert werden kann:

```yaml
id: wissenlebtonline.de-webseite
label: "WissenLebtOnline Webseite"
mode: always                    # always | on_demand
description: "Plattforminformationen, Dienstleistungen, Produkte, OER-Grundlagen"
```

## Workflow

1. **Neuer Text**: unter `<bereich>/<nr>-<slug>.md` ablegen, Frontmatter ausfüllen.
2. **Review**: Änderungen via Git-Diff sichtbar, PR-basierte Freigabe möglich.
3. **Reindex**: `python scripts/rag_reindex.py --area <slug>` chunkt die MDs,
   erzeugt Embeddings, ersetzt die Bereichs-Chunks in der DB. (Skript folgt
   in einem späteren Schritt, sobald die erste Charge Quelltexte steht.)

## Vorhandene Bereiche

| Slug | Bereich | Mode | Umfang |
|---|---|---|---|
| `wissenlebtonline` | WissenLebtOnline Plattform & OER-Grundlagen | `always` | 28 Texte |
| `wirlernenonline` | WirLernenOnline — alte Projektseite / Legacy-Repository (wirlernenonline.de) | `on_demand` | 11 Texte |
| `oer` | OER-Grundlagen und -Strategie (bildungspolitisch, allgemein) | `on_demand` | 18 Texte |
| `edu-sharing-network` | edu-sharing network e.V. — Trägerverein (Weimar), Webinare, Ausschreibungen, Jobs, IT’s JOINTLY, HackathOERn, Sommercamp | `on_demand` | 7 Texte |
| `edu-sharing-com` | edu-sharing.com — kommerzielle Produkt- und Servicewebsite der metaVentis GmbH (Software-Kernentwickler) | `on_demand` | 7 Texte |
| `faq` | Zielgruppenspezifische FAQ-Einträge (frage-zentriert, Kurzantworten mit Querverweisen) | `on_demand` | 7 Texte |

### Bereich `faq` — Inhaltsübersicht

| Datei | Inhalt / Zielgruppe | Quelle |
|---|---|---|
| `001-lehrende-und-lernende.md` | FAQ Lehrkräfte/Lernende: Was ist WLO, Fachportale, Suche, Klassenstufen-Filter, QS-Stufen, Anmeldung, Kosten, Beitragen, „Freie Bildung zum Mitmachen" | `/faq/` + `/bildungsinhalte/` |
| `002-oer-wissen.md` | **OER-Grundlagenwissen**: Definition (UNESCO 2019), DE-Geschichte 2012→2025, 7 CC-Lizenztypen mit OER-Tauglichkeit, **TULLU**-Pflichtangaben, Bearbeitung/Kombination, CC0, KI-generierte Inhalte (§ 2 Abs. 2 UrhG → gemeinfrei), OERcamp-Goldstandard | UNESCO/BMBF/bpb/iRights/OERcamp (Zusammenfassung) |
| `003-redakteurinnen.md` | FAQ Redakteur:innen: Nutzen, Zielgruppen (Päd. Zentren, Fachgesellschaften, Behörden, Bibliotheken, Verlage), 5 Werkzeuge der Redaktionssoftware (KI-Crawler, Themenseiten, LMS, KI-Wissensbasis, Monitoring), KI-Datenbasis, Kosten, Zugang | `/redaktionen/` + `/faq/` |
| `004-schuelerinnen.md` | FAQ Schüler:innen (sehr niedrigschwellig): Was kann ich hier machen?, Anmeldung, Kosten, Themenseiten, eigene Materialien teilen | `/faq/` + `/bildungsinhalte/` |
| `005-plattform-info.md` | **WLO-Plattform-Referenz**: Selbstverständnis (Ökosystem statt Plattform), Zahlen (400k/316.865/25.178/170k OER-Aufschlüsselung), Geschichte 2020/2026/2027, Träger (GWDG/e.V.), Ansprechpartner (Mansour/Neuenfeld/Hupfer), 6 Zielgruppen, 6 Lösungen, Mitmachen, Souveränität (GWDG/ISO 27001) | `/home/` + `/oer-statistik/` |
| `006-politik-und-presse.md` | FAQ Politik/Presse: 3 Ebenen (Ökosystem/Plattform/Produkte), Rolle im Bildungssystem, Abgrenzung zu klassischen Plattformen, Souveränität, KI-Rolle, **zitierbare Zahlen**, gesellschaftliche Wirkung, Bundesland anschließen, Pressekontakt Neuenfeld | `/faq/` + `/oer-statistik/` |
| `007-identitaet-boerdi.md` | **BOERDi-Identität**: blaue Eule von WirLernenOnline, erster Kontakt auf WLO-Webseite, WLO = offene BMBF-Bildungsplattform mit OER, Nutzerkontext (anonym, kein Login) | BOERDi-Systemdefinition |

### Bereich `wissenlebtonline` — Inhaltsübersicht

| Datei | Inhalt / Zielgruppe | Quelle |
|---|---|---|
| `001-oer-grundlagen.md` | OER-Grundlagen, -Community, -Statistik, -Redaktion, Lizenzen, Ökosystem | `/bildungsinhalte/oer/` |
| `002-redaktionen.md` | Redaktionelle Organisationen (Päd. Zentren, Fachgesellschaften, Behörden, Bibliotheken, Verlage) | `/redaktionen/` |
| `003-content-anbieter.md` | Content-Anbieter mit eigenen Datenbasen (OAI-PMH, REST, Crawler) | `/contentanbieter/` |
| `004-oer-community-akteure.md` | Lehrende, Lernende, Autor:innen, OER-Projekte (OER-Cockpit) | `/oer-community/` |
| `005-infrastruktur-betreiber.md` | Hosting, GWDG, PaaS/SaaS, edu-sharing, LMS-Integration | `/software-betreiber/` |
| `006-entwickler-software-ki.md` | Software- und KI-Entwickler, Onboarding, Kubernetes, Docker, MCP | `/bildungsinfrastruktur-mitgestalten/` |
| `007-politik-rahmensetzer.md` | Politik, Ministerien, Förderung, Handlungsempfehlungen | `/wlo-fuer-politik/` |
| `008-plattform-module.md` | **Zentrale Referenz** aller wiederkehrenden Module | mehrere |
| `009-newsletter-und-kontakt.md` | Newsletter, Kontakt, Code of Conduct, Lizenz-Hinweis | mehrere (Footer) |
| `010-home-ueberblick.md` | Home/Startseite, WLO-Geschichte 2020→heute, Team | `/home/` |
| `011-bildungsinhalte-fachportale.md` | Fachportale, WLO in Zahlen (316 k / 29 / 2.970 / …), Open by default | `/bildungsinhalte/` |
| `012-oer-statistik.md` | Deutsche OER-Statistik 2022–2025 + PDF-Links | `/oer-statistik/` |
| `013-kontakt-oer-redaktion.md` | 5-Schritte-Onboarding für OER-Fachredaktionen | `/mitmachen/kontakt-oer-redaktion/` |
| `014-faq.md` | FAQ in 11 Themenbereichen (Grundverständnis, Mehrwerte, KI, Governance, Politik, …) | FAQ-Akkordeon |
| `015-loesungen-ueberblick.md` | 4-Säulen-Modell **Erschließe · Pflege · Zeige · Verbreite** mit Capability-Matrix | `/angebote/` |
| `016-wlo-data.md` | **WLO Data** — Metadaten-Bestand, Themenbäume (~3.000), Refined Data, Kompendialtexte, Volltexte, QA-Paare, NLP-Modelle, Vokabulare, Knowledge Graphs, Adaptionsvariablen | `/wlo-inhalte-fuer-deine-suchmaschine/` |
| `017-lms-cms-connect.md` | LMS/WebCMS/Editor-Anbindung (4 Bundesländer / 9 Plattformen / 500 k User); Moodle, ILIAS, dBildungscloud, OpenOlat, WordPress, MediaWiki, Drupal, OnlyOffice, Serlo, Geogebra | `/angebote/integrationen-fuer-lernplattformen-und-web-cms/` |
| `018-redaktionssoftware.md` | 3 Softwareversionen (edu-sharing Standard / WLO-Version / Bildungs-API & KI-Infrastruktur); Buffets (Prüf/Such/Redaktion), MetaQS, gen. Crawler, Widgets, Bildungs-Map | `/wlo-redaktionssoftware/` |
| `019-quellenerschliessung.md` | Automatisierte Quellenerschließung: 55+ Crawler, generischer Crawler, Browser-Extension (Web Components), KI-Volltext-Analyse | `/automatisierte-quellenerschliessung/` |
| `020-bildungs-api.md` | Bildungs-API: Volltext-Extraktion, Bilderzeugung, Metadaten-Generierung, Textstatistiken, eigene Dienste einbringen (Docker/Kubernetes) | `/angebote/bildungs-api/` |
| `021-ki-oekosystem.md` | Souveränes KI-Ökosystem: GWDG-Hosting, ISO 27001 / DIN EN ISO 9001, lokale Modelle, HackathOERn, Softwareentwicklung 2.0, Docker/Kubernetes-Onboarding | `/angebote/souveraenes-ki-oekosystem/` |
| `022-metadaten-optimieren.md` | Metadaten-Werkzeugkasten: KI-Generierung, Klassifikation, Qualitätseinschätzungen, MetaQS, API-Integration, Empfehlungssysteme | `/metadaten-verbessern-lassen/` |
| `023-home-aktuell.md` | Aktualisierte Startseite: Zielgruppen-Hubs, Open by default, Geschichte 2020→heute (400 k Inhalte), Team (Mansour/Neuenfeld/Hupfer), Partner, Newsletter — supersedes 010 | `/home/` |
| `024-ueber-wlo-geschichte.md` | Timeline 2010–2026, edu-sharing-Geschichte, OER-Community, OERinfo 2016, WLO Pandemie-Gründung, Blaupausen, Umbenennung zu WissenLebtOnline | `/ueber-wlo/` |
| `025-quellen-qualitaet.md` | 657 Quellen, mehrstufige Qualitätssicherung, Qualitätskriterien-Icons, Erschließungswege (Crawler/CSV/REST/OAI-PMH), Top-Quellenverzeichnis | `/datenquellen/` |
| `026-oer-grundlagen-aktuell.md` | OER-Definition, UNESCO-Ursprung, Fachredaktion (Tina Neff/ZUM.de), Remix/CC-Lizenzen, CC-Mixer, Tools, OEP, OER-Ökosystem (JOINTLY/MOERFI/HackathOERn) — supersedes 001 | `/bildungsinhalte/oer/` |
| `027-fachportale.md` | 28 Fachportale, WLO-Fachportale (OER-Redaktion), Community-Portale, 5-Schritte für neue Redaktionen (Gründen → Grundlagen → Themenbaum → Sammlungen → Verwerten) | `/fachportale/` |
| `028-suche-referenz.md` | Referenz-Datei für die WLO-Suchmaschine (kein Seitentext vorhanden); URL, Funktion, Ökosystem-Einbettung | `suche.wirlernenonline.de/search/…` |

### Bereich `wirlernenonline` — Inhaltsübersicht

| Datei | Inhalt / Zielgruppe | Quelle |
|---|---|---|
| `001-startseite.md` | Startseite der alten Projektseite: Mission (Suchmaschine + Community), Zahlen (283.583 Inhalte / 25.019 geprüft / 27 Fachportale), edu-sharing.net e.V. + Wikimedia + Bündnis Freie Bildung, Qualitätssicherung (Basisprüfung / Redaktions-Empfehlung), HPI Schulcloud-Anbindung, KI-Metadaten, CC BY 4.0 | `https://wirlernenonline.de/` |
| `002-ueber-wirlernenonline.md` | Gründungsgeschichte (Corona-Krise April 2020, 7 Wochen bis online), edu-sharing seit 10 Jahren mit 10 Bundesländern, Wikimedia + Bündnis Freie Bildung, 3 Funktionsprinzipien (Offene Daten / Mitmachen / Professionalisierung), Browserplugin+App, WLO-Beirat | `/ueber-wirlernenonline/` |
| `003-oer-bereich.md` | OER-Bereich mit 5 Tabs (Verstehen/Finden/Verwenden/Erstellen/Teilen): UNESCO-Definition, CC0/BY/SA, 5 OER-Argumente inkl. OEP, WLO-Suche + edutags, Remix-Praxis, HowTo-OER Download, License Compatibility Chart, Remix-Board; externe Partner (bpb, OERinForm, OERcamp/J&K, wb-web+iRights, DigiDucation) | `/oer/` + `/oerfinden/` + `/oerverwenden/` + `/oererstellen/` + `/oerteilen/` |
| `004-qualitaetssicherung-und-redaktionsstatut.md` | Mehrstufige QS (Basis-Sichtung / Fachredaktion / 5 Kriterien), 4 Hauptkategorien (Tool/Quelle/Material/Methode), 3 Siegel (OER / Freier Zugang / Redaktionsempfehlung), 12-Punkte-Redaktionsstatut (Beutelsbacher Konsens, keine Werbung, CC-Default, BMBF-Förderung), Stand Sept. 2020 | `/qualitatssicherung/` + `/redaktionsstatut/` |
| `005-quellenerschliessung.md` | 9-stufiger Quellenerschließungsprozess (Sichtung → Rechtsklärung → maschinelle Erschließung → Rohdatenprüfung → Freigabe), Kooperations-Stelle, Qualitätskriterien-Icons, Barrierearmut (noch ungeprüft) | `/quellenerschliessung-uebersicht/` |
| `006-plugins-integrationen.md` | 10 Plattform-Plug-ins (Moodle/ILIAS/OpenOlat/Opal/Mahara + WordPress/Typo3/MediaWiki/Onyx/OnlyOffice), edu-sharing OSS-Basis, automatische Lizenzangaben, selektive Metadaten-Pools für Länder/Schulen, Landesmediensammlungen | `/plugins/` |
| `007-beirat.md` | WLO-Beirat: Mission (partizipativ/konstruktiv-kritisch), Arbeitsweise (Konsent-Prinzip, 2× jährlich), 14 Mitglieder aus ≥15 Organisationen (ZUM, SV-Bildungswerk, digiLL, learninglab, Bundeselternrat, Agentur J&K, eBildungslabor, Uni Bremen/Köln/EHiP, GMK, DLC SH, DIPF/OERinfo, DIE, Wikimedia); Schwerpunkte Bildungsgerechtigkeit + inklusive OER | `/beirat/` |
| `008-oer-statistik.md` | OERde-Statistiken 2022–2025 + Nachhaltigkeit-Sonderstatistik: OER-Definition (CC0/PD/BY/SA), Gesamtzahlen (2023: 86k → 2024: 100k → 2025: 170k), Aufschlüsselung Schule/Hochschule/Berufsbildung/Kita, 4 Sammelstellen (WLO/Mundo/OERSI/KITA.bayern), Agenda-2030-Links | `/statistics/` |
| `009-mitmachen.md` | 8 Mitmach-Pfade: Inhalte / Quellen / Tools vorschlagen, Feedback, Fachredaktionen beitreten, Partner+Kooperationen, Newsletter, Kontakt; Wikipedia-Prinzip | `/mitmachen/` |
| `010-fachportale-und-suche.md` | 28 Fachportale organisiert in 8 Fachgruppen (Deutsch, Fremdsprachen, GeWi, MINT, Musisch, Querschnitt, Religion/Philosophie/Ethik, Sport), Onboarding für neue Fachredakteur:innen, Suche-Referenz (`suche.wirlernenonline.de`) | `/fachportale/` + `suche.wirlernenonline.de/search/` |
| `011-faq.md` | FAQ in 6 Teilen (Was-ist-WLO / Träger+Finanzierung / OER / Mitmachen / Integration / Praktisches); Covid19-Nothilfe-Programm BMBF, HPI-Schulcloud-Teilvorhaben, Repositorium-Einbindung, Mastodon/YouTube/X-Abkehr, Hardware-Suche | `/faq/` |

### Bereich `edu-sharing-network` — Inhaltsübersicht

| Datei | Inhalt / Zielgruppe | Quelle |
|---|---|---|
| `001-verein-ueberblick.md` | Verein edu-sharing network e.V. (Weimar): Mission, 10 Arbeitsgebiete, Projektzeitleiste (2015 Robert-Bosch → JOINTLY → WLO → BIRD → ITsJOINTLY), 4-köpfiger Vorstand (Jindra/Zobel/Morgner/Erfurth), Mitgliedschaft (300€/800€), Spenden | `/` |
| `002-webinare-ki-infrastruktur.md` | Webinarreihe „KI-Infrastruktur für Bildung“ Dez 2025–März 2026 (12 Termine): Transferwege, Rechtsfragen (iRights-law, 2 Teile), Bildungs-/KI-API Hands-on, Redaktionssoftware edu-sharing/WLO, Browser-Plugin, LMS-Anbindung (IMS-LTI), Themenseiten-Widgets, KI-Lerndatenbasis (mit DFKI-Einschätzung); Förderung BMFTR 16INBI001B + NextGenerationEU | `/webinare/` |
| `003-ausschreibungen.md` | 3 UVgO-Vergabeverfahren 2025 (Archiv): MetaQS (Inhalteverwaltung/Plattform-Schnittstellen), MetaLookUP (6 nicht-inhaltliche + 4 inhaltliche Qualitätskriterien für Online-Lerninhalte), IT’s JOINTLY (europäische KI-Wissensbasis, 5 Bildungsbereiche) | `/ausschreibungen/` |
| `004-jobs-und-karriere.md` | Arbeitgeberprofil: Vergabekultur (ÖD-orientiert), Remote + Daily 10 Uhr, Weimar + Berlin Coworking, 4-Schritt-Bewerbungsprozess (Mail → Rückmeldung → Team-Daily → Fachgespräch mit Aufgabe); 4 Tätigkeitsfelder für Initiativbewerbungen (Community-Management, Support-Strukturen, Technischer Support, Koordination) | `/jobs/` |
| `005-its-jointly.md` | **IT’s JOINTLY** (NBP-Teilprojekt, BMBF-gefördert): skalierfreie KI-basierte Inhalteverwaltung, 3 Motoren (Redaktionsnetzwerk mit Human-in-the-Loop / Inhalteerschließung / Software auf edu-sharing-Basis), 4-Partner-Konsortium (Dataport Koordination, edu-sharing.net e.V., GWDG, yovisto); Erblinie JOINTLY4OER → WLO → BOERD → IT’s JOINTLY; Impressum: VR 131198, Vorstand Prof. Erfurth | `its.jointly.info` |
| `006-hackathoern.md` | **HackathOERn** (BMBF-FKZ 01PP24002A): 4 Hackathons + öffentliche Ideendatenbank. Rückblicke HackathOERn No.1 Göttingen (Apr 2025, ~50 TN, LearnGraph/Edufeed/OER Finder/B3/PollOER) + No.2 Weimar (Aug 2025, ~70 TN, 9 Workshops, Chatbot/OER-Editor/Metadaten-Mapping/Edufeed/Celebration-Feature); No.3 Göttingen 11.–13.05.2026 mit 8 Ideen (AI Content Editor, fAIr, poEtree, MCP+Nostr, OER-Navigator, …); 3 Ideen-Labore (Feb–März 2026); Partner MOERFI/FWU/WLO/GWDG; Team Marco (Leitung), Maren (Events), Jason (GWDG) | `/projekt-hackathoern/` |
| `007-sommercamp.md` | **OER-/IT-Sommercamp Weimar** (jährlich August, seit 2016): 10-Schritte-Erfolgsmodell, Jahresrückblicke 2016–2025 — 2016–18 Handlungsempfehlungen (7 Felder, Vorläufer der BMBF-OER-Strategie), 2019 OER-Contentbuffet, 2020 WLO-Geburt (200k Inhalte in 6 Mon.), 2021 Serlo-Editor, 2022 OER-Verlag, 2023 maschinenlesbare Lehrpläne, 2024 KI-Training (Edu-Feed Gewinner), 2025 EduFeed/Nostr/Chatbot/Klexikon; OER-Song für UNESCO 2nd World OER Congress 2017 | `/sommercamp/` |

### Bereich `edu-sharing-com` — Inhaltsübersicht

| Datei | Inhalt / Zielgruppe | Quelle |
|---|---|---|
| `001-ueberblick.md` | Startseite edu-sharing.com (metaVentis GmbH): Slogan, 3 Anwendungsbereiche (Cloudspeicher/Enterprise-Search/Bildungscloud), 6 Mehrwerte (BSI-geprüft, self-hosted), Referenzen NRW-Schulcloud/Berlin/Luxemburg, Release-Historie (9.1 Jan 2025, 9.0 Juni 2024, 8.1 Aug 2023, 8.0 Apr 2023), App, Webinar-Anfrage | `/` |
| `002-cloud-speicher.md` | **LMS Cloud Storage**: professionelles Dateimanagement mit Volltext-Indexierung, WebDAV (Mac Finder/Win Explorer), Plug-ins Moodle/OPAL/ILIAS/MediaWiki, Test-Zugang (lehrer/baum), Rendering-Service für QTI/Etherpad/SCORM/Moodle-Kurse, Tracking für Verwertungsgesellschaften | `/cloud-speicher/` |
| `003-enterprise-search.md` | **Portal + Suchmaschine**: Einfeld- und Facetten-Suche, performant auch bei 10.000 Katalogwerten; Schnittstellen (Elixir, OAI-PMH, Metadaten-Mapping); Integrationen (Wikimedia Commons, DDB, YouTube, Serlo, Landesmedien, Verlagssysteme); Zwei Perspektiven OER-Schaufenster vs. Mediendistribution; Lizenzeditor, Tracking | `/enterprise-search/` |
| `004-bildungs-cloud.md` | **Bildungs-Cloud**: organisationsübergreifend; Tool-Integration (Moodle/OPAL/ILIAS + MediaWiki/Vanilla-Forum/Etherpad + ONYX Testsuite + Liferay); didaktische Vorlagen; Vision „Portable Cloud“ (Nutzer behält Cloud-Speicher beim Organisationswechsel); Shibboleth/SSO | `/bildungs-cloud/` |
| `005-produkt-features.md` | **Feature-Referenz** nach 4 Stakeholder-Rollen (Lehrende/Redaktionen/Autoren/Betreiber): Safe, redaktionelle Sammlungen, Workflows, To-dos, ONLYOFFICE/QTI, LOM/Dublin Core/EAF/ELIXIER, WebDAV, Metadaten-Vererbung, LDAP/Shibboleth/SSO, Ordner-Templates, REST-API (OpenAPI/OAS), Docker, Corporate Design; 7 offizielle Plug-ins (Moodle/OnlyOffice/MediaWiki/ILIAS/ONYX/TYPO3/OpenOLAT); Doku 9.1 auf scrollhelp.site | `/produkt/` |
| `006-mitmachen-community.md` | Open-Source-Community (seit **2007**): GitHub (`edu-sharing-community-repository`), Issue-Tracker, #hack4OER; Dependency-Management auf **Alfresco**-Basis, **Docker-compose + Kubernetes + Helm**; Maven Git Workflow mit PROJECT_NAME-Präfix für Multi-Customer-Builds; Security-Kontakt `security@edu-sharing.com` | `/mitmachen/` + GitHub README |
| `007-jobs-impressum.md` | **metaVentis GmbH** (HRB 50 17 68 Jena, GF **Hupfer + Zobel**, Am Horn 21a Weimar); Arbeitskultur (remote + Daily 10 Uhr, Festanstellung auf Verhandlungsbasis); aktuell keine offenen Stellen, keine Initiativbewerbungen; 4-Schritt-Bewerbungsprozess identisch zum Verein; Vergleichstabelle GmbH vs. e.V. (Zobel als Brücke) | `/jobs/` + `/impressum/` |

### Bereich `oer` — Inhaltsübersicht

| Datei | Inhalt | Quelle |
|---|---|---|
| `001-bmbf-oer-strategie-ueberblick.md` | Kapitel I: Ausgangssituation, OER-Definition (UNESCO 2019), 21st Century Skills, 3 Handlungsziele, Einbettung in UN SDG 4 / EU-Aktionsplan / KMK | BMBF PDF, Juli 2022 |
| `002-bmbf-oer-strategie-handlungsfelder.md` | Kapitel II: 6 Handlungsfelder (OEP, Technische Infrastruktur, Forschung, DigitalPakt 6,5 Mrd., KI-Campus, QLB 91 Projekte) | BMBF PDF, Juli 2022 |
| `003-cc-lizenzwahl.md` | Lizenzwahl-Leitfaden: Bauchgefühl als schlechter Ratgeber, NC/ND/SA-Klauseln erhöhen Rechtsunsicherheit, Abwägung Vor-/Nachteile restriktiver Lizenzen | bpb.de, Till Kreutzer, CC BY 4.0 |
| `004-generierung-der-lizenz.md` | Schritt-für-Schritt-Anleitung zur CC-Lizenz-Generierung: License Chooser, drei Ebenen (Rechtstext, Deed, maschinenlesbarer CC-REL-Code) | bpb.de, Till Kreutzer, CC BY 4.0 |
| `005-creative-commons-lizenzierung-bei-verschiedenen-veroeffentlichungsformen.md` | Praxisleitfaden zur Anbringung von Lizenzhinweisen: Webseiten, Bücher/PDF (XMP, Anhang), Video/Audio/Radio/TV | bpb.de, Till Kreutzer, CC BY 4.0 |
| `006-die-suche-nach-open-content-im-internet.md` | Suchmaschinen und Content-Plattformen für Open Content: Google, Flickr, Wikimedia Commons, Vimeo, CC-Suche (YouTube, Jamendo, SoundCloud, Europeana) | bpb.de, Till Kreutzer, CC BY 4.0 |
| `007-oer-practical-guide-introduction.md` | Open Content Practical Guide — Ch. 1: Einleitung, „Some Rights Reserved", drei Grundprinzipien, Zielgruppe | Kreutzer, UNESCO/hbz/Wikimedia DE, CC BY 4.0 |
| `008-oer-practical-guide-basics.md` | Open Content Practical Guide — Ch. 2: FOSS-Hintergrund, CC-Initiative, Lizenzmodelle, Copyleft/SA, Benefits, rechtliche Aspekte, zentralisiert vs. dezentralisiert | Kreutzer, UNESCO/hbz/Wikimedia DE, CC BY 4.0 |
| `009-oer-practical-guide-cc-scheme.md` | Open Content Practical Guide — Ch. 3: Die sechs CC-Lizenztypen, CC0/Public Domain Mark, Ported/Unported, Licence Conditions, NC/ND/SA-Details inkl. Entscheidungs-Charts, Licence Compatibility | Kreutzer, UNESCO/hbz/Wikimedia DE, CC BY 4.0 |
| `010-oer-practical-guide-practical.md` | Open Content Practical Guide — Ch. 4+5: Lizenzwahl, License Chooser (3 Ebenen), Anbringung von Lizenzhinweisen (Web/PDF/Video/Audio), Open-Content-Suche (Google, Flickr, Wikimedia Commons, Vimeo, CC-Meta), Final Remarks | Kreutzer, UNESCO/hbz/Wikimedia DE, CC BY 4.0 |
| `011-oer-cc-lizenzen-faq.md` | FAQ zu CC-Lizenzen im OER-Kontext (14 Fragen): Kennzeichnung (Einzel/Mehrfach/Position), Lizenz-Button, BY finden, Zitatrecht, Änderungsumfang, Bearbeiter-Kette, Lizenz-Mix, Urheberpersönlichkeitsrecht, No-endorsement, Rechtsfolgen | Spielkamp/Weitzmann, iRights.info, CC BY-SA 4.0 |
| `012-oer-kombinieren-bearbeiten-remixen.md` | 8 Tipps zur OER-Verwendung: Lizenztext prüfen, ND-Übersichtstabelle, Verschmelzen vs. Zusammenstellen, strengste Lizenz gewinnt, Bearbeitung kennzeichnen („Ausschnitt, farbverändert“), Zitatrecht, gemeinfreie Inhalte (Public Domain Mark, CC0, amtliche Werke, NASA) | Steinhau/Pachali, iRights.info (Jointly/BMBF), CC BY 4.0 |
| `013-oer-was-ist-cc0.md` | CC0 — Freigabe mit „null Bedingungen“: rechtliche Komponenten (Verzicht/Lizenz/Non-Assertion), Vor-/Nachteile, Reproduktionen (Lichtbildwerk/Lichtbild/technisches Foto), Copyfraud, Quellen (Europeana, The Met, Openclipart, ZUM), Abgrenzung CC0 vs. Public Domain Mark | Steinhau/Pachali, iRights.info (Jointly/BMBF), CC BY 4.0 |
| `014-oer-gemischte-materialien.md` | Umgang mit gemischten Materialien: Schöpfungshöhe, zusammengesetzte Werke, „auflösende Bedingung“ bei Lizenzverstoß, Lizenzhinweise pro Werk vs. zentral, License Chooser mit 3 Ebenen (Deed / Legal Code / Digital Code) | El-Auwad, iRights.info (Crosspost OERinfo), CC BY 4.0 |
| `015-oer-ki-und-oer.md` | KI und OER (Stand 2023): Funktionsweise generativer KI (Training, Prompts), § 2 Abs. 2 UrhG, reine KI-Schöpfungen sind gemeinfrei, Schöpfungshöhe bei Bearbeitungen (Bild/Text/Musik), Empfehlung CC0/CC BY, Metadaten-Hinweise, Nutzungsbedingungen der Anbieter beachten | Fischer, iRights.info (Crosspost OERinfo), CC BY 4.0 |
| `016-oer-veraendern-und-lizenzieren.md` | OER bearbeiten: was zählt als Bearbeitung (Übersetzung, Cropping, Kolorierung), was nicht (Formatwechsel, Zusammenstellen, reine Faktendarstellung, Inspiration); konkrete Beispiele für korrekte Lizenzhinweise bei Bearbeitungen | Rack (iRights.Law/FIZ Karlsruhe), iRights.info (Crosspost OERinfo), CC BY 4.0 |
| `017-oer-gold-standard-kompendium.md` | Gold-Standard für professionelle OER-Erstellung nach 10 Materialarten (Arbeitsblätter/H5P, Blogs/Webseiten/WordPress, Folien, Fotos, Maker, Onlinekurse, Podcasts, Spiele, Texte, Videos); Werkzeug-Empfehlungen, No-Gos, Lizenzierungsbeispiele, Barrierefreiheit, TULLU-Regel | Fabri/Fahrenkrog/Muuß-Merholz (Hrsg.), ZLL21 Verlag (OERinfo/OERcamps), CC BY 4.0 |
| `018-oer-timeline-entwicklungsphasen.md` | OER-Timeline mit Meilensteinen (UNESCO 2002, MIT OCW, OpenLearn 2006, World Congress 2012, Schultrojaner, OERcamp, Koalitionsvertrag 2013, BMBF-Strategie 2022); 3 Entwicklungsphasen (Idee / Bewegung / Systemphase) mit WLO-Anschluss | Synthese aus H5P-OER-Timeline, CC BY 4.0 |
