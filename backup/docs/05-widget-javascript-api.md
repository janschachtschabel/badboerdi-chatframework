# Widget-JavaScript-API (Embed-Integration)

Diese Doku beschreibt **alle** öffentlichen JavaScript-Schnittstellen des
``<badboerdi-chat>``-Widgets — also die Knöpfe, mit denen einbettende
Hosts (WordPress, Edu-Sharing, eigene Web-Apps) die Widget-Funktionalität
steuern und auf Bot-Ereignisse reagieren können.

Die Schnittstellen sind in zwei Kanälen verfügbar:

* **Custom-Element-Embed** (`<badboerdi-chat>`-HTML-Tag): Inputs werden
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
| **Embed-Modi** | `cards-enabled` | Input | `true` |
| | `canvas-enabled` | Input | `true` |
| | `ai-content-enabled` | Input | `true` |
| | `quick-replies-enabled` | Input | `true` |
| **Lotsen-Modus** | `guide-mode` | Input | `false` (per Default-Setting) |
| | `emit-guide-suggestion` | Input | `false` |
| **Link-Handling** | `intercept-edu-sharing-links` | Input | `false` |
| **Events (window)** | `badboerdi:page-action` | Output | — |
| | `badboerdi:guide-suggestion` | Output | gated |
| **Outputs (Angular)** | `(pageAction)` | Output | — |
| | `(guideSuggestion)` | Output | gated |
| | `(linkClicked)` | Output | gated |

---

## Inputs (Attribute / Property-Bindings)

### Embed-Modi (Display-Toggles)

Die vier Booleans steuern, **was** vom Widget angezeigt wird. Alle
default auf `true`; Setzen auf `"false"` (String im HTML) oder `false`
(Boolean in Angular) deaktiviert das Feature.

#### `cards-enabled`

* `true` (Default): Treffer als interaktive Kacheln im Chat/Canvas.
* `false`: keine Kacheln — Backend rendert Treffer als dezente
  Inline-Markdown-Links am Antwort-Ende. Max-Anzahl aus Studio-Setting
  `cards_inline_link_limit` (Default 5).

```html
<!-- Schlanke Themenseiten-Integration: nur Chat-Text + Inline-Links -->
<badboerdi-chat cards-enabled="false"></badboerdi-chat>
```

#### `canvas-enabled`

* `true` (Default): Canvas-Pane öffnet sich bei Material-Erzeugung
  (Arbeitsblatt, Lernpfad, …) und kann Kachel-Listen aufnehmen.
* `false`: Canvas wird nie geöffnet. Material-Erzeugung rendert das
  Markdown direkt im Chat-Verlauf.

#### `ai-content-enabled`

* `true` (Default): Material-Erzeugungs-Pattern (PAT-21) + Lernpfad
  (PAT-19) sind aktiv.
* `false`: Backend lehnt Erzeugungs-Anfragen freundlich ab
  (Standard-Text aus `widget-modes.yaml`) und bietet stattdessen
  Bestandsmaterialien an.

#### `quick-replies-enabled`

* `true` (Default): Quick-Reply-Pillen unter Bot-Antworten.
* `false`: keine Pillen sichtbar. Lotsen-`__guide__|…`-Buttons werden
  vom Backend stattdessen als Inline-Markdown am Antwort-Ende eingebaut.

---

### Lotsen-Modus

#### `guide-mode`

Aktiviert die Lotsen-Funktion: das Widget zeigt einen 🧭-Toggle im Header,
Treffer bekommen "Bring mich hin"-Buttons, und externe Content-Links
werden auf Repo-interne Render-URLs umgeschrieben (User bleibt im
WLO-Ökosystem).

```html
<badboerdi-chat guide-mode></badboerdi-chat>
```

Sichtbarkeit hängt zusätzlich von der Allow-Liste in `guide-mode.yaml`
(Studio-Setting) ab — auf nicht-allow-listed Hosts ist der Toggle
ausgeblendet.

#### `emit-guide-suggestion` (neu)

Aktiviert die **passive Top-Result-Emission** für externe Host-Reaktion.

* `false` (Default): kein Event, kein Effekt — Host sieht keinen
  Unterschied.
* `true`: bei **jedem** Bot-Turn, der Lotsen-eligible Cards enthält
  (`card.link` oder `card.guide_url` gesetzt), wird automatisch ein
  `badboerdi:guide-suggestion`-CustomEvent auf `window` gefeuert und das
  `(guideSuggestion)`-Output emittiert. Payload siehe unten.

Anwendungsfall: Edu-Sharing-Sidebar, WordPress-Sticky-Banner, andere
Embed-Hosts, die automatisch auf Bot-Empfehlungen reagieren wollen — ohne
dass der User aktiv "lotse mich" sagt.

```html
<badboerdi-chat
  guide-mode
  emit-guide-suggestion="true">
</badboerdi-chat>

<script>
window.addEventListener('badboerdi:guide-suggestion', (e) => {
  const s = e.detail;  // GuideSuggestionPayload (siehe unten)
  console.log('Bot empfiehlt:', s.title, '→', s.url);
  // z.B. einen "Empfohlen"-Banner zeigen oder einen iframe wechseln
});
</script>
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
<badboerdi-chat intercept-edu-sharing-links="true"></badboerdi-chat>
```

---

## Outputs (Events)

### `badboerdi:page-action` (CustomEvent auf `window`)

**Wird gefeuert für jede Backend-`page_action`** — der generische Kanal
für alle host-relevanten Aktionen vom Bot.

Action-Typen:

| `action` | Wann | `payload` |
|---|---|---|
| `navigate` | User sagt explizit "bring mich hin" / "lotse mich" (siehe `GUIDE_NAV_INTENT_RE`-Regex) UND Lotsen-Treffer vorhanden | `{ url, label }` |
| `show_results` | Host-Seite mit Suchergebnis-Container (z.B. `/suche`) | `{ cards, query }` |
| `canvas_show_cards` | Widget-Canvas-Pane soll Kachel-Liste anzeigen | `{ cards, query, pagination, append }` |
| `canvas_open` | Canvas öffnen mit Material-Markdown | `{ material_type, title, markdown }` |
| `canvas_update` | Canvas-Markdown updaten (Edit-Pattern) | `{ markdown }` |
| `canvas_close` | Canvas schließen | `{}` |

```js
window.addEventListener('badboerdi:page-action', (e) => {
  const { action, payload } = e.detail;
  switch (action) {
    case 'navigate':
      console.log('Navigate request:', payload.url, '→', payload.label);
      break;
    case 'show_results':
      // payload.cards enthält die Card-Liste — kann z.B. in einem
      // eigenen Container gerendert werden statt in der Standard-Canvas
      break;
  }
});
```

Angular-Equivalent: `(pageAction)`-Output am `<badboerdi-chat>`-Element.

---

### `badboerdi:guide-suggestion` (CustomEvent auf `window`, neu)

**Passive Top-Result-Anzeige** — feuert bei **jedem** Bot-Turn mit
Lotsen-eligible Cards, sobald `emit-guide-suggestion="true"` gesetzt ist.

Im Gegensatz zu `navigate` (was nur bei expliziter User-Anfrage feuert)
ist das hier ein "Hier ist der beste Treffer, falls du was tun willst"-
Signal, das die Host-Seite nach Belieben konsumieren kann.

**Payload-Schema** (`GuideSuggestionPayload`):

```typescript
interface GuideSuggestionPayload {
  /** Repo-aware Klick-Ziel — identisch zu card.link */
  url: string;
  /** Card-Titel (Display-Label) */
  title: string;
  /** edu-sharing node-ID (UUID), oder leer */
  node_id: string;
  /** 'topic_page' | 'collection' | 'content' */
  node_type: string;
  /** Die User-Query, die diesen Treffer produziert hat */
  query: string;
  /** Weitere Lotsen-Treffer in Display-Reihenfolge (für Top-N-UIs) */
  alternatives: Array<{
    url: string;
    title: string;
    node_id: string;
    node_type: string;
  }>;
}
```

**Beispiel-Empfang:**

```html
<badboerdi-chat
  guide-mode
  emit-guide-suggestion="true">
</badboerdi-chat>

<script>
window.addEventListener('badboerdi:guide-suggestion', (e) => {
  const s = e.detail;

  // Top-1 Banner
  document.getElementById('bot-suggestion-banner').innerHTML = `
    <strong>Bot empfiehlt:</strong>
    <a href="${s.url}" target="_blank">${s.title}</a>
    <small>(${s.node_type})</small>
  `;

  // Top-N Liste
  const list = document.getElementById('bot-alternatives');
  list.innerHTML = s.alternatives
    .slice(0, 4)
    .map(a => `<li><a href="${a.url}">${a.title}</a></li>`)
    .join('');
});
</script>
```

Angular-Equivalent: `(guideSuggestion)`-Output, gleiche Payload.

**Trigger-Bedingungen** (Backend + Frontend):

* `emit-guide-suggestion="true"` ist gesetzt
* Antwort enthält mindestens eine Card mit `card.link` oder
  `card.guide_url` (im Lotsen-Modus auf Allow-listed Repo-Hosts gesetzt)

Bei Klärungs-Turns ohne Treffer oder ohne Lotsen-Modus wird **nicht**
gefeuert.

---

### `(linkClicked)` Angular-Output (gated)

Nur aktiv bei `intercept-edu-sharing-links="true"`. Feuert mit
`pathname + search` (z.B. `/edu-sharing/components/collections?id=…`),
wenn der User im Bot-Text auf einen edu-sharing-Markdown-Link klickt.

```html
<badboerdi-chat
  intercept-edu-sharing-links="true"
  (linkClicked)="onBotLink($event)">
</badboerdi-chat>
```

---

## Embed-Beispiele (vollständig)

### 1. Default — alles an (Widget wie aus dem Standard-Deployment)

```html
<script src="https://wlo-mcp-server.vercel.app/widget/main.js" defer></script>
<badboerdi-chat></badboerdi-chat>
```

### 2. Schlanke Themenseiten-Integration

Nur Chat-Text + dezente Inline-Links, kein Canvas, keine KI-Erzeugung:

```html
<badboerdi-chat
  cards-enabled="false"
  canvas-enabled="false"
  ai-content-enabled="false">
</badboerdi-chat>
```

### 3. Edu-Sharing-Sidebar mit Bot-Empfehlungs-Banner

Widget läuft im Lotsen-Modus, der Top-Treffer wird automatisch an die
Sidebar weitergegeben:

```html
<aside id="bot-sidebar">
  <badboerdi-chat
    guide-mode
    emit-guide-suggestion="true">
  </badboerdi-chat>
  <div id="bot-suggestion-banner"></div>
</aside>

<script>
window.addEventListener('badboerdi:guide-suggestion', (e) => {
  const banner = document.getElementById('bot-suggestion-banner');
  const s = e.detail;
  banner.innerHTML = `
    <h4>Aktuelle Empfehlung</h4>
    <p>
      <a href="${s.url}" class="primary-cta">${s.title}</a>
      <span class="meta">${s.node_type}</span>
    </p>
  `;
});
</script>
```

### 4. WordPress mit Link-Interception (iframe-Routing)

Klicks auf edu-sharing-Links sollen NICHT navigieren, sondern an die
WP-Theme-JS gehen, die dann ein bestehendes iframe wechselt:

```html
<badboerdi-chat
  guide-mode
  intercept-edu-sharing-links="true"
  id="wp-bot">
</badboerdi-chat>

<script>
document.getElementById('wp-bot').addEventListener('linkClicked', (e) => {
  // e.detail = '/edu-sharing/components/collections?id=…'
  document.getElementById('content-iframe').src =
    'https://repository.openeduhub.net' + e.detail;
});
</script>
```

### 5. Minimal-Bubble (z.B. Footer-Chat)

Praktisch nur Text-Chat ohne extra UI-Elemente:

```html
<badboerdi-chat
  cards-enabled="false"
  canvas-enabled="false"
  ai-content-enabled="false"
  quick-replies-enabled="false">
</badboerdi-chat>
```

---

## Erweiterte Hooks (Programmatic API)

Diese sind nur für fortgeschrittene Integrationen relevant.

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
```

### CSS-Customizing

Das Widget exponiert eine CSS-Variable für die Akzentfarbe:

```css
badboerdi-chat {
  --boerdi-primary: #b91c1c;   /* WLO-Rot statt Default-Blau */
}
```

Wird für Header-Hintergrund, "Bring mich hin"-Buttons, Kacheln-Akzente
und Quick-Reply-Pillen verwendet. Default fallback `#1c4587`.

---

## Versionierung und Stabilität

| API-Element | Stabilität |
|---|---|
| Embed-Mode-Inputs (`cards-enabled`, `canvas-enabled`, `ai-content-enabled`, `quick-replies-enabled`) | **stable** seit v0.5 |
| `guide-mode` | **stable** seit v0.4 |
| `emit-guide-suggestion` + `badboerdi:guide-suggestion` | **stable** seit v0.7 (Card-Pipeline v2) |
| `intercept-edu-sharing-links` + `linkClicked` | **stable** seit v0.3 |
| `badboerdi:page-action` mit `navigate`/`show_results`/`canvas_*` Actions | **stable** seit v0.4 |
| Direkter Method-Zugriff via `@ViewChild` | **internal** — kann sich ändern |

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
