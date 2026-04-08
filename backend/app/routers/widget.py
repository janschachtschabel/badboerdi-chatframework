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
    resp.headers["Cache-Control"] = "public, max-age=300"
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
  <title>BOERDi Widget — Demo</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      max-width: 720px; margin: 40px auto; padding: 0 20px; color: #333;
      line-height: 1.6;
    }
    h1 { color: #1c4587; }
    code { background: #f3f4f6; padding: 2px 6px; border-radius: 4px; font-size: 13px; }
    pre  { background: #1f2937; color: #e5e7eb; padding: 16px; border-radius: 8px; overflow-x: auto; }
    .hero { background: #f9fafb; padding: 24px; border-radius: 12px; border: 1px solid #e5e7eb; }
  </style>
</head>
<body>
  <h1>🦉 BOERDi Widget — Demo</h1>
  <div class="hero">
    <p>Klicke unten rechts auf die Eule, um den Chatbot zu öffnen.</p>
    <p>Diese Seite simuliert eine beliebige Drittseite. Der Chatbot weiß über die
       <code>page-context</code>-Property, dass er auf einer Demo-Seite läuft.</p>
  </div>

  <h2>Einbettung</h2>
  <pre>&lt;script src="/widget/boerdi-widget.js" defer&gt;&lt;/script&gt;
&lt;boerdi-chat
  api-url="http://localhost:8000"
  page-context='{"thema":"demo","seite":"widget-test"}'
  position="bottom-right"
  primary-color="#1c4587"&gt;
&lt;/boerdi-chat&gt;</pre>

  <h2>Properties</h2>
  <ul>
    <li><code>api-url</code> — Backend-Basis-URL (z.B. <code>https://api.wlo.de</code>)</li>
    <li><code>page-context</code> — JSON-String mit Kontext für das Pattern-Matching</li>
    <li><code>position</code> — <code>bottom-right</code> | <code>bottom-left</code> | <code>top-right</code> | <code>top-left</code></li>
    <li><code>initial-state</code> — <code>collapsed</code> | <code>expanded</code></li>
    <li><code>primary-color</code> — Akzentfarbe für Button und Header</li>
    <li><code>persist-session</code> — <code>true</code>/<code>false</code> für localStorage-Session</li>
    <li><code>session-key</code> — Storage-Key für die Session-ID</li>
    <li><code>greeting</code> — Begrüßungstext überschreiben</li>
    <li><code>auto-context</code> — URL/Title automatisch in den Kontext packen</li>
  </ul>

  <script src="/widget/boerdi-widget.js" defer></script>
  <boerdi-chat
    api-url="http://localhost:8000"
    page-context='{"thema":"demo","seite":"widget-test"}'
    position="bottom-right"
    primary-color="#1c4587">
  </boerdi-chat>
</body>
</html>
"""
