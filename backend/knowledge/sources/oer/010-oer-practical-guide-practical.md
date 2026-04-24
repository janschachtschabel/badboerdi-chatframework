---
id: oer-practical-guide-practical-010
title: "Open Content — A Practical Guide: Practical Guidelines & Final Remarks"
source: "https://irights.info/wp-content/uploads/2014/11/Open_Content_A_Practical_Guide_to_Using_Open_Content_Licences_web.pdf"
updated: 2014-11-01
license: "CC BY 4.0"
attribution: "Dr. Till Kreutzer, published by German Commission for UNESCO, hbz, Wikimedia Deutschland"
tags: [oer, open-content, creative-commons, licence-chooser, legal-code, deed, cc-rel, licence-notice, attribution, xmp, pdf, search-engines, flickr, wikimedia-commons, vimeo, google, final-remarks]
chunk_strategy: paragraph
serie: "Open Content – A Practical Guide to Using Creative Commons Licences"
lang: en
---

# 4. Practical Guidelines: Using Creative Commons Licences

**Autor**: Dr. Till Kreutzer | **Quelle**: Open Content Practical Guide | **Lizenz**: CC BY 4.0

---

## 4.1 Choosing the "Right" Licence

The selection of the licence is an essential step in an Open Content strategy. Advantages and disadvantages should be thoroughly balanced before the material is licenced.

**Key questions**:
- Why do I licence my work under the CC scheme?
- Which rights do I want to reserve and why?

### Intuition is Not a Good Basis

In many cases, licence selection is based on intuition:
- *„I do not want anybody to make money with my work, so I use an NC license."*
- *„It should not be possible for a publisher to adopt the publications of our foundation and generate profit with it."*
- *„I will not have anybody tampering with my creative work, so I use an ND license."*

These arguments, although perfectly understandable from a psychological standpoint, are **not a good basis for selecting restrictive licences**.

### The Trade-off

Licence restrictions are always accompanied by the **risk of legal uncertainty**. They lead to complex legal questions and prevent uses that are actually in the licenser's interest and/or even actually permitted by the licence.

> This does not mean that one should decide for CC BY in all cases. There can be good reasons to opt for a more restrictive licence — but as these also have disadvantages for the licenser, it is recommended to carefully weigh up advantages and disadvantages, especially for broad Open Content publication strategies of companies or public institutions.

---

## 4.2 Generating the Licence

Attaching a CC licence to a work is very simple. The first step consists in going to the **CC Licence Chooser**:

> **Link**: <https://creativecommons.org/choose/>

To choose a CCPL4 licence, **two questions need to be answered** to determine the licence elements (ND, SA, NC). After that, the licence chooser displays:
- The respective licence
- Links to the licence text
- The short explanation of the licence features (the CC „Deed")
- An **HTML snippet** automatically generated for integration into websites

### The Three Layers of CC Licences

| Layer | Name | Function |
|---|---|---|
| **Ground** | **Legal Code** | Full text of the licence contract in "legalese". Main element from a legal perspective. |
| **Middle** | **CC Deed** / "Human Readable Version" | Short summary of the most relevant terms and conditions. Not a licence in the legal sense — serves as a user-friendly interface. |
| **Upper** | **Machine Readable Version** | Code snippet implementing **CC Rights Expression Language (CC REL)** — enables search engines to locate Open Content. |

As CC puts it:
> „Think of the Commons Deed as a user-friendly interface to the Legal Code beneath, although the Deed itself is not a licence, and its contents are not part of the Legal Code itself."

### Example HTML Snippet

```html
<a rel="license" href="http://creativecommons.org/licenses/by/4.0/">
  <img alt="Creative Commons License" style="border-width:0"
       src="https://i.creativecommons.org/l/by/4.0/88x31.png" />
</a><br />
This work is licensed under a
<a rel="license" href="http://creativecommons.org/licenses/by/4.0/">
  Creative Commons Attribution 4.0 International License
</a>.
```

---

## 4.3 Attaching CC Licences to Different Works

**Basic principle**: The licence should be attached in a way which allows any potential user to recognise the work as being licenced under a particular CC licence.

> **Rule of thumb**: The licence notice should be as evident as possible. The closer it is attached to the licenced work, the more likely it will be found by the user.

If the user is not aware that a particular work can be used under a CC licence, and does not know the terms, **no rights would be granted** and no licence contract would be concluded.

### Attaching the Licence to Web Content

In many cases, all content on a website is licenced under the same licence. Implement a **general licence notice in the footer** of each webpage. CC itself uses:

> "Except where otherwise noted, content on this site is licensed under a Creative Commons Attribution 4.0 International license."

Best practice:
- **Hyperlink** to the CC Deed (which links further to the legal code)
- **Licence logo as a banner** to attract attention

For **mixed content** (e.g. a photo on a CC BY website licensed by a third party under a different CC licence), attach the different notice **as close to the material as possible** — ideally in the caption with attribution notices.

### Licence Notices in Digital Documents or Books

| Scenario | Best Practice |
|---|---|
| **Entire publication** under same licence | Central licence notice in imprint or prominent location |
| **Occasional Open Content** (single photo, text, graph) | Notice attached directly — footnote or caption |
| **PDF technical option** | Embed the licence using **Extensible Metadata Platform (XMP)** |
| **Alternative** | Centralise notices in a descriptive annex with **evident reciprocal connection** to each work (page number, identifiers) |
| **Minimum** | Licence notices must include a reference to the licence text (hyperlink to CC) |
| **Optional** | Include the full licence text in the document |

> Remember: The more hidden the notice, the less likely it will be found — contrary to the interest of the licenser.

### Licence Notices in Videos, Music, Radio or TV Shows

Giving adequate notices in non-textual publications can be tricky.

- **If published online** — implement notices into the online source (simple solution)
- **If offline only** — notices must be integrated into the work itself
- **No general rule** possible due to the different nature of media types — many variants work

> **Key criterion**: The more prominent and descriptive these solutions are, the more likely they will be noticed by users.

---

## 4.4 Finding Open Content Online

### Search Engines

**Google** provides a specific Open Content search function in the **"advanced search"** options. Users can filter results by usage rights:
- „content that can be freely used and shared"
- „content that can be freely used and shared also for commercial purposes"

**Google Image Search** features the same function.

> **Link**: <https://www.google.com/advanced_search>

### Content Platforms

For certain content types, direct platform search is often **more convenient** than general search engines.

#### A) Open Content Images

**Flickr** — World's largest photo community. Millions of images, many under CC licences. The advanced search offers a respective CC-filter setting.

> **Link**: <https://www.flickr.com/search/advanced/>

**Wikimedia Commons** — Another large image archive. Most photos are published under a public licence or are in the public domain.

> **Link**: <https://commons.wikimedia.org>

#### B) Open Content Videos

**Vimeo** — Particularly progressive in the field of Open Content. Enables users to choose a CC licence before uploading. „Advanced filters" include a CC-licensed content option.

> **Link**: <https://vimeo.com>

#### C) Meta-Search via Creative Commons

The CC website features a special search function across multiple platforms:

| Platform | Content Type |
|---|---|
| **YouTube** | Videos |
| **Jamendo** | Music |
| **SoundCloud** | Music |
| **Europeana** | Cultural/historical works of various types |

> **Link**: <https://search.creativecommons.org>

---

## 5. Final Remarks

Open Content licences have the great potential of making it possible to **share copyright-protected content with others in a legally feasible and transparent way**. However, one needs to be aware of potential pitfalls. This is true for both the right holder and the user.

### For Users

Not only to be legally compliant, but also **in order to respect the rights of those who share their creative efforts freely** with others, every user should be aware of their duties and obligations.

### For Licensers

Those who would like to publish their content under a public licence should take an **informed decision** about the licence they choose.

> „The tendency to use restrictive licences, e.g. NonCommercial licences, is problematic for the free culture movement in general and can jeopardize the sharing of content, thereby most likely undermining the right holder's original objectives. It is therefore of utmost importance to think carefully about which licence will best meet one's own particular intentions."

---

## Übersicht: Praktische Entscheidungshilfe

| Medium / Szenario | Lizenzhinweis |
|---|---|
| **Webseite (einheitlich)** | Fußzeile-Notice + Lizenzlogo, Hyperlink zur Deed |
| **Webseite (einzelnes Werk mit abweichender Lizenz)** | Caption direkt am Werk |
| **Buch / Dokument (einheitlich)** | Impressum oder prominente Stelle |
| **Buch / Dokument (einzelnes Werk)** | Footnote oder Caption am Werk |
| **PDF technisch** | XMP-Metadata-Einbettung |
| **Alternative für Dokumente** | Anhang mit expliziten Verweisen je Werk |
| **Video / Audio / Broadcast online** | Notice in Online-Quelle |
| **Video / Audio / Broadcast offline** | Integration ins Werk selbst |

## Querverweise

- **007-oer-practical-guide-introduction.md** — Kapitel 1: Einleitung, drei Grundprinzipien (Teil desselben Guides)
- **008-oer-practical-guide-basics.md** — Kapitel 2: FOSS-Hintergrund, CC-Initiative, Benefits, zentralisiert vs. dezentralisiert (Teil desselben Guides)
- **009-oer-practical-guide-cc-scheme.md** — Kapitel 3: Die sechs CC-Lizenztypen, CC0/PDM, Ported/Unported, NC/ND/SA-Details, Licence Compatibility (Teil desselben Guides)
- Bereich `oer` → **003-cc-lizenzwahl.md** — Deutsche Kurzfassung: Lizenzwahl-Leitfaden
- Bereich `oer` → **004-generierung-der-lizenz.md** — Deutsche Kurzfassung: License Chooser, drei Ebenen
- Bereich `oer` → **005-creative-commons-lizenzierung-bei-verschiedenen-veroeffentlichungsformen.md** — Deutsche Kurzfassung: Anbringung von Lizenzhinweisen
- Bereich `oer` → **006-die-suche-nach-open-content-im-internet.md** — Deutsche Kurzfassung: Suchmaschinen und CC-Plattformen

