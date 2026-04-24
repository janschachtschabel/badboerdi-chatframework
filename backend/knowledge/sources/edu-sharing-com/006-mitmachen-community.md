---
id: escom-mitmachen-006
title: "Mitmachen in der edu-sharing Open-Source-Community (GitHub, Hackathons, FAQ)"
source: "https://edu-sharing.com/mitmachen/"
updated: 2025-01-01
license: "CC BY 4.0"
attribution: "metaVentis GmbH"
tags: [edu-sharing, community, github, open-source, mitmachen, hackathon, hack4oer, issue-tracker, entwicklerdoku, maven, docker, kubernetes, helm, alfresco, projekt-2007, security, oer]
chunk_strategy: paragraph
lang: de
status: active
---

# Mitmachen in der edu-sharing Open-Source-Community

**URL**: <https://edu-sharing.com/mitmachen/> | **GitHub**: <https://github.com/edu-sharing/edu-sharing-community-repository> | **Lizenz**: CC BY 4.0

> **In der edu-sharing Open-Source-Community Spuren hinterlassen.**

---

## 4 Wege zum Mitmachen

1. **Kontakt aufnehmen** — aktuelle Informationen und Veranstaltungshinweise der Community erhalten
2. **Auf GitHub** an der Open-Source-Software mitentwickeln
3. Als **Bildungsorganisation, Betreiber oder Softwarehersteller** edu-sharing-**Partner** werden
4. Als neues **Teammitglied bewerben** (UX-Design, Softwareentwicklung, Projekt-/Produkt-Management)

---

## GitHub und Issue-Tracker

### Code

**Repository**: <https://github.com/edu-sharing/edu-sharing-community-repository>

### Community Mitglied

> Im **edu-sharing NETWORK e.V.** kannst du **Innovation und Qualitätssicherung** mitgestalten.

### Bugs und Ideen

> In unserem **Issue-Tracker** kannst du Bugs oder Weiterentwicklungs-Ideen eintragen und verfolgen.

---

## Hackathons und Workshops

### #hack4OER

> Unsere Community organisiert Hackathons und Workshops. Hier treffen sich **Bildungsexperten und Aktive**, erdenken Lösungen und **„hacken diese an"**. Daraus entstehen Projekte in der Anwender-/Partnergemeinschaft, deren Ergebnisse in den **Open-Source-Quellcode** eingehen.

### Kunden-Statement

> „Vielen Dank für drei tolle Tage in Weimar beim **#hack4oer**"
>
> — **Bildungsportal Sachsen GmbH** über Twitter

---

## FAQ-Block der Mitmachen-Seite

- Wie kann ich mitmachen?
- Was ist ein Hackathon?
- Was ist **#hack4OER**?
- Was ist **OER**?

---

## Entwicklerdoku — GitHub-README (Community Repository)

### Projektgeschichte

> The edu-sharing open-source project started in **2007** to develop **networked E-Learning environments** for managing and sharing educational contents **inter-organisationally**.

### Release-Distribution

- Source + Binaries aus Artifact Repository
- **Ready-to-use** Docker-compose + Kubernetes Package für jeden Release
- Releases Page auf GitHub

### Security

> If you found something which might could be a **vulnerability or a security issue**, please contact us first instead of making a public issue. → `security@edu-sharing.com`

### Dependency Management

- Third-party-Dependencies im Alfresco class path unter `backend/alfresco/module`
- Verhindert Dependency-Konflikte zwischen edu-sharing und Alfresco

**Scope-Regeln**:

- **Inside Alfresco**:
  - `provided` — library kommt mit Alfresco distribution
  - `runtime` — imported for edu-sharing, nicht Alfresco
  - `compile` — für Alfresco oder edu-sharing
- **Inside edu-sharing**:
  - `provided` — immer für alle Third-party-Libs
  - `compile` — nur für edu-sharing-Interne

### Maven Git Workflow

Maven-Artifacts, Docker-Images, Helm-Charts werden **basierend auf Git-Branch-Namen oder Tag** versioniert.

- Aus `maven/fixes/10.0` → Artifact-Version: `<artifactid>:maven-fixes-10.0-SNAPSHOT`

### Feature Branch Workflow

**Muster**: `maven/feature/<version>-My-Fancy-Feature`

- Produziert Artifact: `<artifactid>:maven-fixes-<version>-SNAPSHOT`
- **Beispiel**: `maven/feature/10.0-My-Fancy-Feature` → `maven-fixes-10.0-SNAPSHOT`

### PROJECT_NAME-Präfix (Conflict-Prävention)

Umgebungsvariable `PROJECT_NAME` präfixt Artifacts:

- `PROJECT_NAME=community-` + `maven/feature/10.0-My-Fancy-Feature`
- → `<artifactid>:community-maven-fixes-10.0-SNAPSHOT`

> Wichtig: **alle Projekte** müssen mit demselben PROJECT_NAME gebaut werden.
>
> Wird durch das Tool **`edu-dev-tools ij`-Kommando** automatisch behandelt.

### Maven-Property

> Die Maven-Property `project.version.base` wird **immer auf** `maven-fixes-<version>-SNAPSHOT` gesetzt — praktisch für extern verwaltete Projekte wie `rendering-service-2`.

---

## Querverweise

- `001-ueberblick.md` — Positionierung
- `005-produkt-features.md` — REST-API (OAS), Docker, Self-hosting, Open-Source-Community-Rolle
- `007-jobs-impressum.md` — Team bei metaVentis GmbH
- `edu-sharing-network/001-verein-ueberblick.md` — edu-sharing NETWORK e.V. als Community-Heimat
- `edu-sharing-network/006-hackathoern.md` — aktuelle Hackathon-Aktivitäten (HackathOERn)
- `edu-sharing-network/007-sommercamp.md` — OER- und IT-Sommercamp Weimar

## Einordnung

Die Mitmach-Seite ist die **Brücke** zwischen **kommerzieller Produktwebsite (metaVentis)** und **Community-Verein (edu-sharing network e.V.)**. Wichtig:

- **edu-sharing läuft seit 2007** — fast 20 Jahre Entwicklungsgeschichte, was die Alfresco-Basis erklärt
- **Alfresco** als unterliegendes ECM-Framework ist im Dependency-Tree klar sichtbar
- **Docker-compose + Kubernetes + Helm** → modernes Deployment-Setup
- **`edu-dev-tools ij`** ist ein internes Tool für das Entwickler-Onboarding
- Der ausgeklügelte **Branch-basierte Maven-Workflow** mit `PROJECT_NAME`-Präfix ermöglicht **Multi-Customer-Builds ohne Artifact-Konflikte** — wichtig, weil es viele Landes-/Kunden-Anpassungen gibt (NRW, Berlin, Luxemburg, SWITCH etc.)
- **Security-Kontakt** `security@edu-sharing.com` explizit → professioneller OSS-Umgang mit Vulnerabilities

