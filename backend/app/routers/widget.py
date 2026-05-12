"""Widget router — serves the embeddable BOERDi chat widget JS bundle.

Build the widget first via:
    cd frontend && npm run build:widget

The build output lands in `frontend/dist/widget/browser/`. This router exposes
that directory under `/widget/...` with permissive CORS headers so any host
page can embed it via:

    <script src="https://api.example.com/widget/boerdi-widget.js" defer></script>
    <boerdi-chat api-url="https://api.example.com"></boerdi-chat>
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response

router = APIRouter()

# Repo-root → backend/ → up one → frontend/dist/widget/browser
_REPO_ROOT = Path(__file__).resolve().parents[3]
_WIDGET_DIR_PRIMARY = _REPO_ROOT / "frontend" / "dist" / "widget" / "browser"
# Fallback: standalone backend deploy without sibling frontend tree
# (populated by `scripts/sync-widget-to-backend.{sh,ps1}`).
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_WIDGET_DIR_FALLBACK = _BACKEND_DIR / "widget_dist"


def _active_widget_dir() -> Path:
    """Return the first widget directory that exists.

    Picks the live frontend build first, then falls back to the copy that
    `scripts/sync-widget-to-backend.*` writes into `backend/widget_dist/`
    for isolated backend deployments.
    """
    if _WIDGET_DIR_PRIMARY.exists():
        return _WIDGET_DIR_PRIMARY
    return _WIDGET_DIR_FALLBACK


def _resolve(asset_name: str) -> Path:
    """Resolve a request path safely inside the active widget directory."""
    base = _active_widget_dir()
    target = (base / asset_name).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid path")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"asset not found: {asset_name}")
    return target


def _cors(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    # Revalidate on every fetch so widget updates propagate immediately.
    # `no-cache` (NOT `no-store`) still lets the browser keep the bundle
    # locally but forces a conditional GET (ETag/Last-Modified) on reload,
    # which is cheap and avoids stale-widget confusion during iteration.
    resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


@router.get("/boerdi-widget.js")
async def widget_js():
    """Primary entry point for embedders. Returns the main widget bundle."""
    if not _active_widget_dir().exists():
        raise HTTPException(
            status_code=503,
            detail=(
                "Widget bundle not built yet. Run "
                "`cd frontend && npm run build:widget` first."
            ),
        )
    target = _resolve("main.js")
    resp = FileResponse(target, media_type="application/javascript")
    return _cors(resp)


# Konkrete HTML-Demo-Routen MÜSSEN vor der ``/{asset_name}``-Catch-All
# stehen, sonst fängt FastAPI z.B. "/widget/inline" als asset_name ab
# und versucht, eine Datei "inline" im widget_dist auszuliefern (404).
@router.get("/", response_class=HTMLResponse)
async def widget_demo():
    """Tiny HTML demo page so you can preview the widget locally."""
    return HTMLResponse(_DEMO_HTML)


@router.get("/inline", response_class=HTMLResponse)
async def widget_demo_inline():
    """Embed-Modus-Demo: Chat ohne Kacheln und ohne Canvas.

    Zeigt, wie das Widget auf einer Themenseite oder einem fremden CMS
    minimal auftritt. Treffer werden als dezente Inline-Markdown-Links
    in der Bot-Antwort gerendert; das Canvas öffnet sich nicht.
    Quick-Replies und KI-Material-Erstellung bleiben aktiv.
    """
    return HTMLResponse(_DEMO_INLINE_HTML)


@router.get("/{asset_name}")
async def widget_asset(asset_name: str):
    """Serve any auxiliary file (chunks, css) emitted by the build."""
    target = _resolve(asset_name)
    media = "application/javascript" if asset_name.endswith(".js") else None
    if asset_name.endswith(".css"):
        media = "text/css"
    if asset_name.endswith(".map"):
        media = "application/json"
    resp = FileResponse(target, media_type=media)
    return _cors(resp)


_DEMO_HTML = """<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BOERDi Widget — Demo & Integrations-Guide</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      max-width: 880px; margin: 40px auto; padding: 0 20px; color: #333;
      line-height: 1.6;
    }
    h1 { color: #1c4587; }
    h2 { color: #1c4587; margin-top: 32px; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; }
    h3 { color: #334155; margin-top: 20px; font-size: 1.05em; }
    code { background: #f3f4f6; padding: 2px 6px; border-radius: 4px; font-size: 13px; }
    pre  { background: #1f2937; color: #e5e7eb; padding: 16px; border-radius: 8px; overflow-x: auto; font-size: 13px; }
    .hero { background: #f9fafb; padding: 24px; border-radius: 12px; border: 1px solid #e5e7eb; }
    table { width: 100%; border-collapse: collapse; margin: 8px 0 16px; font-size: 13px; }
    th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #e5e7eb; vertical-align: top; }
    th { background: #f9fafb; }
    .tag { display: inline-block; background: #e0e7ff; color: #3730a3; padding: 1px 8px; border-radius: 10px; font-size: 11px; margin-right: 4px; }
    .tag-note { background: #fef3c7; color: #92400e; }
    .note { background: #fffbeb; border-left: 3px solid #f59e0b; padding: 12px 16px; border-radius: 4px; margin: 12px 0; font-size: 13px; }
  </style>
</head>
<body>
  <h1><img src="/api/static/boerdi.svg" alt="" style="width:36px;height:36px;vertical-align:-8px;margin-right:8px;"/>BOERDi Widget — Demo & Integrations-Guide</h1>
  <div class="hero">
    <p>Klicke unten rechts auf die Eule, um den Chatbot zu öffnen.</p>
    <p>Diese Seite demonstriert alle Integrations-Varianten. Das Widget läuft hier mit
       <code>auto-context="true"</code> — URL, Titel und Themenseiten-Slug werden automatisch erkannt.</p>
  </div>

  <div class="note" style="background:#ecfdf5;border-left-color:#10b981;">
    <strong>Was ist neu?</strong>
    <ul style="margin:6px 0 0 0;">
      <li><strong>Trusted Domains</strong> für den Lotsen-Modus liegen jetzt im Backend
        (<code>guide-mode.yaml</code> oder Env <code>GUIDE_TRUSTED_DOMAINS</code>) — HTML-
        Attribut <code>trusted-domains</code> ist nur noch optional und additiv. Stored-XSS
        auf der Host-Seite kann die Allow-Liste nicht mehr aushebeln.
        <a href="#props">→ siehe Properties</a></li>
      <li><strong>Lotsen-Button getrennt vom Modus</strong>: neue Attribute
        <code>show-guide-button="false"</code> versteckt den 🧭-Toggle und
        <code>guide-mode-default="true|false|auto"</code> setzt den Default unabhängig
        davon. Damit kann der Host eigene Lotsen-UI bauen oder den Modus stillschweigend
        aktivieren.</li>
      <li><strong>Public JS-API</strong>: <code>el.openChatbot()</code>,
        <code>el.closeChatbot()</code>, <code>el.toggleChatbot()</code>,
        <code>el.isChatbotOpen()</code> — kein Shadow-DOM-Klick-Hack mehr nötig.
        <code>initial-state</code>-Attribut ist jetzt reaktiv (via Angular
        <code>ngOnChanges</code>).</li>
      <li><strong>Akzentfarbe per CSS-Variable</strong> überschreibbar:
        <code>boerdi-chat { --boerdi-primary: red; }</code> — kein doppeltes Inline-Styling
        am Kind-Element mehr.</li>
      <li><strong>Material-Symbols-Icons</strong>: Header-, Chat- und Canvas-Icons sind
        jetzt Inline-SVGs aus Google Material Symbols (Outlined). Erbt Farbe (currentColor)
        und Größe (1em) vom umgebenden Button automatisch.</li>
    </ul>
  </div>

  <h2>Schnellstart (Minimal-Embed)</h2>
  <pre>&lt;script src="http://localhost:8000/widget/boerdi-widget.js" defer&gt;&lt;/script&gt;
&lt;boerdi-chat api-url="http://localhost:8000"&gt;&lt;/boerdi-chat&gt;</pre>
  <p>Mehr braucht es nicht für den Standard-Fall. <code>auto-context="true"</code> ist Default,
     d.h. URL-Pfad, <code>?node=</code>, <code>?collection=</code>, <code>?q=</code>, WLO-Slugs
     (<code>/themenseite/…</code>, <code>/fachportal/…</code>), edu-sharing-Render-URLs
     (<code>/components/render/&lt;uuid&gt;</code>) und der Seitentitel werden erkannt und
     an das Backend übergeben.</p>

  <h2>Integrations-Szenarien</h2>

  <h3>1. Themenseite (wirlernenonline.de/themenseite/optik)</h3>
  <pre>&lt;boerdi-chat
  api-url="https://api.wlo.de"
  position="bottom-right"&gt;
&lt;/boerdi-chat&gt;</pre>
  <p>Auto-Context erkennt den Slug <code>optik</code>, das Backend ruft
     <code>search_wlo_topic_pages</code> + <code>get_node_details</code> via MCP auf und
     cacht Titel/Beschreibung/Fächer/Bildungsstufen in der Session (TTL 30 Min).
     Der Bot kann anschließend „Worum geht es auf dieser Seite?" direkt beantworten.</p>

  <h3>2. edu-sharing Content-Render (.../components/render/&lt;uuid&gt;)</h3>
  <pre>&lt;boerdi-chat
  api-url="https://api.wlo.de"
  position="bottom-right"&gt;
&lt;/boerdi-chat&gt;</pre>
  <p>Der <code>node_id</code> wird aus dem URL-Pfad extrahiert und automatisch via MCP aufgelöst.</p>

  <h3>3. Expliziter Kontext-Override (z.B. auf eigener Seite mit bekannten Meta-Daten)</h3>
  <pre>&lt;boerdi-chat
  api-url="https://api.wlo.de"
  page-context='{"node_id":"a1b2c3d4-1234-5678-90ab-cdef01234567"}'&gt;
&lt;/boerdi-chat&gt;</pre>
  <p>Manuell gesetzte <code>page-context</code>-Keys überschreiben Auto-Detection.
     Unterstützte Keys:
     <code>node_id</code>, <code>collection_id</code>, <code>topic_page_slug</code>,
     <code>subject_slug</code>, <code>search_query</code>, <code>page_type</code>,
     <code>document_title</code>.</p>

  <h3>4. Sammlungsseite (.../sammlung/&lt;id&gt;)</h3>
  <pre>&lt;boerdi-chat
  api-url="https://api.wlo.de"
  position="bottom-right"
  initial-state="expanded"&gt;
&lt;/boerdi-chat&gt;</pre>
  <p><code>initial-state="expanded"</code> öffnet das Widget direkt. Nützlich, wenn der
     User über eine Link-Kampagne kommt und sofort interagieren soll.</p>

  <h3>5. Auto-Context deaktivieren (statischer Kontext)</h3>
  <pre>&lt;boerdi-chat
  api-url="https://api.wlo.de"
  auto-context="false"
  page-context='{"page_type":"landingpage","campaign":"digital-pakt-2026"}'&gt;
&lt;/boerdi-chat&gt;</pre>

  <h3>6. Produktiv-Embedding ohne Debug- und Sprach-Buttons</h3>
  <pre>&lt;boerdi-chat
  api-url="https://api.wlo.de"
  show-debug-button="false"
  show-language-buttons="false"&gt;
&lt;/boerdi-chat&gt;</pre>
  <p>Auf Endkunden-Seiten meist sinnvoll: <code>show-debug-button="false"</code> blendet
     den 🔍-Toggle aus (das Debug-Panel wäre für Endnutzer ohnehin verwirrend),
     <code>show-language-buttons="false"</code> entfernt 🔊 (TTS) und 🎤 (Mic). Letzteres
     vermeidet zugleich den Browser-Mikrofon-Berechtigungs-Prompt beim ersten Laden.</p>

  <h3>7. Cross-Domain-Sessions (mehrere Subdomains / externes Repo)</h3>
  <pre>&lt;boerdi-chat
  api-url="https://api.wlo.de"
  session-cookie-domain=".wirlernenonline.de"&gt;
&lt;/boerdi-chat&gt;</pre>
  <p>Wenn das Widget auf mehreren Subdomains derselben Top-Level-Domain läuft
     (z.B. <code>suche.wlo.de</code>, <code>wp-test.wlo.de</code>) und die Konversation über
     alle Subdomains hinweg fortgesetzt werden soll:</p>
  <ul>
    <li><code>session-cookie-domain</code> setzt parallel zu localStorage ein Cookie mit
        dieser Domain — Browser teilt es automatisch zwischen allen Subdomains.</li>
    <li><strong>Trusted Domains für Cross-TLD-Handoff</strong>: die Allow-Liste der
        Domains, an die das Widget <code>?bsid=&lt;session-id&gt;</code> bei Link-Klick anhängen
        darf, wird <strong>backend-seitig</strong> in
        <code>chatbots/wlo/v1/01-base/guide-mode.yaml</code> gepflegt (Feld
        <code>trusted_domains</code>) oder per Env <code>GUIDE_TRUSTED_DOMAINS</code>
        überschrieben. Das Frontend lädt diese Liste beim Start einmalig
        (<code>GET /api/config/guide-mode</code>) und merged optional ein zusätzliches
        HTML-Attribut <code>trusted-domains</code> hinzu (additiv — kann nichts entfernen).
        <span class="tag tag-note">Vertrauensanker</span> Eine Stored-XSS auf der
        Host-Seite kann die Backend-Liste also nicht aushebeln.</li>
  </ul>
  <p>Backend ist domain-agnostisch — gleiche <code>session_id</code> liefert aus jeder
     Origin denselben Verlauf, dieselben Slots, dasselbe Memory.
     <span class="tag tag-note">Default off</span> Ohne Cookie-Domain und ohne Backend-
     Trusted-Domains-Eintrag bleibt das Verhalten wie bisher (rein localStorage,
     origin-isoliert).</p>

  <h3>8. Webseiten-Lotsen-Modus (auf WLO-Domains)</h3>
  <pre>&lt;!-- Default-Variante: Allow-Liste komplett aus dem Backend --&gt;
&lt;boerdi-chat
  api-url="https://api.wlo.de"
  session-cookie-domain=".wirlernenonline.de"&gt;
&lt;/boerdi-chat&gt;

&lt;!-- Variante: zusätzliche Domain rein per HTML ergänzen (additiv, kann nichts entfernen) --&gt;
&lt;boerdi-chat
  api-url="https://api.wlo.de"
  trusted-domains="wp-staging.wirlernenonline.de"
  session-cookie-domain=".wirlernenonline.de"&gt;
&lt;/boerdi-chat&gt;

&lt;!-- Variante: Lotsen-Button verstecken, Modus per Default trotzdem aktiv --&gt;
&lt;boerdi-chat
  api-url="https://api.wlo.de"
  show-guide-button="false"
  guide-mode-default="true"&gt;
&lt;/boerdi-chat&gt;</pre>
  <p>Wenn das Widget auf einer der konfigurierten WLO-Domains läuft (Backend-Liste in
     <code>chatbots/wlo/v1/01-base/guide-mode.yaml</code>), erscheint im Chat-Header
     ein <strong>🧭-Toggle</strong>. Aktiv schaltet er den Lotsen-Modus an: der Bot
     hängt unter seiner Antwort einen <strong>Inline-Link</strong> zur passenden
     WLO-/Repo-Seite an. Klick navigiert <strong>im selben Browser-Tab</strong> statt
     einen neuen zu öffnen.</p>
  <ul>
    <li><strong>Allow-Liste (Vertrauensanker)</strong>: Backend-YAML
        (<code>trusted_domains</code>) und/oder Env <code>GUIDE_TRUSTED_DOMAINS</code>.
        HTML-Attribut <code>trusted-domains</code> ist optional und wirkt nur additiv.
        Wildcards <code>*.example.com</code> matchen alle Subdomains.</li>
    <li><strong>Sichtbarkeit des Toggles:</strong> auf Allow-Liste-Hosts <strong>und</strong>
        wenn <code>show-guide-button</code> nicht auf <code>false</code> steht. Auf
        Drittseiten ist der Modus implicit aus (keine Navigationsziele).</li>
    <li><strong>Default-Aktivierung:</strong>
        <code>guide-mode-default</code> Attribut → <code>true</code>/<code>false</code>/<code>auto</code>.
        <code>auto</code> (Default) folgt der Priorität URL-Param <code>?bgm</code> →
        <code>localStorage["boerdi.guide_mode"]</code> → Backend-Default aus
        <code>guide-mode.yaml</code>. Späteres User-Toggle wird in localStorage
        persistiert.</li>
    <li><strong>Cross-Domain-Brücke:</strong> klickt der User auf eine Card-URL einer
        anderen Allow-Liste-Origin, hängt das Widget automatisch <code>?bsid=&lt;sid&gt;</code>
        und <code>?bgm=&lt;0|1&gt;</code> an — Session und Lotsen-State werden mitgeführt.</li>
    <li><strong>Inline statt Pillen:</strong> Lotsen-Hinweise werden vom Backend in
        jedem Embed-Modus als Markdown-Link am Antwort-Ende eingebaut — kein zusätzlicher
        Pillen-Button im Chat, kein „Bring mich hin"-Card-Button.</li>
    <li><strong>Toggle aus → keine Lotsen-Links:</strong> Backend filtert alle
        magic-prefix-Quick-Replies serverseitig, das Postprocess erzeugt keinen
        Inline-Markdown-Link.</li>
  </ul>
  <p><strong>Wartung:</strong> Allow-Liste (<code>trusted_domains</code>), Default-State
     (<code>guide_mode_default</code>) und Per-Turn-Limit stehen in
     <code>chatbots/wlo/v1/01-base/guide-mode.yaml</code>. Env-Var
     <code>GUIDE_TRUSTED_DOMAINS</code> (komma-/whitespace-getrennt) überschreibt das
     YAML-Feld komplett. Endpoint <code>GET /api/config/guide-mode</code> liefert die
     aktiven Werte ans Frontend (gecached). Die Frage→URL-Mapping-Tabelle für die
     LLM-unabhängigen Quick-Reply-Trigger pflegst du in
     <code>backend/app/services/guide_qr_injector.py</code> (List <code>_RULES</code> +
     Dict <code>_RAG_AREA_URLS</code>).</p>

  <h2 id="props">Properties (vollständige Liste)</h2>
  <table>
    <tr><th>HTML-Attribut</th><th>Typ</th><th>Default</th><th>Beschreibung</th></tr>
    <tr><td><code>api-url</code></td><td>string</td><td><code>""</code></td>
        <td>Backend-Basis-URL (z.B. <code>https://api.wlo.de</code>). Ohne Wert nutzt das Widget denselben Host, von dem das JS geladen wurde.</td></tr>
    <tr><td><code>page-context</code></td><td>JSON string</td><td><code>{}</code></td>
        <td>Manuelle Kontext-Keys (siehe Liste oben). Wird mit Auto-Context gemerged — manuelle Keys gewinnen.</td></tr>
    <tr><td><code>auto-context</code></td><td>boolean</td><td><code>true</code></td>
        <td>URL-Regex extrahiert <code>node_id</code>, Slug, Query-Param usw. automatisch. <code>document.title</code> geht als Fallback mit. Liest zusätzlich Opt-in-Meta-Tags (<code>&lt;meta name="boerdi:node-id"&gt;</code>) und extrahiert sichtbaren Seiteninhalt als <code>page_text</code> für Off-Platform-Embeddings.</td></tr>
    <tr><td><code>position</code></td><td>enum</td><td><code>bottom-right</code></td>
        <td><code>bottom-right</code> | <code>bottom-left</code> | <code>top-right</code> | <code>top-left</code></td></tr>
    <tr><td><code>initial-state</code></td><td>enum</td><td><code>collapsed</code></td>
        <td><code>collapsed</code> (FAB) | <code>expanded</code> (direkt offen)</td></tr>
    <tr><td><code>primary-color</code></td><td>CSS color</td><td><code>""</code> (→ CSS-Default <code>#1c4587</code>)</td>
        <td>Akzentfarbe für FAB, Header und Buttons. Wenn gesetzt, wird sie als Inline-Style auf das Host-Element gelegt und gewinnt damit gegen CSS-Regeln. <br>Alternativ leer lassen und per CSS-Variable im Host-Stylesheet überschreiben: <code>boerdi-chat { --boerdi-primary: red; }</code>.</td></tr>
    <tr><td><code>persist-session</code></td><td>boolean</td><td><code>true</code></td>
        <td>Session-ID in localStorage — Konversation bleibt über Seitenaufrufe erhalten.</td></tr>
    <tr><td><code>session-key</code></td><td>string</td><td><code>boerdi_session_id</code></td>
        <td>localStorage-Key + Cookie-Name, falls mehrere Widgets auf derselben Domain laufen.</td></tr>
    <tr><td><code>session-cookie-domain</code></td><td>string</td><td><code>""</code></td>
        <td>Setzt parallel zu localStorage ein Cookie mit dieser Domain — Browser teilt das Cookie automatisch über alle Subdomains. Beispiel: <code>.wirlernenonline.de</code> verbindet <code>suche.wlo.de</code> + <code>wp-test.wlo.de</code>. Leer = kein Cookie (origin-isoliert wie bisher).</td></tr>
    <tr><td><code>session-cookie-max-age</code></td><td>integer</td><td><code>2592000</code></td>
        <td>Cookie-Lifetime in Sekunden (Default: 30 Tage). Greift nur wenn <code>session-cookie-domain</code> gesetzt ist.</td></tr>
    <tr><td><code>trusted-domains</code></td><td>string</td><td><code>""</code></td>
        <td><strong>Zusätzlich</strong> zur Backend-Allow-Liste (siehe <code>trusted_domains</code> in <code>guide-mode.yaml</code> bzw. <code>GUIDE_TRUSTED_DOMAINS</code> Env-Var) per HTML eintragbare Hostnames für Cross-TLD-Session/Toggle-Handoff. Beim Klick auf einen Link zu einer dieser Domains hängt das Widget <code>?bsid=&lt;session-id&gt;&amp;bgm=&lt;0|1&gt;</code> an. <br>Backend-Liste hat Vorrang als <strong>Vertrauensanker</strong>; das HTML-Attribut wirkt nur <em>additiv</em> — eine Stored-XSS auf der Host-Seite kann die Backend-Allow-Liste nicht aushebeln. Subdomain-Match ist automatisch (<code>openeduhub.net</code> matcht <code>*.openeduhub.net</code>). <code>https://</code>/<code>http://</code>-Präfix und Trailing-Slashes werden toleriert.</td></tr>
    <tr><td><code>greeting</code></td><td>string</td><td><code>""</code></td>
        <td>Eigener Begrüßungstext (überschreibt den Persona-Default).</td></tr>
    <tr><td><code>show-debug-button</code></td><td>boolean</td><td><code>true</code></td>
        <td>🔍 Debug-Toggle im Header anzeigen. <code>false</code> = Button ausgeblendet (für Produktiv-Embeddings sinnvoll, da Endnutzer das Debug-Panel meist nicht brauchen).</td></tr>
    <tr><td><code>show-language-buttons</code></td><td>boolean</td><td><code>true</code></td>
        <td>🔊 Text-to-Speech und 🎤 Mic-Aufnahme anzeigen. <code>false</code> = beide Buttons aus, kein Sprach-Feature. <span class="tag tag-note">Tipp</span> verhindert auch den Browser-Mikrofon-Permission-Prompt beim ersten Laden.</td></tr>
    <tr><td><code>canvas-enabled</code></td><td>boolean</td><td><code>true</code></td>
        <td>Canvas-Pane (Material-Erstellung, Lernpfad-Anzeige) ein/aus. <code>false</code> rendert Material/Lernpfad direkt im Chat-Verlauf — kein Canvas-Aufgehen.</td></tr>
    <tr><td><code>ai-content-enabled</code></td><td>boolean</td><td><code>true</code></td>
        <td>KI-generierte Inhalte (Arbeitsblatt, Quiz, Lernpfad, Remix) ein/aus. <code>false</code> lehnt Erstell-Anfragen mit der Alt-Antwort aus <code>widget-modes.yaml</code> freundlich ab.</td></tr>
    <tr><td><code>cards-enabled</code></td><td>boolean</td><td><code>true</code></td>
        <td>Kachel-Anzeige ein/aus. <code>false</code> rendert Treffer als dezente Inline-Markdown-Links im Bot-Text (max. N aus <code>widget-modes.yaml</code> → <code>cards_inline_link_limit</code>). Titel wird im Frontend gekürzt; URL ist <code>guide_url</code> (Lotsen-Modus an) oder <code>wlo_url</code> (Direktlink).</td></tr>
    <tr><td><code>quick-replies-enabled</code></td><td>boolean</td><td><code>true</code></td>
        <td>Gesprächsvorschläge-Pillen unter Bot-Antworten. <code>false</code> blendet alle QR-Buttons komplett aus — keine Konversations-Vorschläge mehr. <br>Lotsen-Hinweise sind davon nicht betroffen: sie werden <em>in jedem Modus</em> als Inline-Link im Bot-Text gerendert, nicht als Pille.</td></tr>
    <tr><td><code>show-guide-button</code></td><td>boolean</td><td><code>true</code></td>
        <td>🧭-Lotsen-Toggle-Button im Header. <code>false</code> blendet den Button aus — der Lotsen-Modus selbst bleibt nutzbar (per <code>guide-mode-default</code> oder Backend-Default + Cross-TLD-<code>?bgm=…</code>-Handoff). Nützlich, wenn der Host das Lotsen-Toggling per eigener UI-Komponente steuert.</td></tr>
    <tr><td><code>guide-mode-default</code></td><td>tristate</td><td><code>auto</code></td>
        <td>Initial-State des Lotsen-Modus. <code>true</code>/<code>false</code> = explizit ein/aus; <code>auto</code> = bisheriges Verhalten (URL <code>?bgm</code> → localStorage → Backend-Default aus <code>guide-mode.yaml</code>). Wirkt nur beim allerersten Boot; späteres User-Toggle hat Vorrang.</td></tr>
  </table>

  <h3>Public JavaScript-API (Chat-Bubble von außen steuern)</h3>
  <p>Das <code>&lt;boerdi-chat&gt;</code>-Element exponiert vier Methoden, mit denen die einbettende Seite das Panel öffnen/schließen kann — ohne Shadow-DOM-Tricks:</p>
  <pre>const el = document.querySelector('boerdi-chat');
el.openChatbot();    // Panel öffnen
el.closeChatbot();   // Panel schließen (FAB sichtbar)
el.toggleChatbot();  // Toggle
el.isChatbotOpen();  // → boolean</pre>
  <p>Alternativ — und für Angular-Templates praktisch — über reaktive Attribut-Änderungen:</p>
  <pre>el.setAttribute('initial-state', 'expanded');   // entspricht openChatbot()
el.setAttribute('initial-state', 'collapsed');  // entspricht closeChatbot()</pre>
  <p>In Angular per <code>[attr.initial-state]="state()"</code> direkt im Template binden — das Widget reagiert via <code>ngOnChanges</code> auf jede Änderung.</p>

  <h3>Akzentfarbe per CSS-Variable</h3>
  <p>Statt das <code>primary-color</code>-Attribut zu setzen, kann die Farbe auch per CSS-Variable im Host-Stylesheet überschrieben werden:</p>
  <pre>boerdi-chat {
  --boerdi-primary: red;
}</pre>
  <p>Das funktioniert sauber, solange <code>primary-color</code> NICHT zusätzlich gesetzt ist. Mit Attribut hat das Attribut Vorrang (Inline-Style schlägt CSS).</p>

  <h3>Embed-Modus-Varianten (kompakte Auftritte)</h3>
  <p>Die vier <code>*-enabled</code>-Properties lassen die einbettende Seite das Widget
     <strong>feature-by-feature minimaler</strong> auftreten. Defaults bleiben <code>true</code>,
     Bestandsintegrationen ändern sich nicht. Schwellen (Anzahl der Inline-Links, Titel-Kürzung,
     Alt-Antwort-Text) liegen in <code>chatbots/wlo/v1/01-base/widget-modes.yaml</code> und
     sind über das Studio editierbar.</p>

  <p><strong>Schlanke Themenseite</strong> — keine Kachel-Komponente, kein Canvas:</p>
  <pre>&lt;boerdi-chat
  api-url="https://api.wlo.de"
  cards-enabled="false"
  canvas-enabled="false"&gt;
&lt;/boerdi-chat&gt;</pre>

  <p><strong>Reduziert</strong> — Kacheln ja, KI-Erstellung nein, keine Pillen:</p>
  <pre>&lt;boerdi-chat
  api-url="https://api.wlo.de"
  ai-content-enabled="false"
  quick-replies-enabled="false"&gt;
&lt;/boerdi-chat&gt;</pre>

  <p><strong>Minimal-Bubble</strong> — nur Text + Inline-Links:</p>
  <pre>&lt;boerdi-chat
  api-url="https://api.wlo.de"
  cards-enabled="false"
  canvas-enabled="false"
  ai-content-enabled="false"
  quick-replies-enabled="false"&gt;
&lt;/boerdi-chat&gt;</pre>

  <div class="note">
    <strong>Lotsen-Modus (🧭) — Steuerung im Überblick:</strong>
    <ul>
      <li><strong>Allow-Liste der vertrauenswürdigen Domains</strong>: server-seitig in
        <code>chatbots/wlo/v1/01-base/guide-mode.yaml</code> (Feld <code>trusted_domains</code>),
        überschreibbar via Env <code>GUIDE_TRUSTED_DOMAINS</code>. Frontend ergänzt diese
        Backend-Liste optional via HTML-Attribut <code>trusted-domains</code> (additiv,
        kann nichts entfernen).</li>
      <li><strong>Default-Aktivierung</strong>: <code>guide_mode_default</code> in der
        YAML legt den initialen Toggle-State fest; per Embed via Attribut
        <code>guide-mode-default="true|false|auto"</code> überschreibbar.</li>
      <li><strong>Sichtbarkeit des Toggle-Buttons</strong>: per Attribut
        <code>show-guide-button="true|false"</code> einzeln steuerbar — Button ausblenden,
        Modus trotzdem aktivieren ist möglich (z.B. wenn der Host eigene Lotsen-UI bringt).</li>
      <li><strong>Cross-Domain-Persistenz</strong>: damit der Toggle-State über
        Page-Loads/TLDs überlebt, MUSS die Backend-Allow-Liste die Ziel-Domains kennen;
        für Subdomains derselben TLD zusätzlich <code>session-cookie-domain</code> setzen.</li>
    </ul>
  </div>

  <h2>Was der Chatbot kann</h2>
  <table>
    <tr><th>Fähigkeit</th><th>Beispiel-Nutzer-Anfrage</th></tr>
    <tr><td><span class="tag">Suche</span> Einzel-Materialien</td>
        <td>„Zeig mir Videos zur Bruchrechnung"</td></tr>
    <tr><td><span class="tag">Suche</span> Sammlungen</td>
        <td>„Welche Sammlungen gibt es zu Geometrie?"</td></tr>
    <tr><td><span class="tag">Suche</span> Themenseiten</td>
        <td>„Wo finde ich eine Übersicht zu Klimawandel?"</td></tr>
    <tr><td><span class="tag">Info</span> Plattform/Projekt/Statistik</td>
        <td>„Wie viele OER-Materialien hat WLO?"</td></tr>
    <tr><td><span class="tag">Canvas-Create</span> didaktisch</td>
        <td>„Erstell mir ein Arbeitsblatt zur Photosynthese Klasse 6"</td></tr>
    <tr><td><span class="tag">Canvas-Create</span> analytisch</td>
        <td>„Ich brauche ein Factsheet zu Bildungsgerechtigkeit"</td></tr>
    <tr><td><span class="tag">Canvas-Create</span> Lernpfad</td>
        <td>„Bau mir einen Lernpfad aus der Sammlung"</td></tr>
    <tr><td><span class="tag">Canvas-Edit</span></td>
        <td>„Mach es einfacher", „Füge Lösungen hinzu"</td></tr>
    <tr><td><span class="tag">Feedback</span></td>
        <td>„Das war nicht hilfreich" → Acknowledgment + Routing-Angebot</td></tr>
    <tr><td><span class="tag">Lotsen-Modus</span> Webseiten-Navigation</td>
        <td>„Wie kann ich mitmachen?" → Inline-Link „Mitmachen-Seite" im Bot-Text. Klick navigiert im gleichen Tab zur WLO-Seite.</td></tr>
  </table>
  <div class="note">
    <strong>Canvas-Arbeitsfläche:</strong> Ab Breakpoint &gt;1200 px öffnet das Widget eine
    zweite Spalte rechts neben dem Chat (Canvas-Pane). Dort erscheinen Markdown-Dokumente
    (Arbeitsblatt, Quiz, Factsheet, …) mit Druck/Download, sowie die Material-Kachel-Grid für
    Such-Ergebnisse. Mobile: Tab-Switcher im Header.
  </div>

  <h2>Personas, Intents, Patterns</h2>
  <p>Das Backend klassifiziert jeden Turn auf 9 Personas (Lehrkraft, Schüler:in, Eltern,
     Anonym, Verwaltung, Politik, Berater, Presse, Redaktion) und 14 Intents
     (Suche/Canvas-Create/Canvas-Edit/Feedback/…). 27 Patterns entscheiden, wie geantwortet
     wird; eine YAML-Routing-Rules-Engine kann Patterns vor und nach der Selektion
     überschreiben — alles konfigurierbar im BadBoerdi Studio (im Default-Setup auf
     <code>:3001</code> bzw. <code>studio.&lt;ip&gt;.nip.io</code>).</p>

  <div class="note" style="background:#eef2ff;border-left-color:#6366f1;">
    <strong>Andere Variante zum Vergleich:</strong>
    <a href="/widget/inline">/widget/inline</a> — Kompakter Embed-Modus
    ohne Kacheln und ohne Canvas. Treffer werden als dezente Inline-Links
    in der Bot-Antwort gerendert. Empfohlen für Themenseiten,
    eingebettete Hilfe-Bubbles und CMS-Integrationen mit eigenem Layout.
  </div>

  <!-- Live-Demo: Same-Origin (kein hardcoded Host) — funktioniert auf localhost,
       nip.io, Custom-Domains und überall sonst, wo dieses HTML serviert wird. -->
  <script src="/widget/boerdi-widget.js" defer></script>
  <boerdi-chat
    position="bottom-right"
    primary-color="#1c4587">
  </boerdi-chat>
</body>
</html>
"""


_DEMO_INLINE_HTML = """<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BOERDi Widget — Inline-Modus (keine Kacheln, kein Canvas)</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      max-width: 820px; margin: 40px auto; padding: 0 20px; color: #1f2937;
      line-height: 1.65;
    }
    h1 { color: #1c4587; margin-bottom: 4px; }
    h2 { color: #1c4587; margin-top: 32px; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; }
    .lead { color: #475569; font-size: 1.05em; margin: 0 0 28px; }
    .hero {
      background: linear-gradient(180deg, #f8fafc 0%, #eff6ff 100%);
      padding: 24px 28px; border-radius: 12px; border: 1px solid #dbeafe;
      margin-bottom: 24px;
    }
    .hero p { margin: 0; }
    .hero p + p { margin-top: 8px; }
    code { background: #f1f5f9; padding: 2px 7px; border-radius: 4px; font-size: 13px; color: #0f172a; }
    pre  { background: #1e293b; color: #e2e8f0; padding: 16px 18px; border-radius: 8px; overflow-x: auto; font-size: 13px; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 16px 0 24px; }
    .panel { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 16px 18px; }
    .panel h3 { margin: 0 0 8px; color: #334155; font-size: 1rem; }
    .panel p { margin: 0; color: #475569; font-size: 0.93em; }
    .pill {
      display: inline-block; background: #ddd6fe; color: #5b21b6;
      padding: 1px 9px; border-radius: 10px; font-size: 11px; margin-right: 4px;
      font-weight: 600;
    }
    .pill-off { background: #fee2e2; color: #991b1b; }
    .pill-on  { background: #dcfce7; color: #166534; }
    .swap-link {
      display: inline-block; margin-top: 12px;
      color: #1c4587; text-decoration: underline; text-decoration-thickness: 1px;
    }
    .swap-link:hover { text-decoration-thickness: 2px; }
    ul.try-prompts { background: #f9fafb; padding: 14px 18px 14px 36px; border-radius: 8px; border-left: 3px solid #1c4587; }
    ul.try-prompts li { margin-bottom: 6px; }
  </style>
</head>
<body>
  <h1><img src="/api/static/boerdi.svg" alt="" style="width:32px;height:32px;vertical-align:-7px;margin-right:8px;"/>Inline-Link-Modus</h1>
  <p class="lead">
    Diese Demo zeigt das Widget mit deaktivierten Kacheln und deaktiviertem Canvas — der
    Anwendungsfall für eine Themenseite, ein WordPress-Theme oder ein fremdes CMS, das
    selbst Layout und Inhalts-Komponenten mitbringt.
  </p>

  <div class="hero">
    <p>
      <span class="pill pill-off">cards-enabled="false"</span>
      <span class="pill pill-off">canvas-enabled="false"</span>
      <span class="pill pill-off">show-language-buttons="false"</span>
      <span class="pill pill-off">show-debug-button="false"</span>
      <span class="pill pill-off">show-guide-button="false"</span>
      <span class="pill pill-on">guide-mode-default="true"</span>
      <span class="pill pill-on">quick-replies-enabled="true"</span>
      <span class="pill pill-on">ai-content-enabled="true"</span>
      <span class="pill" style="background:#8b0000;color:#fff">primary-color="#8b0000"</span>
    </p>
    <p>
      <strong>Was sich gegenüber der Standard-Demo ändert:</strong>
      Treffer-Kacheln entfallen — der Bot listet stattdessen <strong>maximal 3 Inline-Links</strong>
      direkt in der Antwort (Limit aus <code>chatbots/wlo/v1/01-base/widget-modes.yaml</code>).
      Links sind <u>dezent unterstrichen</u> in der Schriftfarbe des Bot-Texts. Material- und
      Lernpfad-Erstellung landen ebenfalls direkt im Chat-Verlauf statt im Canvas.
      Header-Buttons (🔊 TTS, 🎤 Mic, 🔍 Debug, 🧭 Lotsen-Toggle) sind ausgeblendet — der
      Lotsen-Modus läuft trotzdem (per Default an) und liefert Inline-Repo/WLO-Links.
    </p>
    <p>
      <a class="swap-link" href="/widget/">← Zurück zur klassischen Demo (mit Kacheln + Canvas)</a>
    </p>
  </div>

  <h2>Embed-Snippet (Konfiguration dieser Demo)</h2>
  <pre>&lt;script src="/widget/boerdi-widget.js" defer&gt;&lt;/script&gt;
&lt;boerdi-chat
  cards-enabled="false"
  canvas-enabled="false"
  show-language-buttons="false"
  show-debug-button="false"
  show-guide-button="false"
  guide-mode-default="true"
  position="bottom-right"
  primary-color="#8b0000"&gt;
&lt;/boerdi-chat&gt;</pre>
  <p class="form-hint" style="font-size:.85em;color:#475569;margin-top:-8px">
    Im Header ist nur noch der „Neuer Chat"-Button + Schließen-Kreuz sichtbar. Der
    Lotsen-Modus startet trotzdem aktiv — Inline-Links zeigen Repo-/WLO-Ziele statt
    Direktlinks. Wer den Modus user-toggle-bar lassen möchte, lässt
    <code>show-guide-button</code> auf <code>true</code> und
    <code>guide-mode-default</code> auf <code>auto</code>.
  </p>
  <p class="form-hint" style="font-size:.85em;color:#475569;margin-top:-4px">
    Die <code>primary-color="#8b0000"</code> ist hier absichtlich dunkelrot statt
    WLO-Standard-Blau — so siehst du sofort, welche UI-Elemente die Akzentfarbe
    übernehmen: FAB-Bubble, Panel-Header, Send-Button, Mic-Border, Quick-Reply-Pillen
    und der Input-Focus-Ring. Der Bot-Text und die Inline-Treffer-Links bleiben
    bewusst schwarz für Lesbarkeit; das BOERDi-Logo bleibt ebenfalls farb-stabil.
  </p>

  <h3>Minimal-Variante (alle Buttons sichtbar, nur Kacheln/Canvas aus)</h3>
  <pre>&lt;boerdi-chat
  cards-enabled="false"
  canvas-enabled="false"&gt;
&lt;/boerdi-chat&gt;</pre>

  <h3>Chat-Panel von außen öffnen</h3>
  <pre>const el = document.querySelector('boerdi-chat');
el.openChatbot();    // Panel öffnen
el.closeChatbot();   // schließen
el.toggleChatbot();  // Toggle</pre>

  <h2>Probier es aus</h2>
  <p>Öffne den Chatbot unten rechts und stelle eine der folgenden Fragen — du siehst
     dann den Unterschied zur klassischen Variante.</p>
  <ul class="try-prompts">
    <li>„Zeig mir Material zum Thema Photosynthese."</li>
    <li>„Welche Sammlungen gibt es zu Geometrie?"</li>
    <li>„Erstell mir ein Arbeitsblatt zur Photosynthese für Klasse 6."</li>
    <li>„Was ist eine Themenseite?" — Lotsen-Modus liefert hier zusätzlich einen Inline-Link.</li>
  </ul>

  <h2>Worauf solltest du achten?</h2>
  <div class="grid">
    <div class="panel">
      <h3>Treffer</h3>
      <p>Keine Kacheln mit Vorschau-Bild. Stattdessen eine kurze Liste mit
         „- [Titel](URL)"-Einträgen im Bot-Text. Lotsen-Modus an?
         Dann zeigt der Bot die Repo-/WLO-URL; sonst den Direktlink auf den Inhalt.</p>
    </div>
    <div class="panel">
      <h3>Material-Erstellung</h3>
      <p>Fragst du nach einem Arbeitsblatt, klappt das Canvas <em>nicht</em> auf —
         der gesamte Markdown-Inhalt landet stattdessen im Chat-Verlauf.</p>
    </div>
    <div class="panel">
      <h3>Quick-Replies</h3>
      <p>Pillen-Buttons bleiben aktiv — z. B. Themenwahl-Vorschläge nach dem Greeting,
         oder „Andere Klassenstufe"-Folgefragen unter Bot-Antworten.</p>
    </div>
    <div class="panel">
      <h3>Lotsen-Modus</h3>
      <p>Wenn du den Lotsen-Toggle (🧭) aktivierst, werden Lotsen-Hinweise
         <strong>immer als Inline-Link</strong> im Bot-Text gerendert — egal
         in welchem Embed-Modus. Card-Buttons und Quick-Reply-Pillen bleiben
         für ihre eigentliche Rolle (Kachel-Aktionen bzw. Gesprächsvorschläge).</p>
    </div>
  </div>

  <!-- Live-Demo: Same-Origin (kein hardcoded Host) — kompakter Embed-Modus.
       Konfiguration: keine Kacheln, kein Canvas, keine Sprach-/Debug-/Lotsen-
       Buttons im Header — der Lotsen-Modus startet aber per Default aktiv,
       damit die Inline-Treffer als Repo-/WLO-Links erscheinen.
       primary-color absichtlich dunkelrot, damit man die Akzentfarben-
       Kaskade einmal mit einer Nicht-Default-Farbe live sieht — FAB-Bubble,
       Panel-Header, Send-Button, Mic-Border, Quick-Reply-Pillen und der
       Input-Focus-Ring müssen alle denselben Rot-Ton zeigen. -->
  <script src="/widget/boerdi-widget.js" defer></script>
  <boerdi-chat
    cards-enabled="false"
    canvas-enabled="false"
    show-language-buttons="false"
    show-debug-button="false"
    show-guide-button="false"
    guide-mode-default="true"
    position="bottom-right"
    primary-color="#8b0000">
  </boerdi-chat>
</body>
</html>
"""
