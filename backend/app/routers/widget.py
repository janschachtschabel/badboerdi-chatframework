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


@router.get("/", response_class=HTMLResponse)
async def widget_demo():
    """Tiny HTML demo page so you can preview the widget locally."""
    return HTMLResponse(_DEMO_HTML)


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
  <h1>🦉 BOERDi Widget — Demo & Integrations-Guide</h1>
  <div class="hero">
    <p>Klicke unten rechts auf die Eule, um den Chatbot zu öffnen.</p>
    <p>Diese Seite demonstriert alle Integrations-Varianten. Das Widget läuft hier mit
       <code>auto-context="true"</code> — URL, Titel und Themenseiten-Slug werden automatisch erkannt.</p>
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

  <h2>Properties (vollständige Liste)</h2>
  <table>
    <tr><th>HTML-Attribut</th><th>Typ</th><th>Default</th><th>Beschreibung</th></tr>
    <tr><td><code>api-url</code></td><td>string</td><td><code>""</code></td>
        <td>Backend-Basis-URL (z.B. <code>https://api.wlo.de</code>). Ohne Wert nutzt das Widget denselben Host, von dem das JS geladen wurde.</td></tr>
    <tr><td><code>page-context</code></td><td>JSON string</td><td><code>{}</code></td>
        <td>Manuelle Kontext-Keys (siehe Liste oben). Wird mit Auto-Context gemerged — manuelle Keys gewinnen.</td></tr>
    <tr><td><code>auto-context</code></td><td>boolean</td><td><code>true</code></td>
        <td>URL-Regex extrahiert <code>node_id</code>, Slug, Query-Param usw. automatisch. <code>document.title</code> geht als Fallback mit.</td></tr>
    <tr><td><code>position</code></td><td>enum</td><td><code>bottom-right</code></td>
        <td><code>bottom-right</code> | <code>bottom-left</code> | <code>top-right</code> | <code>top-left</code></td></tr>
    <tr><td><code>initial-state</code></td><td>enum</td><td><code>collapsed</code></td>
        <td><code>collapsed</code> (FAB) | <code>expanded</code> (direkt offen)</td></tr>
    <tr><td><code>primary-color</code></td><td>CSS color</td><td><code>#1c4587</code></td>
        <td>Akzentfarbe für FAB, Header und Buttons.</td></tr>
    <tr><td><code>persist-session</code></td><td>boolean</td><td><code>true</code></td>
        <td>Session-ID in localStorage — Konversation bleibt über Seitenaufrufe erhalten.</td></tr>
    <tr><td><code>session-key</code></td><td>string</td><td><code>boerdi_session_id</code></td>
        <td>localStorage-Key, falls mehrere Widgets auf derselben Domain laufen.</td></tr>
    <tr><td><code>greeting</code></td><td>string</td><td><code>""</code></td>
        <td>Eigener Begrüßungstext (überschreibt den Persona-Default).</td></tr>
  </table>

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
     (Suche/Canvas-Create/Canvas-Edit/Feedback/…). 26 Patterns entscheiden, wie geantwortet
     wird — konfigurierbar im <a href="http://localhost:3001">BadBoerdi Studio</a>.</p>

  <script src="/widget/boerdi-widget.js" defer></script>
  <boerdi-chat
    api-url="http://localhost:8000"
    position="bottom-right"
    primary-color="#1c4587">
  </boerdi-chat>
</body>
</html>
"""
