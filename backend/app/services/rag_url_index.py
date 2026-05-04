"""Frontmatter-URL-Index für RAG-Quellmaterial.

Jede Quelldatei unter ``backend/knowledge/sources/<dir>/*.md`` trägt im
YAML-Frontmatter ein ``source: "https://..."``-Feld mit der echten URL
des Original-Dokuments. Die SQLite-DB speichert leider nur den Datei-
namen als ``rag_chunks.source`` — die echte URL geht beim Ingest
verloren.

Dieses Modul baut zur Laufzeit ein Lookup-Dict, das ``filename`` (mit
und ohne Verzeichnis-Disambiguierung) auf die echte URL aus dem
Frontmatter abbildet. Genutzt vom Webseiten-Lotsen-Modus
(``guide_qr_injector``), um *präzise* Bring-mich-hin-URLs anzubieten
statt der generischen Domain-Hauptseiten.

Cache-Strategie: einmal pro Prozess geladen, lazy beim ersten Aufruf.
mtime-basierte Invalidierung pro Datei wäre overkill — Quelldateien
ändern sich nur bei einer Re-Ingestion, die ohnehin einen Backend-
Restart impliziert.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Repo-Root → backend/ → knowledge/sources/
_SOURCES_DIR = Path(__file__).resolve().parents[2] / "knowledge" / "sources"

# Lookup: filename (basename) → erste gefundene URL.
# Filenames in den Source-Verzeichnissen sind unique (geprüft 2026-05-03,
# 78 Files, 0 Duplikate); eine zweite Map nach (dir, filename) ist daher
# redundant. Sollten künftig Duplikate auftauchen, wird ``_load`` warnen.
_url_by_filename: dict[str, str] = {}
_loaded: bool = False


_FRONTMATTER_SOURCE_RE = re.compile(
    r'^source:\s*"?([^"\n]+?)"?\s*$',
    re.MULTILINE,
)


def _normalize_url(url: str) -> str:
    """Bereinigt frontmatter ``source:``-Werte zu einer reinen URL.

    Mögliche Formate in der Praxis (aus den existierenden RAG-Quellen):
      - ``https://example.com/page/``                  → unverändert
      - ``https://example.com/ + /unter1/ + /unter2/`` → erste URL
      - ``https://example.com/ (FAQ-Akkordeon, …)``    → Klammer weg
      - ``https://example.com/ (zusammengeführt aus …)`` → Klammer weg

    Erst splitten wir bei ``" + "`` (Sub-Page-Listen), dann entfernen
    wir alles ab dem ersten Whitespace gefolgt von ``(`` (Kommentar
    in Klammern), schließlich Trailing-Punktuationen.
    """
    if not url:
        return ""
    # "url1 + url2" → "url1"
    if " + " in url:
        url = url.split(" + ", 1)[0].strip()
    # "https://x/ (Kommentar)" → "https://x/"
    paren_idx = url.find(" (")
    if paren_idx >= 0:
        url = url[:paren_idx].strip()
    # Whitespace innerhalb einer URL ist immer ein Fehler — alles ab
    # dem ersten Whitespace abschneiden.
    ws_idx = re.search(r"\s", url)
    if ws_idx:
        url = url[:ws_idx.start()]
    # Trailing-Punktuationen
    return url.rstrip(",.;: ")


def _load() -> None:
    global _loaded, _url_by_filename
    if _loaded:
        return
    if not _SOURCES_DIR.exists():
        logger.warning("RAG sources dir not found: %s", _SOURCES_DIR)
        _loaded = True
        return
    duplicates: list[str] = []
    for md_path in _SOURCES_DIR.rglob("*.md"):
        if md_path.name.lower() == "readme.md":
            continue
        try:
            text = md_path.read_text(encoding="utf-8", errors="ignore")
        except OSError as e:
            logger.warning("RAG-URL-Index: cannot read %s — %s", md_path, e)
            continue
        m = _FRONTMATTER_SOURCE_RE.search(text)
        if not m:
            continue
        url = _normalize_url(m.group(1))
        if not url.startswith("http"):
            continue
        existing = _url_by_filename.get(md_path.name)
        if existing and existing != url:
            duplicates.append(md_path.name)
            continue
        _url_by_filename[md_path.name] = url
    if duplicates:
        logger.warning(
            "RAG-URL-Index: %d filename collisions ignored: %s",
            len(duplicates), duplicates[:5],
        )
    logger.info("RAG-URL-Index loaded: %d filenames mapped", len(_url_by_filename))
    _loaded = True


def url_for_chunk_source(source: str | None) -> Optional[str]:
    """Resolve a RAG-chunk's ``source`` field (filename, e.g.
    ``001-startseite.md``) to its original Web-URL extracted from the
    file's YAML-Frontmatter. Returns ``None`` when the file isn't
    indexed (unknown/external source)."""
    if not source or not isinstance(source, str):
        return None
    _load()
    return _url_by_filename.get(source)


def url_for_chunk_sources(sources: list[str] | None) -> Optional[str]:
    """Iterate ``sources`` (Top-K filenames) and return the first
    URL we can resolve. Order matters — caller should pass them
    sorted by relevance."""
    if not sources:
        return None
    _load()
    for s in sources:
        u = _url_by_filename.get(s) if isinstance(s, str) else None
        if u:
            return u
    return None
