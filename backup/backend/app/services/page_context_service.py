"""Page-Context-Service — Resolve current page to structured metadata.

When the widget is embedded on a theme page (or on an edu-sharing render
URL), the frontend passes `page_context` with one or more of:

    - node_id         (edu-sharing uuid, e.g. 'a1b2c3d4-...')
    - collection_id   (same uuid, different semantic)
    - topic_page_slug (wirlernenonline.de/themenseite/<slug>)
    - subject_slug    (wirlernenonline.de/fachportal/<subject>/…)
    - search_query    (active search term on host page)
    - document_title  (fallback signal)

This service turns that opaque blob into a structured `PageMetadata`
dict that the system prompt can present semantically. The result is
cached on `session_state.entities._page_metadata` and TTL-guarded so
the MCP call happens at most once per session (unless the URL changes).

Design decisions:
  - Best-effort: every MCP failure degrades to "unresolved" — the chat
    keeps working, the LLM just sees less context.
  - Page-context is the source of truth for "where is the user?" —
    don't overwrite existing metadata if the node_id is the same.
  - No blocking: callers that can't await (e.g. the classifier prompt
    builder) should just use whatever's cached.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from app.services import mcp_client

logger = logging.getLogger(__name__)

# Cache key lives in session_state["entities"] under this name
_META_KEY = "_page_metadata"
_META_TTL_SECONDS = 60 * 30        # 30 min for successfully resolved pages
_UNRESOLVED_TTL_SECONDS = 60 * 2   # 2 min for unresolved/failed — retry soon


def _current_context_signature(page_context: dict[str, Any]) -> str:
    """Stable hash of the fields we resolve against, to detect URL changes."""
    keys = ("node_id", "collection_id", "topic_page_slug", "subject_slug")
    return "|".join(str(page_context.get(k) or "") for k in keys)


def _cached_is_fresh(
    session_state: dict[str, Any],
    signature: str,
) -> bool:
    cached = (session_state.get("entities") or {}).get(_META_KEY)
    if not isinstance(cached, dict):
        return False
    if cached.get("_signature") != signature:
        return False
    ts = cached.get("_resolved_at") or 0
    # Unresolved entries expire much faster so transient MCP outages don't
    # lock us out of context for half an hour. Successful resolutions keep
    # the long TTL (theme pages rarely change).
    ttl = (
        _UNRESOLVED_TTL_SECONDS if cached.get("unresolved")
        else _META_TTL_SECONDS
    )
    return (time.time() - ts) < ttl


def get_cached(session_state: dict[str, Any]) -> dict[str, Any] | None:
    """Return cached metadata (if any) without triggering a fetch."""
    cached = (session_state.get("entities") or {}).get(_META_KEY)
    if isinstance(cached, dict) and cached.get("title"):
        return cached
    return None


# ────────────────────────────────────────────────────────────────────
# Parsing helpers for MCP responses (they return plain text / JSON-ish
# bodies depending on the tool). We try JSON first, then fall back to
# regex-based extraction of the fields we care about.
# ────────────────────────────────────────────────────────────────────


def _safe_json(text: str) -> dict[str, Any] | list[Any] | None:
    try:
        return json.loads(text)
    except Exception:
        return None


def _extract_node_fields(raw: str) -> dict[str, Any]:
    """Pull title/description/keywords/disciplines/stufen from `get_node_details`.

    Accepts (in order of preference):
      1. The MCP v2+ `outputFormat="json"` shape — flat FormattedNode with
         label-resolved fields (`disciplines`, `educationalContexts`, …).
      2. The legacy edu-sharing JSON shape with `ccm:*` properties
         (kept as a fallback so old MCP servers still work).
      3. The "Key: Value" Markdown block (default `outputFormat="markdown"`).

    Missing fields degrade to empty strings/lists.
    """
    out: dict[str, Any] = {
        "title": "",
        "description": "",
        "keywords": [],
        "disciplines": [],
        "educational_contexts": [],
        "learning_resource_types": [],
        "url": "",
    }
    if not raw:
        return out

    data = _safe_json(raw)
    if isinstance(data, dict):
        # 1. MCP v2+ shape: flat FormattedNode with camelCase keys and label
        #    arrays. We detect it via the presence of `nodeId` AND any of
        #    the camelCase label keys at the top level.
        if data.get("nodeId") and (
            "disciplines" in data
            or "educationalContexts" in data
            or "learningResourceTypes" in data
        ):
            def _str(k: str) -> str:
                v = data.get(k)
                return v if isinstance(v, str) else ""

            def _strlist(k: str) -> list[str]:
                v = data.get(k)
                if isinstance(v, list):
                    return [str(x) for x in v if x]
                if isinstance(v, str) and v:
                    return [v]
                return []

            out["title"] = _str("title")
            out["description"] = _str("description")
            out["keywords"] = _strlist("keywords")
            out["disciplines"] = _strlist("disciplines")
            out["educational_contexts"] = _strlist("educationalContexts")
            out["learning_resource_types"] = _strlist("learningResourceTypes")
            out["url"] = _str("url") or _str("renderUrl")
            if out["title"]:
                return out

        # 2. Legacy edu-sharing JSON: "properties" wrapper or top-level ccm:*
        props = (
            data.get("properties")
            or data.get("node", {}).get("properties")
            or data
        )
        if isinstance(props, dict):
            def _first(keys: list[str]) -> str:
                for k in keys:
                    v = props.get(k)
                    if isinstance(v, list) and v:
                        return str(v[0])
                    if isinstance(v, str) and v:
                        return v
                return ""

            def _list(keys: list[str]) -> list[str]:
                for k in keys:
                    v = props.get(k)
                    if isinstance(v, list) and v:
                        return [str(x) for x in v if x]
                    if isinstance(v, str) and v:
                        return [v]
                return []

            out["title"] = _first(["cm:title", "cm:name", "title", "name"])
            out["description"] = _first([
                "cclom:general_description", "description",
            ])
            out["keywords"] = _list(["cclom:general_keyword", "keywords"])
            out["disciplines"] = _list([
                "ccm:taxonid_DISPLAYNAME", "disciplines",
                "ccm:taxonid",
            ])
            out["educational_contexts"] = _list([
                "ccm:educationalcontext_DISPLAYNAME",
                "ccm:educationalcontext", "educational_contexts",
            ])
            out["learning_resource_types"] = _list([
                "ccm:oeh_lrt_aggregated_DISPLAYNAME",
                "ccm:oeh_lrt_aggregated", "learning_resource_types",
            ])
            out["url"] = _first(["wwwurl", "url", "ccm:wwwurl"])
            if out["title"]:
                return out

    # 3. Fallback: parse "Key: Value" text body (markdown output)
    def _grab(pattern: str) -> str:
        m = re.search(pattern, raw, re.IGNORECASE | re.MULTILINE)
        return (m.group(1) or "").strip() if m else ""

    def _grab_list(pattern: str) -> list[str]:
        txt = _grab(pattern)
        if not txt:
            return []
        # comma- or pipe-separated
        parts = re.split(r"[,;|]\s*", txt)
        return [p.strip() for p in parts if p.strip()]

    out["title"] = _grab(r"^Titel\s*[:\-]\s*(.+)$") or _grab(r"^Title\s*[:\-]\s*(.+)$")
    out["description"] = _grab(r"^Beschreibung\s*[:\-]\s*(.+)$") or _grab(
        r"^Description\s*[:\-]\s*(.+)$"
    )
    out["keywords"] = _grab_list(r"^(?:Keywords|Schlagworte)\s*[:\-]\s*(.+)$")
    out["disciplines"] = _grab_list(r"^(?:Fächer|Disciplines|Fach)\s*[:\-]\s*(.+)$")
    out["educational_contexts"] = _grab_list(
        r"^(?:Bildungsstufen?|Stufen?|Educational\s*Context)\s*[:\-]\s*(.+)$"
    )
    out["learning_resource_types"] = _grab_list(
        r"^(?:Materialtypen?|Resource\s*Types?|LRT)\s*[:\-]\s*(.+)$"
    )
    out["url"] = _grab(r"^URL\s*[:\-]\s*(\S+)$")
    return out


# ────────────────────────────────────────────────────────────────────
# Main resolve entry point
# ────────────────────────────────────────────────────────────────────


async def resolve_page_context(
    page_context: dict[str, Any],
    session_state: dict[str, Any],
    *,
    force_refresh: bool = False,
) -> dict[str, Any] | None:
    """Resolve the host page's metadata via MCP and cache it on session_state.

    Returns the resolved metadata dict, or None if nothing was resolvable.
    Never raises — on any failure, returns None and logs.

    Strategy:
      1. If `node_id` / `collection_id` is present → call `get_node_details`.
      2. Else if `topic_page_slug` is present → call `search_wlo_topic_pages`
         with the slug as query and take the top hit's nodeId, then node_details.
      3. Else: cache a minimal {"title": document_title, "unresolved": True}
         so the prompt can at least show the page title.
      4. TTL-cached per (node_id|collection_id|slug) signature.
    """
    if not isinstance(page_context, dict) or not page_context:
        return None

    signature = _current_context_signature(page_context)
    if not signature.strip("|"):
        # No addressable context — only titles/search_query — minimal fallback
        title = page_context.get("document_title") or ""
        if not title:
            return None
        meta = {
            "title": title,
            "description": "",
            "keywords": [],
            "disciplines": [],
            "educational_contexts": [],
            "learning_resource_types": [],
            "url": "",
            "source": "document_title_only",
            "unresolved": True,
            "_signature": signature,
            "_resolved_at": time.time(),
        }
        session_state.setdefault("entities", {})[_META_KEY] = meta
        return meta

    if not force_refresh and _cached_is_fresh(session_state, signature):
        return (session_state.get("entities") or {}).get(_META_KEY)

    node_id = (page_context.get("node_id") or "").strip()
    collection_id = (page_context.get("collection_id") or "").strip()
    slug = (page_context.get("topic_page_slug") or "").strip()

    meta: dict[str, Any] | None = None

    try:
        # Path 1: direct node_id / collection_id → get_node_details (JSON)
        # JSON output gives us label-resolved disciplines/educationalContexts
        # without further URI-→-label cache lookups in Boerdi.
        target_id = node_id or collection_id
        if target_id:
            raw = await mcp_client.call_mcp_tool(
                "get_node_details",
                {"nodeId": target_id, "outputFormat": "json"},
            )
            if raw and not raw.startswith("MCP error"):
                fields = _extract_node_fields(raw)
                if fields.get("title"):
                    meta = {
                        **fields,
                        "node_id": target_id,
                        "source": "get_node_details",
                        "unresolved": False,
                    }

        # Path 2: topic page slug → search_wlo_topic_pages → node_details
        if meta is None and slug:
            query = slug.replace("-", " ").replace("_", " ")
            raw = await mcp_client.call_mcp_tool(
                "search_wlo_topic_pages",
                {"query": query, "maxResults": 1},
            )
            if raw and not raw.startswith("MCP error"):
                # Try to extract a nodeId out of the response text.
                m = re.search(
                    r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",
                    raw,
                )
                if m:
                    found_id = m.group(0)
                    raw2 = await mcp_client.call_mcp_tool(
                        "get_node_details",
                        {"nodeId": found_id, "outputFormat": "json"},
                    )
                    if raw2 and not raw2.startswith("MCP error"):
                        fields = _extract_node_fields(raw2)
                        if fields.get("title"):
                            meta = {
                                **fields,
                                "node_id": found_id,
                                "source": "topic_page_slug",
                                "unresolved": False,
                            }

    except Exception as e:
        logger.warning("page_context resolve failed: %s", e)
        meta = None

    if meta is None:
        # Final fallback: document_title as placeholder so LLM has *something*
        title = page_context.get("document_title") or slug or ""
        if not title:
            return None
        meta = {
            "title": title,
            "description": "",
            "keywords": [],
            "disciplines": [],
            "educational_contexts": [],
            "learning_resource_types": [],
            "url": "",
            "source": "fallback_title",
            "unresolved": True,
        }

    meta["_signature"] = signature
    meta["_resolved_at"] = time.time()
    session_state.setdefault("entities", {})[_META_KEY] = meta
    logger.info(
        "page_context resolved: title=%r source=%s disciplines=%s",
        meta.get("title"), meta.get("source"), meta.get("disciplines"),
    )
    return meta


# ────────────────────────────────────────────────────────────────────
# Prompt rendering — turn metadata into a semantic block for the LLM
# ────────────────────────────────────────────────────────────────────


def render_for_prompt(meta: dict[str, Any] | None) -> str:
    """Human-readable block for the system prompt.

    Returns empty string if no usable metadata. Otherwise returns a
    German-language block the LLM can reference directly.
    """
    if not isinstance(meta, dict):
        return ""
    title = (meta.get("title") or "").strip()
    if not title:
        return ""

    lines: list[str] = ["## Aktuelle Themenseite"]
    lines.append(f"Titel: {title}")

    desc = (meta.get("description") or "").strip()
    if desc:
        # Limit description length to keep the prompt slim
        if len(desc) > 400:
            desc = desc[:397].rsplit(" ", 1)[0] + "…"
        lines.append(f"Beschreibung: {desc}")

    disc = meta.get("disciplines") or []
    if disc:
        lines.append(f"Fächer: {', '.join(disc[:5])}")

    ctx = meta.get("educational_contexts") or []
    if ctx:
        lines.append(f"Bildungsstufen: {', '.join(ctx[:5])}")

    kw = meta.get("keywords") or []
    if kw:
        lines.append(f"Schlagworte: {', '.join(kw[:8])}")

    lrt = meta.get("learning_resource_types") or []
    if lrt:
        lines.append(f"Materialtypen auf der Seite: {', '.join(lrt[:6])}")

    if meta.get("url"):
        lines.append(f"URL: {meta['url']}")

    if meta.get("unresolved"):
        lines.append(
            "(Hinweis: vollständige Seitenmetadaten konnten nicht geladen "
            "werden — nur Seitentitel ist sicher.)"
        )

    lines.append("")
    lines.append(
        "Der Nutzer ist auf dieser Seite eingebettet. Regeln:"
    )
    lines.append(
        "- Bei Fragen wie 'Worum geht es hier?', 'Was ist das?', 'Fuer welche "
        "Klasse ist das?' -> beziehe dich direkt auf Titel/Beschreibung/Stufen."
    )
    lines.append(
        "- Bei Create-Anfragen ohne eigenes Thema ('Erstelle mir ein "
        "Arbeitsblatt dazu', 'Mach ein Quiz hierzu') -> nimm den Seitentitel "
        "als Thema."
    )
    lines.append(
        "- Bei 'mehr Material dazu', 'weitere Inhalte', 'andere Materialtypen' "
        "-> Suche mit Titel/Schlagworten starten, passend zu den Bildungsstufen."
    )
    return "\n".join(lines)


def render_raw_for_prompt(page_context: dict[str, Any] | None) -> str:
    """Fallback block when no MCP-resolved metadata is available, but the
    widget's DOM-detector extracted visible page text + heuristic fields.

    This keeps the LLM grounded on pages where the widget can SEE the
    content (most third-party WLO embeddings) but the URL doesn't match
    a known platform pattern that the MCP-resolver could deepen.

    Returns an empty string if no usable raw text is present.
    """
    if not isinstance(page_context, dict):
        return ""
    text = (page_context.get("page_text") or "").strip()
    if not text:
        return ""

    kind = (page_context.get("page_kind") or "other").lower()
    detection = page_context.get("detection_source") or ""

    lines: list[str] = ["## Inhalt der aktuellen Seite (Heuristik)"]
    if kind != "other":
        kind_labels = {
            "topic": "Themenseite",
            "collection": "Sammlung",
            "content": "Inhaltsseite (einzelnes Material)",
            "subject": "Fachportal",
            "search": "Such-Ergebnisseite",
        }
        lines.append(f"Seitentyp: {kind_labels.get(kind, kind)}")

    if page_context.get("topic_page_slug"):
        lines.append(f"Themenseite-Slug: {page_context['topic_page_slug']}")
    if page_context.get("subject_slug"):
        lines.append(f"Fach-Slug: {page_context['subject_slug']}")
    if page_context.get("search_query"):
        lines.append(f"Aktiver Suchbegriff: {page_context['search_query']}")
    if detection:
        lines.append(f"Erkennungs-Quelle: {detection}")

    # Cap snippet length — the prompt budget is finite.
    snippet = text if len(text) <= 1500 else text[:1497] + "…"
    lines.append("")
    lines.append("Sichtbarer Text der Seite (gekürzt):")
    lines.append(snippet)
    lines.append("")
    lines.append(
        "Regeln: Wenn der Nutzer mit 'hier', 'auf dieser Seite', 'das "
        "Thema', 'dazu' o.ä. referenziert, beziehe dich auf diese Inhalte. "
        "Sprich vom 'Seiteninhalt', NICHT von 'Auszug' oder 'Heuristik' — "
        "das sind interne Begriffe."
    )
    return "\n".join(lines)
