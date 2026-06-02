# Widget-JavaScript-API (Embed-Integration)

> **Welle E (2026-05-23) — entfernte Attribute:** `cards-enabled`,
> `canvas-enabled`, `inline-result-grouping`, `quick-replies-enabled`,
> `show-guide-button`, `guide-mode-default` existieren **nicht mehr**.
> Layout-Steuerung (Gruppen-Boxen, Limits, Schriftgröße,
> Quick-Reply-Anzahl, KI-Material-Box) liegt zentral im Studio-Tab
> **🎨 Anzeige** (`01-base/display-rules.yaml`). Lotsen-Modus ist immer
> aktiv (kein UI-Toggle), Canvas-Pane wurde durch InlineDocument-Box im
> Chat-Verlauf ersetzt. Übrig bleiben: `api-url`, `position`,
> `primary-color`, `initial-state`, `greeting`, `auto-context`,
> `page-context`, `persist-session`, `session-key`,
> `session-cookie-domain`, `session-cookie-max-age`, `trusted-domains`,
> `show-debug-button`, `show-language-buttons`, `ai-content-enabled`,
> `emit-guide-suggestion`, `emit-routing-debug`,
> `intercept-edu-sharing-links`.

Diese Doku beschreibt **alle** öffentlichen JavaScript-Schnittstellen des
``<boerdi-chat>``-Widgets — also die Knöpfe, mit denen einbettende
Hosts (WordPress, Edu-Sharing, eigene Web-Apps) die Widget-Funktionalität
steuern und auf Bot-Ereignisse reagieren können.

Die Schnittstellen sind in zwei Kanälen verfügbar:

* **Custom-Element-Embed** (`<boerdi-chat>`-HTML-Tag): Inputs werden
  als HTML-Attribute gesetzt, Events als globale CustomEvents auf `window`
  konsumiert.
* **Angular-Component**: Inputs werden als Property-Binding gesetzt
  (`[input]=…`), Events als `(output)`-Binding konsumiert. Gleiche
  Payloads.

Beide Kanäle sind gleichwertig — wähle den, der zur Host-Integration passt.

---

## Quick-Reference

| Kategorie | Name | Richtung | Default |
|---|---|---|---|
| **Grundkonfig** | `api-url` | Input | `''` (relative `/api`) |
| | `position` | Input | `bottom-right` |
| | `initial-state` | Input | `collapsed` |
| | `primary-color` | Input | `#1c4587` |
| | `greeting` | Input | `''` (Backend-Default) |
| | `auto-context` | Input | `true` |
| | `page-context` | Input | `''` |
| **Session** | `persist-session` | Input | `true` |
| | `session-key` | Input | `boerdi_session_id` |
| | `session-cookie-domain` | Input | `''` |
| | `session-cookie-max-age` | Input | `2592000` (30 Tage) |
| | `trusted-domains` | Input | `''` |
| **Embed-Modi (Welle E)** | `ai-content-enabled` | Input | `true` — KI-Content (M10/M11) pro Embed deaktivierbar |
| **UI-Toggles** | `show-debug-button` | Input | `true` |
| | `show-language-buttons` | Input | `true` |
| | `emit-guide-suggestion` | Input | `false` |
| | `emit-routing-debug` | Input | `false` |
| **Link-Handling** | `intercept-edu-sharing-links` | Input | `false` |
| **Events (window)** | `badboerdi:page-action` | Output | immer aktiv |
| | `badboerdi:guide-suggestion` | Output | gated |
| | `badboerdi:routing-debug` | Output | gated |
| | `badboerdi:query-meta` | Output | immer aktiv |
| **Outputs (Angular)** | `(pageAction)` | Output | immer aktiv |
| | `(guideSuggestion)` | Output | gated |
| | `(routingDebug)` | Output | gated |
| | `(queryMeta)` | Output | immer aktiv |
| | `(linkClicked)` | Output | gated |
| **Public JS-API** | `openChatbot()` | Methode | — |
| | `closeChatbot()` | Methode | — |
| | `toggleChatbot()` | Methode | — |
| | `isChatbotOpen()` | Methode | — |

---

## Inputs (Attribute / Property-Bindings)

### Grundkonfiguration

#### `api-url`

Backend-API-URL. Wenn leer, wird relativ zum Host aufgelöst (`/api`).

```html
<boerdi-chat api-url="https://chat.example.com"></boerdi-chat>
```

#### `position`

Anker-Position des FAB-Buttons auf der Seite.

* `bottom-right` (Default)
* `bottom-left`
* `top-right`
* `top-left`

```html
<boerdi-chat position="bottom-left"></boerdi-chat>
```

#### `initial-state`

Startzustand des Panels.

* `collapsed` (Default): nur FAB-Button sichtbar
* `expanded`: Chat-Panel sofort offen

```html
<boerdi-chat initial-state="expanded"></boerdi-chat>
```

#### `primary-color`

Akzentfarbe als CSS-Hex-Wert. Überschreibt den Default `#1c4587`. Wird
für Header-Hintergrund, Kacheln-Akzente, Quick-Reply-Pillen und
"Bring mich hin"-Buttons verwendet. Alternativ per CSS-Variable
`--boerdi-primary` setzbar.

```html
<boerdi-chat primary-color="#8b0000"></boerdi-chat>
```

#### `greeting`

Überschreibt die initiale Begrüßungs-Nachricht des Bots. Wenn leer,
wird der Backend-Default aus der Chatbot-Config verwendet.

```html
<boerdi-chat greeting="Hallo! Wie kann ich dir beim Lernen helfen?"></boerdi-chat>
```

#### `auto-context`

Automatische Erkennung des Seitenkontexts (URL, Titel, Query-Params,
Referrer, Themenseiten-Slug). Der erkannte Kontext wird als
`environment.page_context` an das Backend gesendet.

* `true` (Default): automatische Erkennung aktiv
* `false`: keine auto-Detection — Kontext nur via `page-context`

```html
<boerdi-chat auto-context="false"></boerdi-chat>
```

#### `page-context`

Expliziter Seitenkontext als JSON-String oder Objekt. Ergänzt oder
überschreibt den auto-detected Kontext.

```html
<boerdi-chat page-context='{"collection_id":"abc-123","topic":"Bruchrechnung"}'></boerdi-chat>
```

---

### Session-Management

#### `persist-session`

Sitzung in `localStorage` über Seitennavigation hinweg persistieren.

* `true` (Default): Session-ID wird gespeichert; bei Reload setzt der
  Chat dort fort, wo er aufgehört hat.
* `false`: jede Seite startet eine neue Session.

#### `session-key`

Storage-Key für die persistierte Session-ID. Default: `boerdi_session_id`.
Nützlich wenn mehrere Widgets auf derselben Domain laufen und eigene
Sessions brauchen.

```html
<boerdi-chat session-key="my_custom_session"></boerdi-chat>
```

#### `session-cookie-domain`

Cookie-Domain für Cross-Subdomain-Session-Sharing. Wenn gesetzt, wird
die Session-ID zusätzlich als Cookie geschrieben, damit sie über
Subdomains hinweg geteilt wird (z.B. von `repository.openeduhub.net`
nach `redaktion.openeduhub.net`).

```html
<boerdi-chat session-cookie-domain=".openeduhub.net"></boerdi-chat>
```

#### `session-cookie-max-age`

Cookie-Lebensdauer in Sekunden. Default: `2592000` (30 Tage).

#### `trusted-domains`

Komma-separierte Whitelist von Hostnamen für die Session-ID-Übergabe
via `?bsid=`-URL-Parameter (Cross-TLD-Bridge). Wird mit der
Backend-`trusted_domains`-Liste aus `guide-mode.yaml` gemerged.

```html
<boerdi-chat trusted-domains="wirlernenonline.de,openeduhub.net"></boerdi-chat>
```

---

### Embed-Modi (Welle E — auf das Minimum reduziert)

#### `ai-content-enabled`

* `true` (Default): Material-/Lernpfad-Erzeugungs-Pattern (M09 / M10 / M11) sind aktiv.
* `false`: Backend lehnt Erzeugungs-Anfragen freundlich ab
  (Standard-Text aus `widget-modes.yaml`) und bietet stattdessen
  Bestandsmaterialien an.

Studio-Default + Pattern-Gates können denselben Effekt erzielen; das
Host-Attribut hat Vorrang als embed-spezifische Härtung — z.B. wenn
eine Plattform selbst KI-Content-Tools mitbringt und Doppel-Generierung
verhindern will.

```html
<boerdi-chat ai-content-enabled="false"></boerdi-chat>
```

> **Entfernt in Welle E (2026-05-23)** — die folgenden Attribute
> existieren **nicht mehr**:
> `cards-enabled`, `canvas-enabled`, `inline-result-grouping`,
> `quick-replies-enabled`, `show-guide-button`, `guide-mode-default`.
> Layout (Gruppen-Boxen, Limits, Schriftgrößen, Quick-Reply-Anzahl,
> KI-Material-Box) liegt zentral im Studio-Tab **🎨 Anzeige**
> (`01-base/display-rules.yaml`). Canvas-Pane wurde durch InlineDocument-
> Box im Chat-Verlauf ersetzt. Lotsen-Modus ist immer aktiv, der
> 🧭-Toggle im Header ist dauerhaft entfernt.

---

### UI-Toggles

#### `show-debug-button`

Zeigt den Debug-Toggle-Button im Chat-Header. Default `true`. Für
Produktiv-Embeddings empfiehlt sich `false`.

#### `show-language-buttons`

Zeigt 🔊 TTS und 🎤 Mic-Aufnahme im Chat-Header bzw. Footer. Default
`true`. `false` verhindert auch den Browser-Mikrofon-Permission-Prompt
beim ersten Laden.

#### `emit-guide-suggestion`

Aktiviert die **passive Top-Result-Emission** für externe Host-Reaktion.

* `false` (Default): kein Event, kein Effekt.
* `true`: bei **jedem** Bot-Turn, der Lotsen-eligible Cards enthält
  (`card.link` oder `card.guide_url` gesetzt), wird automatisch ein
  `badboerdi:guide-suggestion`-CustomEvent auf `window` gefeuert und das
  `(guideSuggestion)`-Output emittiert. Payload siehe unten.

```html
<boerdi-chat
  guide-mode-default="true"
  emit-guide-suggestion="true">
</boerdi-chat>
```

#### `emit-routing-debug`

Aktiviert die **Routing-Telemetrie-Emission** pro Bot-Turn.

* `false` (Default): kein Event.
* `true`: nach jedem Bot-Turn wird ein `badboerdi:routing-debug`-
  CustomEvent auf `window` gefeuert mit dem vollständigen Routing-
  Payload (Pattern, Intent, State, Persona, Tools, RAG-Sources,
  Modifier). Nützlich für Integration-Debugging und Analytics.

```html
<boerdi-chat emit-routing-debug="true"></boerdi-chat>
```

---

### Link-Handling

#### `intercept-edu-sharing-links`

Steuert, wie das Widget mit Klicks auf edu-sharing-Markdown-Links im
Bot-Text umgeht.

* `false` (Default): normales Browser-Navigation (`_blank`-Tab).
* `true`: Navigation wird **unterdrückt**, stattdessen feuert das
  `(linkClicked)`-Output mit dem Pathname+Search (z.B.
  `/components/collections?id=…`). Der Host übernimmt die Navigation
  (z.B. eigenes iframe-Routing).

Wirkt **nur auf Markdown-Links im Bot-Text** — die Kacheln-Klicks
laufen über einen separaten Pfad (siehe `(pageAction)`).

```html
<boerdi-chat intercept-edu-sharing-links="true"></boerdi-chat>
```

---

## Outputs (Events)

### `badboerdi:page-action` (CustomEvent auf `window`)

**Wird gefeuert für jede Backend-`page_action`** — der generische Kanal
für alle host-relevanten Aktionen vom Bot.

Action-Typen:

| `action` | Wann | `payload` |
|---|---|---|
| `navigate` | User sagt explizit "bring mich hin" / "lotse mich" UND Lotsen-Treffer vorhanden | `{ url, label }` |
| `show_results` | Host-Seite mit Suchergebnis-Container (z.B. `/suche`) | `{ cards, query }` |
| `canvas_show_cards` | Widget-Canvas-Pane soll Kachel-Liste anzeigen | `{ cards, query, pagination, append }` |
| `canvas_open` | Canvas öffnen mit Material-Markdown | `{ material_type, title, markdown }` |
| `canvas_update` | Canvas-Markdown updaten (Edit-Pattern) | `{ markdown }` |
| `canvas_close` | Canvas schliessen | `{}` |

```js
window.addEventListener('badboerdi:page-action', (e) => {
  const { action, payload } = e.detail;
  switch (action) {
    case 'navigate':
      console.log('Navigate request:', payload.url, payload.label);
      break;
    case 'show_results':
      console.log('Cards:', payload.cards.length, 'Query:', payload.query);
      break;
  }
});
```

Angular-Equivalent: `(pageAction)`-Output am `<boerdi-chat>`-Element.

---

### `badboerdi:guide-suggestion` (CustomEvent auf `window`)

**Passive Top-Result-Anzeige** — feuert bei **jedem** Bot-Turn mit
Lotsen-eligible Cards, sobald `emit-guide-suggestion="true"` gesetzt ist.

Im Gegensatz zu `navigate` (was nur bei expliziter User-Anfrage feuert)
ist das hier ein "Hier ist der beste Treffer, falls du was tun willst"-
Signal, das die Host-Seite nach Belieben konsumieren kann.

**Payload-Schema** (`GuideSuggestionPayload`):

```typescript
interface GuideSuggestionPayload {
  url: string;        // Repo-aware Klick-Ziel (identisch zu card.link)
  title: string;      // Card-Titel
  node_id: string;    // edu-sharing node-ID (UUID)
  node_type: string;  // 'topic_page' | 'collection' | 'content'
  query: string;      // User-Query, die diesen Treffer produziert hat
  alternatives: Array<{
    url: string;
    title: string;
    node_id: string;
    node_type: string;
  }>;
}
```

```js
window.addEventListener('badboerdi:guide-suggestion', (e) => {
  const s = e.detail;
  console.log('Top:', s.title, s.url);
  console.log('Alternativen:', s.alternatives.length);
});
```

Angular-Equivalent: `(guideSuggestion)`-Output, gleiche Payload.

**Trigger-Bedingungen:**

* `emit-guide-suggestion="true"` ist gesetzt
* Antwort enthält mindestens eine Card mit `card.link` oder
  `card.guide_url`

Bei Klärungs-Turns ohne Treffer wird **nicht** gefeuert.

---

### `badboerdi:routing-debug` (CustomEvent auf `window`)

**Routing-Telemetrie** — feuert nach jedem Bot-Turn mit dem vollständigen
Routing-Payload, sobald `emit-routing-debug="true"` gesetzt ist.

**Payload-Schema** (`RoutingDebugPayload`):

```typescript
interface RoutingDebugPayload {
  pattern: string;          // Ausgewähltes Pattern (z.B. "PAT-05")
  intent: string;           // Erkannter Intent (z.B. "search_content")
  state: string;            // Verlaufs-Phase (z.B. "state-6")
  persona: string;          // Aktive Persona (z.B. "lotse")
  tools_called: string[];   // MCP-Tools die aufgerufen wurden
  rag_areas: string[];      // RAG-Bereiche die durchsucht wurden
  sources: string[];        // Quellen-Tags (z.B. ["mcp", "rag"])
  signals: string[];        // Routing-Signale (z.B. ["has_video_filter"])
  modifier: {
    tone: string;           // Ton (z.B. "freundlich")
    formality: string;      // Anrede (z.B. "du")
    override: boolean;      // Modifier-Override aktiv?
  };
}
```

```js
window.addEventListener('badboerdi:routing-debug', (e) => {
  const d = e.detail;
  console.log('Pattern:', d.pattern, 'Intent:', d.intent);
  console.log('Tools:', d.tools_called);
  console.log('Sources:', d.sources);
});
```

Angular-Equivalent: `(routingDebug)`-Output, gleiche Payload.

---

### `badboerdi:query-meta` (CustomEvent auf `window`)

**MCP-Suchanfragen-Metadaten** — feuert nach jedem Bot-Turn, der MCP-
Tool-Aufrufe enthielt. Liefert Details zu allen Suchanfragen die das
Backend an den MCP-Server gestellt hat (Tool, Suchbegriff, Filter,
Ergebniszahl, Such-URL).

Immer aktiv — kein Opt-in-Attribut nötig.

**Payload-Schema**:

```typescript
interface QueryMetaPayload {
  queries: QueryMetaEntry[];
}

interface QueryMetaEntry {
  tool_name: string;       // z.B. "search_wlo_content"
  query_type: string;      // z.B. "ngsearchword", "keyword_collections"
  search_term: string;     // Der tatsächliche Suchbegriff
  criteria: Array<{
    property: string;      // z.B. "ccm:taxonid"
    values: string[];      // URI-Werte
    label?: string;        // Human-readable (z.B. "Biologie")
  }>;
  pagination: {
    maxItems: number;
    skipCount: number;
    totalResults: number;
  };
  repository_url: string;  // Repo-Base-URL
  search_url: string;      // Direkt-Link zur Suche im Repo
}
```

```js
window.addEventListener('badboerdi:query-meta', (e) => {
  for (const q of e.detail.queries) {
    console.log(q.tool_name, q.search_term, q.search_url);
    console.log('Treffer:', q.pagination.totalResults);
  }
});
```

Angular-Equivalent: `(queryMeta)`-Output, gleiche Payload.

---

### `(linkClicked)` Angular-Output (gated)

Nur aktiv bei `intercept-edu-sharing-links="true"`. Feuert mit
`pathname + search` (z.B. `/edu-sharing/components/collections?id=…`),
wenn der User im Bot-Text auf einen edu-sharing-Markdown-Link klickt.

```html
<boerdi-chat
  intercept-edu-sharing-links="true"
  (linkClicked)="onBotLink($event)">
</boerdi-chat>
```

---

## Public JS-API (Programmatic Control)

Das Widget-Custom-Element exponiert vier Methoden für programmatische
Steuerung. Zugriff via `document.querySelector` oder `getElementById`:

```js
const bot = document.querySelector('boerdi-chat');

bot.openChatbot();              // Chat-Panel öffnen
bot.closeChatbot();             // Chat-Panel schliessen
bot.toggleChatbot();            // Öffnen/Schliessen umschalten
console.log(bot.isChatbotOpen()); // true | false
```

| Methode | Rückgabe | Beschreibung |
|---|---|---|
| `openChatbot()` | `void` | Öffnet das Chat-Panel (FAB wird zum Panel) |
| `closeChatbot()` | `void` | Schliesst das Chat-Panel (zeigt nur FAB) |
| `toggleChatbot()` | `void` | Toggle zwischen offen und geschlossen |
| `isChatbotOpen()` | `boolean` | `true` wenn Panel geöffnet, `false` wenn collapsed |

Anwendungsbeispiel — externes "Frag den Bot"-CTA:

```html
<button onclick="document.querySelector('boerdi-chat').openChatbot()">
  Frag den Bot
</button>
```

---

## Embed-Beispiele (vollständig)

### 1. Default — alles an

```html
<script src="https://chat.example.com/widget/main.js" defer></script>
<boerdi-chat api-url="https://chat.example.com"></boerdi-chat>
```

### 2. Schlanke Themenseiten-Integration

Nur Chat-Text + dezente Inline-Links, kein Canvas, keine KI-Erzeugung:

```html
<boerdi-chat
  cards-enabled="false"
  canvas-enabled="false"
  ai-content-enabled="false">
</boerdi-chat>
```

### 3. Edu-Sharing-Sidebar mit Bot-Empfehlungs-Banner

Widget läuft im Lotsen-Modus, der Top-Treffer wird automatisch an die
Sidebar weitergegeben:

```html
<aside id="bot-sidebar">
  <boerdi-chat
    guide-mode-default="true"
    emit-guide-suggestion="true">
  </boerdi-chat>
  <div id="bot-suggestion-banner"></div>
</aside>

<script>
window.addEventListener('badboerdi:guide-suggestion', (e) => {
  const s = e.detail;
  document.getElementById('bot-suggestion-banner').innerHTML =
    '<a href="' + s.url + '">' + s.title + '</a>';
});
</script>
```

### 4. WordPress mit Link-Interception (iframe-Routing)

Klicks auf edu-sharing-Links sollen NICHT navigieren, sondern an die
WP-Theme-JS gehen, die dann ein bestehendes iframe wechselt:

```html
<boerdi-chat
  guide-mode-default="true"
  intercept-edu-sharing-links="true"
  id="wp-bot">
</boerdi-chat>

<script>
document.getElementById('wp-bot').addEventListener('linkClicked', (e) => {
  document.getElementById('content-iframe').src =
    'https://repository.openeduhub.net' + e.detail;
});
</script>
```

### 5. Minimal-Bubble (z.B. Footer-Chat)

Praktisch nur Text-Chat ohne extra UI-Elemente:

```html
<boerdi-chat
  cards-enabled="false"
  canvas-enabled="false"
  ai-content-enabled="false"
  quick-replies-enabled="false">
</boerdi-chat>
```

### 6. Vollausstattung mit Telemetrie

Alle Features an, Lotsen-Modus aktiv, Debug-Events für Analytics:

```html
<boerdi-chat
  guide-mode-default="true"
  show-guide-button="false"
  emit-guide-suggestion="true"
  emit-routing-debug="true"
  primary-color="#8b0000"
  position="bottom-right">
</boerdi-chat>

<script>
window.addEventListener('badboerdi:query-meta', (e) => {
  for (const q of e.detail.queries) {
    analytics.track('mcp_search', {
      tool: q.tool_name,
      query: q.search_term,
      results: q.pagination.totalResults,
    });
  }
});

window.addEventListener('badboerdi:routing-debug', (e) => {
  analytics.track('routing', {
    pattern: e.detail.pattern,
    intent: e.detail.intent,
    tools: e.detail.tools_called,
  });
});
</script>
```

### 7. Cross-Domain-Session-Sharing

Session über mehrere WLO-Domains hinweg teilen:

```html
<boerdi-chat
  session-cookie-domain=".openeduhub.net"
  trusted-domains="wirlernenonline.de,openeduhub.net,openeduhub.de">
</boerdi-chat>
```

---

## Erweiterte Hooks (Programmatic API)

### Direkter Zugriff auf die Chat-Component

Wenn der Embed-Host das Widget als Angular-Component (nicht Custom-
Element) konsumiert, kann er das innere `<badboerdi-chat>` per
`@ViewChild` referenzieren und Methoden direkt rufen:

```typescript
@ViewChild('chat') chatRef?: ChatComponent;

sendBotMessage(text: string) {
  this.chatRef?.sendMessage(text);
}

resetSession() {
  this.chatRef?.restart();
}

updateContext(ctx: Record<string, any>) {
  this.chatRef?.updateContext(ctx);
}
```

### CSS-Customizing

Das Widget exponiert eine CSS-Variable für die Akzentfarbe:

```css
boerdi-chat {
  --boerdi-primary: #b91c1c;   /* WLO-Rot statt Default-Blau */
}
```

Wird für Header-Hintergrund, "Bring mich hin"-Buttons, Kacheln-Akzente
und Quick-Reply-Pillen verwendet. Default fallback `#1c4587`.

Alternativ als HTML-Attribut: `<boerdi-chat primary-color="#b91c1c">`.

---

## Versionierung und Stabilität

| API-Element | Stabilität |
|---|---|
| Embed-Mode-Inputs (`cards-enabled`, `canvas-enabled`, `ai-content-enabled`, `quick-replies-enabled`) | **stable** |
| Grundkonfig-Inputs (`api-url`, `position`, `primary-color`, `greeting`, `auto-context`) | **stable** |
| Session-Inputs (`persist-session`, `session-key`, `session-cookie-domain`, `trusted-domains`) | **stable** |
| UI-Toggles (`show-debug-button`, `show-language-buttons`, `show-guide-button`) | **stable** |
| `guide-mode-default` + Lotsen-Modus | **stable** |
| `emit-guide-suggestion` + `badboerdi:guide-suggestion` | **stable** |
| `emit-routing-debug` + `badboerdi:routing-debug` | **stable** |
| `badboerdi:query-meta` | **stable** |
| `intercept-edu-sharing-links` + `(linkClicked)` | **stable** |
| `badboerdi:page-action` mit `navigate`/`show_results`/`canvas_*` Actions | **stable** |
| Public JS-API (`openChatbot`, `closeChatbot`, `toggleChatbot`, `isChatbotOpen`) | **stable** |
| Direkter Method-Zugriff via `@ViewChild` (`sendMessage`, `restart`, `updateContext`) | **internal** — kann sich ändern |

Neue Inputs/Events werden additiv eingeführt und brechen keine bestehenden
Integrationen — bestehende Hosts ohne Attribute sehen das Legacy-Verhalten.

---

## Siehe auch

* [03-elemente.md](./03-elemente.md) — Datenstruktur der Cards
  (Card-Pipeline v2)
* [04-deployment.md](./04-deployment.md) — Widget-Build + Deployment +
  Studio-Settings
* [api-endpunkte.md](./api-endpunkte.md) — Backend-REST-API für direkte
  Server-Server-Integration ohne Widget
