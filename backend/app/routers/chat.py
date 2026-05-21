"""Chat router — main conversation endpoint with 3-phase pattern engine."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import re as _re
from typing import Any

# Matches the header line the LP generator emits, e.g. "> **Lernpfad: Eiszeit**".
# Used to lift the exact title into the canvas payload when an LP is routed.
_re_lp_title = re.compile(r"\*\*(Lernpfad:[^*]+)\*\*")


def _norm_words(s: str) -> list[str]:
    """Lower-cased tokenization for title/topic relevance comparisons.

    Strips punctuation and splits on whitespace. Used by
    _collection_matches_topic to check topic-in-title with word boundaries
    (plain substring would accept 'eis' in 'eisen' etc.).
    """
    if not s:
        return []
    s = re.sub(r"[^\w\säöüÄÖÜß-]+", " ", s.lower())
    return [w for w in s.split() if w]


def _collection_matches_topic(cards: list[WloCard], topic: str) -> bool:
    """True if at least one collection title contains the topic as a word.

    Uses word-boundary matching — 'Eiszeit' would match the title
    'Eiszeit und Klimawandel', but NOT 'Eisen-Erzeugung'. Multi-word
    topics require the longest content word to appear as a full token.
    """
    if not topic or not cards:
        return False
    topic_tokens = _norm_words(topic)
    # Prefer the longest token (typically the most specific keyword)
    content = [t for t in topic_tokens if len(t) >= 4]
    if not content:
        # Topic was only stopwords / short tokens — accept conservatively
        return True
    key = max(content, key=len)
    for c in cards:
        title_tokens = _norm_words(getattr(c, "title", "") or "")
        if key in title_tokens:
            return True
        # Also allow morphological neighbours: prefix match ≥5 chars
        # (e.g. topic 'Eiszeit' ↔ title token 'Eiszeiten' / 'Eiszeitalter')
        for tt in title_tokens:
            if len(tt) >= 5 and (tt.startswith(key) or key.startswith(tt)):
                return True
    return False

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.models.schemas import ChatRequest, ChatResponse, ClassificationResult, DebugInfo, PaginationInfo, WloCard
from app.services.database import (
    get_or_create_session, update_session, get_messages, get_memory,
    log_safety_event,
)
from app.services.database import save_message as _db_save_message


async def save_message(session_id: str, role: str, content: str,
                       cards=None, debug=None):
    """Gated message persistence — respects 01-base/privacy-config.yaml.

    When `logging.messages: false` is configured, calls become no-ops so
    the chat runs without ever storing user/bot text. Safety-log path is
    unaffected (it uses log_safety_event directly, not save_message).
    """
    try:
        from app.services.config_loader import load_privacy_config
        if not load_privacy_config().get("messages", True):
            return
    except Exception:
        # Loader failure → default to logging (conservative).
        pass
    await _db_save_message(session_id, role, content, cards=cards, debug=debug)
from app.services.rate_limiter import check_rate_limit
from app.services.llm_service import (
    classify_input, generate_response, generate_quick_replies, generate_learning_path_text,
)
from app.services.canvas_service import (
    generate_canvas_content, generate_canvas_remix,
    edit_canvas_content, resolve_material_type, extract_material_type_from_message,
    looks_like_create_intent, material_type_quick_replies,
    material_type_quick_replies_for_persona, get_material_type_category,
    infer_material_type_from_lrt,
    # Live-reload-freundliche Getter statt Modul-Konstanten:
    get_material_types, get_type_aliases, get_search_verbs, get_create_triggers,
)
from app.services.text_extraction_service import extract_text_from_url
from app.services.mcp_client import (
    call_mcp_tool, parse_wlo_cards, parse_wlo_topic_page_cards,
    parse_total_count, resolve_discipline_labels,
    reset_query_metas, get_query_metas,
)
from app.services.pattern_engine import select_pattern, get_patterns
from app.services.rag_service import get_rag_context, get_always_on_rag_context
from app.services.config_loader import (
    card_pipeline_v2_enabled,
    get_on_demand_rag_areas,
    get_repo_base_url,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Per-session locks (race-condition guard) ────────────────────
# Prevents two concurrent requests from the same session_id from clobbering
# each other's session_state. Locks are created lazily and cleaned up
# opportunistically when no waiters remain.
_session_locks: dict[str, tuple[asyncio.Lock, int]] = {}
_session_locks_guard = asyncio.Lock()


async def _get_session_lock(session_id: str) -> asyncio.Lock:
    """Return (or lazily create) the per-session lock and bump its refcount.

    The refcount tracks how many concurrent requests are holding *or
    waiting on* this lock. ``_release_session_lock`` decrements it under
    the same guard and pops the entry once the count reaches zero, so
    the registry stays bounded under load and we never race with a
    parallel ``_get_session_lock`` that's already pulled the same lock
    object out of the dict.
    """
    async with _session_locks_guard:
        entry = _session_locks.get(session_id)
        if entry is None:
            lock = asyncio.Lock()
            _session_locks[session_id] = (lock, 1)
            return lock
        lock, count = entry
        _session_locks[session_id] = (lock, count + 1)
        return lock


async def _release_session_lock(session_id: str) -> None:
    """Decrement the lock's refcount; drop it from the registry at zero.

    Must be called *after* ``async with lock:`` has exited — calling it
    inside the ``async with`` block while ``lock.locked()`` is still
    True would simply skip the cleanup. Using a refcount instead of
    ``not lock.locked()`` avoids the TOCTOU race between a concurrent
    ``_get_session_lock`` (which has the lock object in hand but hasn't
    yet awaited ``async with``) and our pop.
    """
    async with _session_locks_guard:
        entry = _session_locks.get(session_id)
        if entry is None:
            return
        lock, count = entry
        new_count = count - 1
        if new_count <= 0:
            _session_locks.pop(session_id, None)
        else:
            _session_locks[session_id] = (lock, new_count)


def _is_empty_topic_pages_response(raw: str) -> bool:
    """True when the WLO MCP server reported no topic pages found for a
    ``search_wlo_topic_pages`` call. The server uses BOTH a German plain-
    text marker and (occasionally) an empty JSON results array — match
    either."""
    if not raw:
        return True
    if "Keine Themenseiten" in raw:
        return True
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            results = parsed.get("results") or parsed.get("items") or []
            return not results
    except Exception:
        pass
    return False


def _filter_topic_pages_by_title(raw: str, needle: str) -> str | None:
    """Filter a ``search_wlo_topic_pages`` JSON envelope to results whose
    ``title`` contains ``needle`` (case-insensitive). Returns the
    re-serialised filtered envelope, or ``None`` if no match.

    Used for the global-fallback path: when the server's tight query
    matcher returns "Keine Themenseiten gefunden" but the topic page
    actually exists in the unfiltered global list.
    """
    if not raw or not needle:
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    results = parsed.get("results") or parsed.get("items") or []
    needle_lower = needle.lower().strip()
    filtered = [
        r for r in results
        if isinstance(r, dict)
        and needle_lower in (r.get("title") or "").lower()
    ]
    if not filtered:
        return None
    out = dict(parsed)
    out["results"] = filtered
    out["total"] = len(filtered)
    out["_query_fallback"] = True
    return json.dumps(out, ensure_ascii=False)


async def _topic_pages_with_warmup(
    query: str,
    extra_args: dict[str, Any],
) -> str:
    """Run search_wlo_topic_pages with a dedicated collections warmup
    AND a global-list fallback when the server's tight query matcher
    fails to find a topic page that actually exists.

    Two empirical quirks of the WLO MCP server:

    1. Session-state: the topic-page index only populates after a
       ``search_wlo_collections`` call with small ``maxResults`` and no
       discipline filter. We run a dedicated warmup before the actual
       call so this state is always in place.

    2. Tight query matcher: ``search_wlo_topic_pages(query="Mathematik")``
       returns "Keine Themenseiten gefunden" even though a topic page
       titled exactly "Mathematik" exists in the unfiltered global list.
       The server seems to search inside topic-page CONTENT but ignores
       the topic-page title for the query match. Fallback: if the
       initial call returned no results, fetch the global list (no
       query) and filter client-side by title-contains-query.

    Tradeoff: 1 extra MCP roundtrip per turn that requests topic pages,
    plus 1 more if the query-fallback triggers. Mitigated by Phase-A3
    tool cache (TTL 300s) — repeat queries hit the cache for free.
    """
    from app.services.mcp_client import call_mcp_tool as _ct
    try:
        # Fire-and-forget warmup — its cards are discarded; only the
        # session-state side effect on the MCP server matters.
        await _ct("search_wlo_collections", {"query": query, "maxResults": 5})
    except Exception:
        pass
    primary = await _ct("search_wlo_topic_pages", extra_args)
    if not _is_empty_topic_pages_response(primary):
        return primary
    # Server returned 0 hits for the query — try the global list and
    # filter by title containment. ``maxResults`` is capped at 20 by the
    # server schema; we ask for the full window.
    try:
        global_args: dict[str, Any] = {"maxResults": 20}
        # Preserve the discipline hint if the caller provided one — even
        # with no query, the server narrows by discipline reliably.
        if extra_args.get("discipline"):
            global_args["discipline"] = extra_args["discipline"]
        global_raw = await _ct("search_wlo_topic_pages", global_args)
    except Exception as _e:
        logger.warning("topic_pages global fallback failed: %s", _e)
        return primary
    filtered = _filter_topic_pages_by_title(global_raw, query)
    if filtered:
        logger.info(
            "topic_pages query-fallback: server reported 0 hits for %r, "
            "but global-list contains a title match (returned filtered set)",
            query,
        )
        return filtered
    return primary


def _widget_modes(req: "ChatRequest") -> dict[str, bool]:
    """Extract the four widget-embed-mode flags from the request environment.

    Returns a dict with the four toggles (``cards_enabled``,
    ``canvas_enabled``, ``ai_content_enabled``, ``quick_replies_enabled``).
    Each defaults to ``True`` when the frontend has not sent the field
    (``None`` in the Pydantic Environment block) — that preserves
    backward compatibility with older widget bundles that don't know
    about these flags.

    Only an explicit ``False`` from the frontend disables a feature.
    """
    env = req.environment
    def _val(attr: str) -> bool:
        v = getattr(env, attr, None)
        return True if v is None else bool(v)
    return {
        "cards_enabled": _val("cards_enabled"),
        "canvas_enabled": _val("canvas_enabled"),
        "ai_content_enabled": _val("ai_content_enabled"),
        "quick_replies_enabled": _val("quick_replies_enabled"),
        # inline-result-grouping: separater Flag, gleiche Default-Semantik
        # (None → True seit Welle C.5). Wird vom Postprocess gebraucht, um
        # zu entscheiden, ob Cards bei ``cards_enabled=false`` zu Inline-
        # Markdown-Bullets umgewandelt werden (Legacy) oder als Cards
        # durchgereicht werden (damit das Frontend sie in der Box-Anzeige
        # rendern kann, unabhängig von der Tile-Anzeige).
        "inline_result_grouping": _val("inline_result_grouping"),
    }


def _truncate_title(title: str, max_chars: int) -> str:
    """Word-boundary-aware truncation with ellipsis.

    Cuts at the last whitespace before ``max_chars`` (kein Mitten-im-Wort-
    Cut), appends "…" if anything was removed. Returns the original title
    if it fits.
    """
    t = (title or "").strip()
    if len(t) <= max_chars:
        return t
    cut = t[:max_chars]
    space = cut.rfind(" ")
    if space >= max_chars // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:-") + "…"


def _inline_card_url(card: Any, guide_mode: bool) -> str:
    """Pick the right URL to expose in an inline link.

    Lotsen-Modus an → ``guide_url`` (Repo/WLO-Seite, falls Backend es
    annotiert hat); sonst → ``wlo_url`` (Direktlink auf Inhalt).
    Fallback: ``url`` (kann external sein) → ``content_url``.
    """
    def _g(name: str) -> str:
        v = getattr(card, name, None) if not isinstance(card, dict) else card.get(name)
        return (v or "").strip() if isinstance(v, str) else ""
    if guide_mode:
        url = _g("guide_url")
        if url:
            return url
    return _g("wlo_url") or _g("url") or _g("content_url")


# Mapping von User-Stichworten zu kanonischen Substrings, die in den
# Card-Feldern ``learning_resource_types`` matchen sollten. WLO emittiert
# diese Labels mit Capitalisation (z.B. ``['Video']``, ``['Arbeitsblatt']``),
# Match läuft case-insensitive via ``substring in lower(blob)``.
_CONTENT_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "video":          ("video", "videos"),
    "arbeitsblatt":   ("arbeitsblatt", "arbeitsblätter", "arbeitsblaetter"),
    "übung":          ("übung", "uebung", "übungen", "uebungen"),
    "quiz":           ("quiz", "test", "tests"),
    "audio":          ("audio", "podcast", "podcasts", "hörspiel", "hoerspiel"),
    "präsentation":   ("präsentation", "praesentation", "präsentationen", "praesentationen"),
    "interaktiv":     ("interaktiv", "interaktive"),
    "kurs":           ("kurs", "kurse", "tutorial", "tutorials"),
    "spiel":          ("lernspiel", "lernspiele", "spiel"),
    "grafik":         ("infografik", "grafik"),
}


def _user_wants_specific_content_type(message: str) -> bool:
    """Heuristik: fragt der User nach einem konkreten Material-Format?

    Wenn der User „Such mir ein Arbeitsblatt zu …" oder „Hast du Videos
    zu …" schreibt, will er Einzelinhalte — keine kuratierten Sammlungen.
    Dann kehren wir in der Inline-Link-Reihenfolge die Standardgruppierung
    um (Einzel zuerst statt Themenseite zuerst).
    """
    msg = (message or "").lower()
    for keywords in _CONTENT_TYPE_KEYWORDS.values():
        if any(kw in msg for kw in keywords):
            return True
    return False


def _extract_wanted_content_types(message: str) -> set[str]:
    """Welche konkreten Material-Typen hat der User in der Nachricht
    erwähnt? Returns lower-case substrings, die in
    ``card.learning_resource_types`` matchen sollten — z.B. ``{"video"}``
    bei „Hast du Videos zur …?" oder ``{"arbeitsblatt"}`` bei
    „Such mir Arbeitsblätter zu …".

    Returns leere Menge, wenn der User keinen Typ-Fokus ausgedrückt hat.
    """
    msg = (message or "").lower()
    wanted: set[str] = set()
    for canonical, keywords in _CONTENT_TYPE_KEYWORDS.items():
        if any(kw in msg for kw in keywords):
            wanted.add(canonical)
    return wanted


def _resolve_wanted_content_types(
    message: str,
    session_entities: dict | None = None,
    classification_entities: dict | None = None,
) -> set[str]:
    """Welle C Sprint 6 Hotfix — Vollständiger Type-Filter aus 3 Quellen.

    Zieht den Material-Typ-Wunsch aus:
      1. Aktueller User-Nachricht ("nur videos zeigen" → {"video"})
      2. ``classification.entities.medientyp`` (frisch vom Classifier)
      3. ``session_state.entities.medientyp`` (aus vorherigem Turn akkumuliert)

    Damit überlebt der Filter ein Follow-up wie „nur Videos zeigen"
    auch wenn der Classifier den medientyp nicht erneut extrahiert hat
    (weil das alte session-Wissen bereits präsent ist).

    User-Bug-Report Sprint 6: Ohne diesen Resolver landete der Bot bei
    „nur Videos zeigen" auf PAT-06 und zeigte trotzdem Sammlungen
    statt nur Videos.
    """
    wanted = _extract_wanted_content_types(message)

    for src in (classification_entities, session_entities):
        if not isinstance(src, dict):
            continue
        mt = src.get("medientyp") or src.get("material_typ") or ""
        if not isinstance(mt, str) or not mt.strip():
            continue
        # Map auf canonical key — wenn der Wert direkt einem Keyword
        # entspricht (z.B. "Video"), nutze ihn als Filter-String.
        mt_lower = mt.strip().lower()
        # Bevorzuge canonical-Match wenn möglich
        matched = False
        for canonical, keywords in _CONTENT_TYPE_KEYWORDS.items():
            if mt_lower == canonical or any(kw in mt_lower for kw in keywords):
                wanted.add(canonical)
                matched = True
                break
        if not matched and mt_lower:
            # Fallback: das raw-Wort als Substring nutzen
            wanted.add(mt_lower)

    return wanted


def _card_matches_wanted_types(card: Any, wanted: set[str]) -> bool:
    """True, wenn die ``learning_resource_types`` der Card einen der vom
    User gewünschten Typen enthalten. Wenn ``wanted`` leer ist (kein Typ-
    Fokus), gibt's keine Einschränkung → True. Substring-Match auf der
    lowercase-konkatenierten Type-Liste.
    """
    if not wanted:
        return True
    lrt = (card.get("learning_resource_types") if isinstance(card, dict)
           else getattr(card, "learning_resource_types", None))
    if not lrt:
        return False
    blob = " ".join(str(t).lower() for t in lrt if t)
    return any(w in blob for w in wanted)


def _apply_llm_card_selection(
    cards: list[Any], selected_ids: list[str] | None,
) -> list[Any]:
    """Filtere ``cards`` auf die vom LLM via ``select_top_cards`` gewählten
    IDs, in der vom LLM angegebenen Reihenfolge.

    ID-Vergleich auf ``node_id``-Feld (UUID-String). Nicht-Matching-IDs
    werden ignoriert (LLM könnte mal halluziniert haben). Cards, die im
    Original sind aber NICHT in der Auswahl, werden weggelassen — der LLM
    hat sich bewusst gegen sie entschieden.

    Bei leerer/None-Selection → unveränderte Card-Liste zurückgeben
    (Caller fällt auf algorithmische Sortierung zurück).
    """
    if not selected_ids:
        return list(cards or [])
    if not cards:
        return []
    # Build node_id → card lookup
    by_id: dict[str, Any] = {}
    for c in cards:
        nid = c.get("node_id") if isinstance(c, dict) else getattr(c, "node_id", None)
        if isinstance(nid, str) and nid:
            by_id[nid] = c
    # Pick in LLM order; skip IDs the LLM produced but we can't find
    ordered: list[Any] = []
    for nid in selected_ids:
        c = by_id.get(nid)
        if c is not None:
            ordered.append(c)
    # Salvage: wenn die LLM-Auswahl ZERO matches produziert (typisch wenn
    # das Modell IDs aus früheren Turns oder Halluzinationen liefert),
    # nehmen wir lieber die ungefilterte Card-Liste als gar nichts —
    # algorithmisch sortiert ist immer noch besser als leere Inline-Liste.
    if not ordered and cards:
        logger.warning(
            "select_top_cards: %d selected IDs aber 0 Matches in %d cards — "
            "fallback auf ungefilterte Liste",
            len(selected_ids), len(cards),
        )
        return list(cards)
    return ordered


def _sort_cards_for_inline(cards: list[Any], prefer_content: bool) -> list[Any]:
    """Sortiere Cards für Inline-Link-Anzeige in Gruppen.

    Default: Themenseite → Sammlungen → Einzelinhalte (wie im Canvas).
    Bei ``prefer_content=True`` (User fragt nach konkretem Format):
    Einzelinhalte → Themenseiten → Sammlungen.

    Innerhalb jeder Gruppe bleibt die ursprüngliche Reihenfolge (Relevanz
    aus MCP) erhalten.
    """
    def _g(c: Any, name: str) -> Any:
        return c.get(name) if isinstance(c, dict) else getattr(c, name, None)

    def is_topic_page(c: Any) -> bool:
        nt = _g(c, "node_type")
        if nt == "topic_page":
            return True
        return nt == "collection" and bool(_g(c, "topic_pages"))

    def is_collection_only(c: Any) -> bool:
        nt = _g(c, "node_type")
        return nt == "collection" and not _g(c, "topic_pages")

    def is_content(c: Any) -> bool:
        nt = _g(c, "node_type")
        return nt not in ("collection", "topic_page")

    topic = [c for c in cards if is_topic_page(c)]
    coll = [c for c in cards if is_collection_only(c)]
    content = [c for c in cards if is_content(c)]

    if prefer_content:
        return content + topic + coll
    return topic + coll + content


def _extract_web_links_from_text(
    text: str,
    cards: list[Any] | None = None,
    *,
    max_links: int = 5,
) -> tuple[str, list[dict[str, str]]]:
    """Zieht Markdown-Links ``[label](url)`` aus dem Bot-Antwort-Text raus,
    sofern sie nicht bereits zu einer Card gehören. Rückgabe:

    - **cleaned_text**: Originaltext, aber Bullet-Zeilen die nur aus
      Link bestehen sind entfernt; Inline-Links sind zu Plain-Text-
      Labels umgewandelt (``[Label](url)`` → ``Label``). Triple-Blank-
      Lines werden auf Double kollabiert.
    - **web_links**: Liste ``[{title, url}]`` der promoteten Links in
      Erscheinungsreihenfolge, dedupliziert.

    Card-URLs (``link``, ``url``, ``wlo_url``, ``topic_pages[*].url``)
    werden ausgeschlossen, damit Treffer-Kacheln nicht doppelt erscheinen
    (einmal als Card, einmal als Web-Link). Frontend liest ``web_links``
    direkt aus dem strukturierten Feld statt im Markdown zu parsen.

    ``max_links`` cappt die Liste (Default 5) — verhindert dass ein
    überschwängliches LLM 20 Links in die Box pumpt.
    """
    raw = text or ""
    # Fast-Path: nichts zu tun wenn weder Markdown- noch HTML-Link-Pattern
    # im Text auftaucht. Beide Indikatoren prüfen — sonst wären HTML-only-
    # Outputs (z.B. ``- <a href="...">X</a>``) fälschlich übersprungen.
    has_md = "[" in raw and "](" in raw
    has_html = "<a " in raw.lower() and "href" in raw.lower()
    if not has_md and not has_html:
        return raw, []

    # Card-URLs sammeln (für Filter — verhindert Duplikate mit Card-Boxen)
    card_urls: set[str] = set()
    for c in (cards or []):
        if isinstance(c, dict):
            _get = lambda k: c.get(k)
        else:
            _get = lambda k, _c=c: getattr(_c, k, None)
        for fld in ("link", "guide_url", "wlo_url", "url", "topic_page_url"):
            v = (_get(fld) or "").strip() if _get(fld) else ""
            if v:
                card_urls.add(v)
        tps = _get("topic_pages") or []
        if isinstance(tps, list):
            for tp in tps:
                if isinstance(tp, dict):
                    tu = (tp.get("url") or "").strip()
                    if tu:
                        card_urls.add(tu)

    # Aggressive Link-Regex für ZWEI Syntax-Varianten:
    #  A) Markdown ``[label](url)`` — Standard-Bot-Output
    #  B) HTML ``<a href="url">label</a>`` — manche LLMs produzieren das,
    #     vor allem in Bullet-Listen oder bei Pattern-Outputs die HTML
    #     teilweise erlauben (gebraucht für mehr Layout-Kontrolle)
    #
    # Bullet-Variante: ganze Zeile entfernen wenn sie ausschließlich aus
    # Bullet + Link besteht. Verschiedene Bullet-Marker erlaubt: ``-`` ``*``
    # ``+`` (Markdown) sowie typografische Zeichen wie ``•`` ``◦`` ``▪`` ``·``
    # die manche LLMs trotz Markdown-Anweisung produzieren.

    # Markdown-Bullet-Line: ``- [Label](url)``  (auch mit Bold/Italic/Quote
    # um den Link, nummerierte Listen ``1. [Label](url)`` und beliebigem
    # Präfix-Text VOR dem Link wie ``- **Sammlung:** [Dreiecke](url)`` oder
    # ``- Video: [Titel](url)``. Der Präfix ist alles bis zur ersten ``[``
    # und darf ``**``/``__``/``:`` und Wörter enthalten — solange darin
    # KEIN weiterer Markdown-Link vorkommt.
    bullet_link_re = _re.compile(
        r"""^\s*
            (?:[-*+•◦▪·‣⁃▪►▶]|\d+[.)])    # Bullet ODER ``1.``/``1)`` Numbering
            \s+
            [^\[\n]{0,80}?                # optionaler Präfix vor dem Link
                                          # (Label wie ``**Sammlung:**``)
            \[([^\]\n]+)\]
            \(\s*<?(https?://.+?)>?\s*\)
            [^\[\n]{0,40}?                # optionaler Suffix nach dem Link
                                          # (Trailing-Bold/Italic-Wrapper,
                                          # Punctuation, kurze Anmerkung)
            \s*$
        """,
        _re.VERBOSE,
    )
    # HTML-Bullet-Line: ``- <a href="url">Label</a>``  (auch mit Bold)
    bullet_html_link_re = _re.compile(
        r"""^\s*[-*+•◦▪·]\s+
            (?:\*{0,2}|_{0,2})            # ggf. **/* Bold/Italic
            <a\s+[^>]*?href\s*=\s*["'](https?://[^"']+)["'][^>]*>
            ([^<]+)
            </a>
            (?:\*{0,2}|_{0,2})
            \s*$
        """,
        _re.VERBOSE | _re.IGNORECASE,
    )
    # Inline-Markdown-Link irgendwo im Text
    inline_link_re = _re.compile(
        r"""\[([^\]\n]+)\]\s*
            \(
            [^)]*?
            (https?://[^)\s>"'<]+)
            [^)]*?
            \)
        """,
        _re.VERBOSE,
    )
    # Inline-HTML-Link irgendwo im Text
    inline_html_link_re = _re.compile(
        r"""<a\s+[^>]*?href\s*=\s*["'](https?://[^"']+)["'][^>]*>
            ([^<]+)
            </a>
        """,
        _re.VERBOSE | _re.IGNORECASE,
    )

    web_links: list[dict[str, str]] = []
    seen: set[str] = set()

    def _is_material_url(url: str) -> bool:
        """True wenn ``url`` auf ein einzelnes Material zeigt (Video,
        Arbeitsblatt, externes Lehrer-Online-Modul, …) statt auf eine
        Webseite (Artikel, FAQ, Themenseite). Solche URLs gehören NICHT
        in die ``web_links``-Box „Webseiten-Inhalte" — sie sind Inhalte,
        die der LLM nur zufällig inline verlinkt hat, statt sie über die
        Card-Pipeline anzubieten.

        Heuristiken:
        - edu-sharing-Render-Pfade (``/edu-sharing/components/`` etc.)
        - Video-Plattformen (YouTube, Vimeo, Mediathekviewweb)
        - Direkt-Downloads (PDF, MP4, MP3, …)
        """
        u = (url or "").lower()
        if not u:
            return False
        # edu-sharing Material-Render-Pfade
        if (
            "/edu-sharing/components/" in u
            or "/edu-sharing/eduservlet/" in u
            or "/edu-sharing/rest/" in u
        ):
            return True
        # Video-Plattformen (YouTube, Vimeo etc. = einzelne Inhalte)
        from urllib.parse import urlparse
        try:
            host = (urlparse(url).hostname or "").lower()
        except Exception:
            host = ""
        if any(host.endswith(h) for h in (
            "youtube.com", "youtu.be", "vimeo.com",
            "dailymotion.com", "twitch.tv", "tiktok.com",
        )):
            return True
        # Direkt-File-URLs (Endung)
        if u.endswith((
            ".pdf", ".mp4", ".mp3", ".wav", ".ogg", ".webm",
            ".docx", ".doc", ".pptx", ".ppt", ".odt", ".odp",
            ".zip", ".epub",
        )):
            return True
        return False

    def _record(label: str, url: str) -> bool:
        """True wenn Link aufgenommen ODER bewusst gestrippt werden soll.
        Rückgabe steuert nur die Text-Strip-Logik — ``web_links`` wird
        intern befüllt. ``True`` heißt: aus Text entfernen (Bullet) bzw.
        durch Label ersetzen (Inline). ``False`` heißt: ungültiger Input
        oder leeres Label.
        """
        label = (label or "").strip()
        url = (url or "").strip()
        if not label or not url:
            return False
        if url in seen:
            # Duplikat — aus Text strippen, aber kein 2. Eintrag in web_links
            return True
        # URL wird trotzdem aus Text entfernt, kommt aber nicht in die
        # ``Webseiten-Inhalte``-Box wenn es ein Card-Treffer ODER ein
        # einzelnes Material ist. So bleibt der Bot-Text frei von Links,
        # ohne dass die Box Materialien aufnimmt, die in die Sammlungen-
        # /Inhalte-Boxen gehören.
        skip_box = (url in card_urls) or _is_material_url(url)
        if skip_box:
            seen.add(url)
            return True
        if len(web_links) >= max_links:
            # Trotz max-Cap aus dem Text strippen — sonst stehen die
            # ersten 5 in der Box und der 6. bleibt als Underline im Text.
            seen.add(url)
            return True
        seen.add(url)
        web_links.append({"title": label, "url": url})
        return True

    # Pass 1: zeilenweise — Bullet-Link-Zeilen ganz entfernen.
    # Versucht erst Markdown-Bullet, dann HTML-Bullet — Reihenfolge
    # wichtig, damit ein gemischter Pattern wie ``- <a href=...>X</a>``
    # nicht durch die Markdown-Regex fälschlich gematcht würde.
    out_lines: list[str] = []
    for line in raw.split("\n"):
        m_md = bullet_link_re.match(line)
        if m_md and _record(m_md.group(1), m_md.group(2)):
            continue
        m_html = bullet_html_link_re.match(line)
        if m_html and _record(m_html.group(2), m_html.group(1)):
            # HTML: group(1) = url, group(2) = label (Reihenfolge anders als MD)
            continue
        out_lines.append(line)
    stripped = "\n".join(out_lines)

    # Pass 2a: Inline-Markdown-Links → "[Label](url)" durch "Label" ersetzen
    def _replace_md(match: "_re.Match[str]") -> str:
        label, url = match.group(1), match.group(2)
        if _record(label, url):
            return label
        return match.group(0)

    # Pass 2b: Inline-HTML-Links → "<a href="url">Label</a>" durch "Label"
    def _replace_html(match: "_re.Match[str]") -> str:
        # HTML-Regex hat group(1)=url, group(2)=label
        url, label = match.group(1), match.group(2)
        if _record(label, url):
            return label
        return match.group(0)

    cleaned = inline_link_re.sub(_replace_md, stripped)
    cleaned = inline_html_link_re.sub(_replace_html, cleaned)

    # Triple-Blank-Lines kollabieren (Bullet-Strip kann Lücken hinterlassen)
    cleaned = _re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, web_links


def _icon_name_for_card(card: Any) -> str:
    """Pick a Material-Symbol-Name passend zum Inhaltstyp einer Card.

    Wird beim Inline-Link-Rendering (``_build_inline_card_links``) als
    Sentinel ``@@ICON:NAME@@`` voran gestellt — das Frontend ersetzt das
    in ``renderMarkdown`` mit dem passenden Inline-SVG aus ``shared/icons.ts``.
    Damit sieht der User auf einen Blick, ob ein Inline-Treffer eine
    Themenseite, eine Sammlung oder ein einzelnes Material ist.
    """
    def _g(name: str) -> Any:
        return card.get(name) if isinstance(card, dict) else getattr(card, name, None)
    node_type = _g("node_type") or ""
    topic_pages = _g("topic_pages") or []
    if node_type == "topic_page":
        return "topic"              # Themenseite (Stern-Icon)
    if node_type == "collection":
        if topic_pages:
            return "topic"          # Themenseite (Stern-Icon)
        return "auto_stories"        # Sammlung (Buch-Stapel)
    # Einzel-Inhalt — Typ aus learning_resource_types ableiten
    types = _g("learning_resource_types") or []
    types_l = [str(t).lower() for t in types if t]
    has = lambda needle: any(needle in t for t in types_l)
    if has("video"):
        return "play_circle"
    if has("arbeitsblatt"):
        return "article"
    if has("interaktiv"):
        return "videogame_asset"
    if has("audio"):
        return "headphones"
    if has("quiz") or has("test"):
        return "quiz"
    if has("präsent") or has("praesent"):
        return "image"
    if has("übung") or has("uebung"):
        return "edit_note"
    if has("kurs"):
        return "school"
    if has("webseite") or has("website"):
        return "language"
    return "menu_book"


def _build_inline_card_links(
    cards: list[Any],
    guide_mode: bool,
    limit: int,
    title_max: int,
    prefer_content: bool = False,
) -> str:
    """Render up to ``limit`` cards as a Markdown bullet-list of links.

    Returns "" if no usable cards remain. Each entry is::

        - [@@ICON:NAME@@ Kurztitel](URL)

    Das Frontend ersetzt das ``@@ICON:NAME@@``-Sentinel mit dem passenden
    Material-Symbol-Inline-SVG (hellgrau gestylt), damit Nutzer
    Themenseiten, Sammlungen und Einzelmaterialien optisch unterscheiden
    können — ohne Kachel-Layout.

    Reihenfolge: standardmäßig Themenseite → Sammlung → Einzelinhalt
    (analog zum Canvas-Kachel-Grid). Bei ``prefer_content=True`` (User
    fragt nach konkretem Format wie „Video", „Arbeitsblatt") kehrt sich
    das um — Einzelinhalte stehen oben, damit der Treffer-Typ den die
    User-Frage anvisiert hat, zuerst sichtbar ist.

    URL fallback chain: card.link (Card-Pipeline v2, Single Source of
    Truth) → guide_url (only when guide_mode on) → wlo_url → url →
    content_url. If even that is empty, the entry is skipped (no naked-
    text dangling). If a card has no title, the URL stands in as the
    visible label.
    """
    if not cards:
        return ""
    ordered = _sort_cards_for_inline(cards, prefer_content)
    lines: list[str] = []
    seen_urls: set[str] = set()
    for c in ordered:
        if len(lines) >= limit:
            break
        # Phase 4a: card.link bevorzugen (build_card_link Single Source of
        # Truth — collections?id= für Sammlungen, render/ für Inhalte im
        # Lotsen-Modus, externe URL im Normal-Modus). Wenn nicht gesetzt,
        # fällt der alte _inline_card_url-Pfad ein.
        url = (c.get("link") if isinstance(c, dict)
               else getattr(c, "link", "")) or ""
        if not url:
            url = _inline_card_url(c, guide_mode)
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        title = ""
        try:
            title = (c.get("title") if isinstance(c, dict)
                     else getattr(c, "title", "")) or ""
        except Exception:
            title = ""
        title = _truncate_title(title, title_max) or url
        icon = _icon_name_for_card(c)
        # Icon-Sentinel INSIDE der Markdown-Link-Klammern, damit das Span
        # nach dem Parsen INNERHALB des ``<a>``-Tags landet und Teil der
        # Klick-Fläche wird. KEIN Leerzeichen zwischen Sentinel und Titel
        # — der Abstand kommt vom ``margin-right`` am ``.bb-inline-icon``-
        # Span (CSS). Sonst würde der Link-Underline durch das Space-
        # Zeichen vor dem Titel ziehen — optisch hässlich.
        lines.append(f"- [@@ICON:{icon}@@{title}]({url})")
    return "\n".join(lines)


def _apply_widget_modes_postprocess(
    modes: dict[str, bool],
    quick_replies: list[str],
    cards: list[Any],
    page_action: dict[str, Any] | None,
    response_text: str,
    guide_mode_on: bool,
    user_message: str = "",
    selected_card_ids: list[str] | None = None,
) -> tuple[list[str], list[Any], dict[str, Any] | None, str]:
    """Wendet die 3 Display-Toggle-Effekte auf die fertige Response an.

    Reihenfolge wichtig:
    1. ``canvas_enabled=false`` zuerst — wenn Canvas aus, müssen wir den
       Canvas-Markdown aus der ``page_action`` zurück in ``response_text``
       holen, BEVOR wir entscheiden, ob Cards inline gerendert werden.
    2. ``cards_enabled=false`` danach — wenn Cards aus, hängen wir die
       (jetzt finalen) Cards als Markdown-Liste an ``response_text`` an
       und leeren die Card-Liste.
    3. ``quick_replies_enabled=false`` zuletzt — Quick-Replies komplett
       wegfallen lassen.
    """
    from app.services.config_loader import load_widget_modes_config as _lwm

    # ── Welle C Sprint 6 Hotfix: Lotsen-URL-Konsistenz ───────────────
    # Bevor der Inline-Card-Append oder andere Text-Mutationen laufen,
    # rewrite externe URLs (``card.url`` = z.B. youtube.com) im LLM-
    # generierten Bot-Text auf die jeweilige Repo-Render-URL (``card.link``
    # / ``card.wlo_url``). Greift nur wenn Lotsen-Modus aktiv ist —
    # im Normal-Modus bleiben externe Links unverändert (der User
    # springt absichtlich raus).
    response_text = _rewrite_external_urls_to_repo(
        response_text, cards or [], guide_mode_on,
    )

    # Vor jeder Transformation festhalten, ob die Antwort eine "echte"
    # Information anbietet (Cards oder Canvas-Material). Lotsen-Inline-
    # Links zu RAG-Quellen (FAQ, WLO-Webseite, Fachportale…) sind nur
    # dann sinnvoll, wenn die Antwort sonst rein textuell wäre. Sobald
    # Cards oder ein Canvas-Dokument im Spiel sind, lenken zusätzliche
    # Off-Topic-Links nur ab und sehen wie Werbung aus — der User möchte
    # dann die Hauptinformation lesen.
    _has_substantive_content = bool(cards) or (
        isinstance(page_action, dict)
        and page_action.get("action") in {
            "canvas_open", "canvas_update", "canvas_show_cards",
        }
        and (
            page_action.get("action") != "canvas_show_cards"
            or ((page_action.get("payload") or {}).get("cards"))
        )
    )

    # ── 1) canvas_enabled=false ──────────────────────────────────────
    if not modes["canvas_enabled"] and page_action and isinstance(page_action, dict):
        action = page_action.get("action") or ""
        payload = page_action.get("payload") or {}
        if action in {"canvas_open", "canvas_update"}:
            md = (payload.get("markdown") or "").strip() if isinstance(payload, dict) else ""
            if md:
                # Sentinel-HTML-Kommentar als Marker für das Frontend.
                # Das Frontend nutzt ihn um:
                #   1. den Marker beim Render zu strippen (DOMPurify-safe),
                #   2. einen Print-/PDF-Button für genau diese Nachricht
                #      anzuzeigen (analog zum Lernpfad-Print-Button),
                #   3. eine treffende Print-Überschrift zu setzen.
                # Format: <!-- boerdi:printable-canvas|<type>|<title> -->
                # <type> ist material_type aus dem Canvas-Payload
                # (z.B. "lernpfad", "arbeitsblatt", "quiz"); <title> ist
                # der vom Backend gesetzte Dokument-Titel.
                _ct_type = ""
                _ct_title = ""
                if isinstance(payload, dict):
                    _ct_type = str(payload.get("material_type") or "material").strip().lower()
                    _ct_title = str(payload.get("title") or "Material").strip()
                # Pipe in title escapen, damit das Parsing im Frontend
                # nicht durcheinanderkommt.
                _ct_title_safe = _ct_title.replace("|", "/").replace("-->", "--&gt;")
                sentinel = f"<!-- boerdi:printable-canvas|{_ct_type}|{_ct_title_safe} -->"
                # Markdown ins Chat-Text einbauen, Canvas-Action droppen.
                response_text = (
                    response_text + "\n\n" + sentinel + "\n\n" + md
                ).strip()
            page_action = None
        elif action == "canvas_show_cards":
            # Cards aus dem Canvas-Payload zurück ins Top-Level cards-Feld
            # heben, damit (falls cards_enabled=true) die normale Card-
            # Anzeige im Chat greift. Bei cards_enabled=false werden sie
            # weiter unten zu Inline-Links transformiert.
            inner = (payload.get("cards") or []) if isinstance(payload, dict) else []
            if isinstance(inner, list) and inner:
                cards = list(inner) + list(cards or [])
            page_action = None

    # Lotsen-QRs (``__guide__|Label|URL``) werden als Inline-Markdown-Links
    # ans Antwort-Ende gehängt — aber nur, wenn die Antwort sonst rein
    # textuell wäre. Pillen-Buttons für Absprung-Links sehen UX-mäßig
    # schlecht aus; die Chatfortführungs-Pillen sollen für *Konversation*
    # da sein, nicht für Navigation. Card-Buttons (``card.guide_url``)
    # sind ein separater Mechanismus und bleiben unverändert.
    def _extract_guide_inline(qrs: list[str]) -> tuple[list[str], list[str]]:
        kept: list[str] = []
        inline: list[str] = []
        for qr in qrs:
            if isinstance(qr, str) and qr.startswith("__guide__|"):
                rest = qr[len("__guide__|"):]
                if "|" in rest:
                    label, url = rest.split("|", 1)
                    label = label.strip() or "Bring mich hin"
                    url = url.strip()
                    if url:
                        inline.append(f"- [{label}]({url})")
                        continue
            kept.append(qr)
        return kept, inline

    # Inline-Modus (Host-Setting cards-enabled="false") signalisiert „minimaler
    # UI-Fußabdruck — nur Kachel-Treffer als Inline-Links". RAG-Fallback-
    # Hinweise (FAQ, Themenseiten via guide_qr_injector) wären in diesem
    # Modus Lärm: der User hat die schlanke Variante gewählt, will keine
    # spekulativen Off-Topic-Hinweise. Daher Lotsen-QRs hier IMMER strippen,
    # statt sie als Inline-Markdown anzuhängen.
    #
    # AUSNAHME (Welle C.5 Refactor 2026-05-21): Wenn ``inline-result-grouping``
    # an ist (Default), gibt es im Frontend separate Box-Anzeigen für Cards
    # (Themenseiten / Sammlungen) und Webseiten-Inhalte. Dann ist
    # ``cards-enabled=false`` keine Inline-Link-Anweisung mehr, sondern nur
    # noch „keine Card-Tile-Anzeige" — die Cards bleiben aber im Array
    # erhalten und werden vom Frontend in den Boxen gerendert. Inline-Card-
    # Markdown wird in dem Fall NICHT erzeugt.
    _grouping_on_pp = modes.get("inline_result_grouping", True)
    _cards_inline_mode = (not modes["cards_enabled"]) and (not _grouping_on_pp)

    if _cards_inline_mode or _has_substantive_content:
        # Cards / Canvas-Material decken die Information ab — Lotsen-
        # Inline-Links zu RAG-Quellen wären off-topic. Lotsen-QRs aus
        # den Quick-Replies droppen, damit sie auch nicht als Pille
        # auftauchen. Inline-Mode: ebenfalls strippen (kein FAQ-Append).
        quick_replies = [
            qr for qr in quick_replies
            if not (isinstance(qr, str) and qr.startswith("__guide__|"))
        ]
        _guide_inline_lines: list[str] = []
    else:
        quick_replies, _guide_inline_lines = _extract_guide_inline(quick_replies)

    # ── 2) cards_enabled=false ───────────────────────────────────────
    # ABER: nur in den Inline-Markdown-Konversions-Pfad, wenn auch
    # ``inline-result-grouping=false`` ist. Bei aktivem Grouping bleiben
    # Cards in der Liste erhalten — das Frontend rendert sie dann in den
    # Result-Group-Boxen (Themenseiten/Sammlungen/Webseiten), nicht als
    # Tile und nicht als Inline-Markdown. Siehe ``_cards_inline_mode`` oben.
    if (not modes["cards_enabled"]) and not _grouping_on_pp:
        wm = _lwm()
        limit = int(wm.get("cards_inline_link_limit", 3))
        title_max = int(wm.get("cards_inline_link_title_max", 70))
        # Wenn die Antwort schon KI-generiertes Canvas-Material enthält
        # (Lernpfad, Arbeitsblatt, Quiz, Bericht …), die separate Inline-
        # Card-Liste NICHT zusätzlich anhängen — die wäre redundant zum
        # Material selbst (das im Lernpfad-Fall sogar die Cards bereits
        # inline referenziert). Erkannt entweder am ``boerdi:printable-
        # canvas``-Sentinel (Material-Erzeugung) oder am intrinsischen
        # Lernpfad-Marker ``**Lernpfad:``.
        _has_inline_canvas_material = (
            "boerdi:printable-canvas" in (response_text or "")
            or _re.search(r"\*\*Lernpfad:", response_text or "")
        )
        if _has_inline_canvas_material:
            logger.info(
                "inline-mode: Antwort enthält Canvas-Material — "
                "keine zusätzliche Inline-Card-Liste angehängt"
            )
            cards = []
            # page_action kann gleich raus — Inline-Material läuft komplett
            # über response_text.
            if page_action and isinstance(page_action, dict):
                _pl = page_action.get("payload") or {}
                if isinstance(_pl, dict) and "cards" in _pl:
                    _pl["cards"] = []
                    page_action["payload"] = _pl
            # ── 2b) Lotsen-Inline-Links anhängen (nach Cards-Inline, damit sie
            #         als eigene Liste darunter auftauchen) ──────────────────────
            if _guide_inline_lines:
                response_text = (
                    response_text.rstrip() + "\n\n" + "\n".join(_guide_inline_lines)
                ).strip()
            # ── 3) quick_replies_enabled=false ───────────────────────────────
            if not modes["quick_replies_enabled"]:
                quick_replies = []
            return quick_replies, cards, page_action, response_text
        # PRIO 1: vom LLM via select_top_cards-Tool getroffene Auswahl
        # (siehe llm_service.py). Wenn das LLM Tool gerufen hat, ist diese
        # Liste die Quelle der Wahrheit — kein Re-Sortieren auf algorith-
        # mischer Basis. Damit folgt die Anzeige der semantischen Auswahl
        # des Modells (Klassenstufe, Material-Mix, Typ-Priorität).
        if selected_card_ids:
            cards_for_display = _apply_llm_card_selection(cards or [], selected_card_ids)
            # LLM hat schon sortiert + auf 5 begrenzt → kein algorithmischer
            # Sort mehr.
            prefer_content = False
        else:
            cards_for_display = list(cards or [])
            # Fallback: User fragt explizit nach Inhaltstyp (Video/Arbeitsblatt/…)?
            # Dann Einzelinhalte zuerst, sonst Themenseite → Sammlung → Einzel
            # (gleiche Reihenfolge wie das Canvas-Grid).
            prefer_content = _user_wants_specific_content_type(user_message)
        inline_md = _build_inline_card_links(
            cards_for_display, guide_mode_on, limit, title_max,
            prefer_content=prefer_content,
        )
        # Diagnostic log: wenn cards da sind aber inline_md leer bleibt,
        # ist meistens ein URL-Issue schuld (alle URLs leer oder nicht
        # allow-listed). Wir wollen das sehen, weil sonst der User nur
        # Text sieht und nicht weiß warum die Links fehlen.
        if cards_for_display and not inline_md:
            try:
                _diag = []
                for _c in cards_for_display[:3]:
                    _g = (lambda n: _c.get(n) if isinstance(_c, dict)
                          else getattr(_c, n, None))
                    _diag.append({
                        "node_id": _g("node_id"),
                        "guide_url": bool(_g("guide_url")),
                        "wlo_url": bool(_g("wlo_url")),
                        "url": bool(_g("url")),
                        "title": bool(_g("title")),
                    })
                logger.warning(
                    "inline-mode: %d cards aber 0 Links — guide_mode=%s, "
                    "limit=%d, sample=%s",
                    len(cards_for_display), guide_mode_on, limit, _diag,
                )
            except Exception:
                pass
        if inline_md:
            # Mit Leerzeile vom Bot-Text trennen, damit Markdown-Renderer
            # die Liste sauber abgrenzt.
            response_text = (response_text.rstrip() + "\n\n" + inline_md).strip()
        # Cards-Liste BEHALTEN, auch im Inline-Mode — das Frontend zeigt
        # sie nicht als Kacheln (gated durch ``cardsEnabledBool=false``),
        # aber JS-Listener / Embed-Hosts (Event-Inspector, externe Systeme
        # mit ``emit-guide-suggestion="true"``) brauchen sie, um den Top-1-
        # Treffer als ``badboerdi:guide-suggestion``-Event zu konsumieren.
        # Vorher: ``cards = []`` — Inspector im Inline-Modus blieb stumm.
        cards = cards_for_display
        # Falls die page_action noch Cards hält (z.B. show_results auf
        # /suche), ebenfalls leeren — wir wollen konsistent "keine
        # Kacheln, nur Inline-Links". Das page_action-Cards-Feld ist
        # für die Canvas-Komponente; im Inline-Mode ist Canvas eh
        # ausgeschaltet, also ist Leeren hier sinnvoll.
        if page_action and isinstance(page_action, dict):
            payload = page_action.get("payload") or {}
            if isinstance(payload, dict) and "cards" in payload:
                payload["cards"] = []
                page_action["payload"] = payload

    # ── 2b) Lotsen-Inline-Links anhängen (nach Cards-Inline, damit sie
    #         als eigene Liste darunter auftauchen) ──────────────────────
    if _guide_inline_lines:
        response_text = (
            response_text.rstrip() + "\n\n" + "\n".join(_guide_inline_lines)
        ).strip()

    # ── 3) quick_replies_enabled=false ───────────────────────────────
    if not modes["quick_replies_enabled"]:
        quick_replies = []

    return quick_replies, cards, page_action, response_text


def _attach_guide_qr(
    req: "ChatRequest",
    quick_replies: list[str],
    session_state: dict[str, Any] | None = None,
    response_text: str | None = None,
) -> list[str]:
    """Webseiten-Lotse: deterministisch einen Bring-mich-hin-QR an der
    Spitze der Quick-Replies einfügen.

    Trigger-Reihenfolge (siehe ``guide_qr_injector.inject_guide_qr``):
    1. LLM hat schon ``__guide__|...`` produziert → no-op.
    2. User-Frage matcht eine Regel aus ``guide_qr_injector._RULES``
       (z.B. "wie kann ich mitmachen" → /mitmachen).
    3. Bot hat ``query_knowledge(area=…)`` mit einer bekannten Area
       aufgerufen (verfolgt in ``session_state['_rag_areas_used']``)
       → URL der RAG-Quelle anbieten (z.B. WissenLebtOnline →
       wissenlebtonline.de).

    No-op wenn Guide-Mode aus oder Host nicht allow-listed. Fehler
    werden geschluckt — Quick-Replies sind Pure-UX-Sugar und dürfen
    einen erfolgreichen Antwort-Turn niemals blockieren.
    """
    try:
        env = req.environment
        # Hard gate: Lotsen-Modus AUS → ALLE Guide-QRs entfernen, nicht
        # nur Injektor überspringen. Das LLM kann eigenmächtig
        # ``__guide__|...``-Einträge erzeugen (Tool-Schema lädt es ein),
        # die dürfen aber nicht zum User durchschlagen, wenn der Toggle
        # bewusst aus ist. Gleiches gilt, wenn der Host nicht auf der
        # Allow-Liste steht.
        guide_on = bool(getattr(env, "guide_mode", False))
        host = (getattr(env, "host", "") or "").strip()
        if not guide_on or not host:
            return _strip_guide_qrs(quick_replies)
        from app.services.guide_mode_service import host_is_allowed
        from app.services.guide_qr_injector import inject_guide_qr
        from app.services.config_loader import load_guide_mode_config
        if not host_is_allowed(host):
            return _strip_guide_qrs(quick_replies)
        rag_areas: list[str] = []
        rag_top_sources: list[str] = []
        if isinstance(session_state, dict):
            v = session_state.get("_rag_areas_used")
            if isinstance(v, list):
                rag_areas = [a for a in v if isinstance(a, str)]
            s = session_state.get("_rag_top_sources")
            if isinstance(s, list):
                rag_top_sources = [x for x in s if isinstance(x, str)]
        # Anzahl Bring-mich-hin-Buttons pro Antwort aus guide-mode.yaml
        # lesen (1-3, default 2). Mehr als 3 würde keinen Platz für
        # Folge-Fragen-QRs lassen — config_loader clamped das.
        max_guide_qrs = int(load_guide_mode_config().get("max_guide_quick_replies", 2))
        return inject_guide_qr(
            req.message or "",
            quick_replies,
            rag_areas_used=rag_areas,
            response_text=response_text,
            rag_top_sources=rag_top_sources,
            max_guide_qrs=max_guide_qrs,
        )
    except Exception as e:
        logger.warning("guide-qr injection failed: %s", e)
        return quick_replies


def _strip_guide_qrs(quick_replies: list[str]) -> list[str]:
    """Remove every ``__guide__|...`` entry from the QR list. Used as
    the fail-safe when guide mode is off — the LLM can still emit the
    magic prefix but the user must not see it."""
    if not quick_replies:
        return list(quick_replies or [])
    return [q for q in quick_replies if not (
        isinstance(q, str) and q.startswith("__guide__|")
    )]


# Welle C Sprint 6 Hotfix — Guide-Marker-Cleaner für Bot-Antwort-Text.
# Markdown frisst die doppelten Unterstriche zu Bold-Markup, übrig bleibt
# ``guide|Label|URL`` als sichtbarer Text. Das Marker-Format gehört
# ausschließlich in ``quick_replies``.
import re as _re_guide_markers

# Match-Variants: mit und ohne führende ``__``, weil Markdown sie u.U.
# bereits weggefressen hat. Greedy bis zur nächsten Whitespace-Grenze
# nach der URL (so dass „<…> Wahnsinnig" am Zeilenende sauber stehen
# bleibt).
_GUIDE_MARKER_RE = _re_guide_markers.compile(
    r"(?:__)?guide(?:__)?\|[^|]+\|https?://\S+",
    flags=_re_guide_markers.IGNORECASE,
)


def _rewrite_external_urls_to_repo(
    text: str, cards: list[Any], guide_mode: bool,
) -> str:
    """Welle C Sprint 6 Hotfix — Lotsen-URL-Konsistenz im Bot-Text.

    Bug-Report (Inline-Widget + Lotsen): „einzelinhalte dürfen im
    lotsenmodus nicht auf die wwwurl verlinkt sein". Trotz korrekt
    annotierter ``card.link`` baute der LLM im Antwort-Text Markdown-
    Links auf ``card.url`` (externer Anbieter, z.B. ``youtube.com/...``).
    Sammlungen waren OK, weil sie keine externe URL haben — Einzel-
    inhalte aber schon.

    Fix: nach Antwort-Generierung scanne alle Markdown-Links und
    ersetze externe URLs durch die jeweilige Repo-Render-URL der
    zugehörigen Card. ``card.url`` (extern) → ``card.link`` /
    ``card.wlo_url`` (Repo). No-op wenn Lotsen aus oder keine Card-
    URL-Map verfügbar.
    """
    if not guide_mode or not text or not cards:
        return text or ""
    url_map: dict[str, str] = {}
    for c in cards:
        if isinstance(c, dict):
            ext = (c.get("url") or "").strip()
            repo = (c.get("link") or c.get("wlo_url")
                    or c.get("guide_url") or "").strip()
        else:
            ext = (getattr(c, "url", "") or "").strip()
            repo = (getattr(c, "link", "")
                    or getattr(c, "wlo_url", "")
                    or getattr(c, "guide_url", "")
                    or "").strip()
        if ext and repo and ext != repo:
            url_map[ext] = repo
    if not url_map:
        return text
    rewritten = text
    n_replaced = 0
    for ext, repo in url_map.items():
        if ext in rewritten:
            rewritten = rewritten.replace(ext, repo)
            n_replaced += 1
        else:
            # LLM often adds/removes "www." — try the opposite variant.
            if "://www." in ext:
                alt = ext.replace("://www.", "://", 1)
            elif "://" in ext:
                alt = ext.replace("://", "://www.", 1)
            else:
                continue
            if alt in rewritten:
                rewritten = rewritten.replace(alt, repo)
                n_replaced += 1
    if n_replaced:
        logger.info(
            "lotsen-mode URL-rewrite: %d external→repo replacements in response_text",
            n_replaced,
        )
    return rewritten


def _strip_guide_markers_from_text(text: str) -> str:
    """Remove stray ``__guide__|Label|URL`` (and Markdown-stripped
    ``guide|Label|URL``) markers from the bot response text.

    The marker is only legitimate inside ``quick_replies`` entries.
    When the LLM leaks it into the answer body, it shows up as
    raw text after Markdown normalisation — visually broken.

    Idempotent: safe to call multiple times. Whitespace cleanup
    afterwards collapses double-spaces that can remain after stripping
    a marker from a line.
    """
    if not text:
        return ""
    # Fast-path: skip regex if no marker-candidate substring is present.
    # Markdown can eat the surrounding underscores, so we check both
    # ``guide|`` (Markdown-cleaned) and ``guide__|`` (raw, surviving).
    low = text.lower()
    if "guide|" not in low and "guide__|" not in low:
        return text
    cleaned = _GUIDE_MARKER_RE.sub("", text)
    # Collapse multiple consecutive blanks and stranded line-ends
    cleaned = _re_guide_markers.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = _re_guide_markers.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _attach_guide_urls(
    req: "ChatRequest",
    cards: list[Any] | None,
    page_action: dict[str, Any] | None,
) -> None:
    """Webseiten-Guide-Modus: annotate ``card.guide_url`` on every card
    in the response that the widget will render, when (a) the user has
    the guide-mode toggle on AND (b) the widget runs on an allow-listed
    host.

    Annotates BOTH the inline ``cards`` list AND any cards inside a
    ``canvas_show_cards`` page_action payload — both reach the widget.

    No-op when guide-mode is off or the host isn't whitelisted, so
    callers can invoke this unconditionally.
    """
    try:
        env = req.environment
        if not getattr(env, "guide_mode", False):
            return
        host = (getattr(env, "host", "") or "").strip()
        if not host:
            return
        from app.services.guide_mode_service import (
            annotate_cards_with_guide_url, host_is_allowed,
        )
        if not host_is_allowed(host):
            return
        if cards:
            annotate_cards_with_guide_url(cards, enabled=True, host=host)
        if (
            page_action
            and isinstance(page_action, dict)
            and page_action.get("action") == "canvas_show_cards"
        ):
            payload_cards = (page_action.get("payload") or {}).get("cards") or []
            if isinstance(payload_cards, list):
                annotate_cards_with_guide_url(
                    payload_cards, enabled=True, host=host,
                )
    except Exception as e:
        # Guide-mode is optional UX — never let it break a chat turn
        logger.warning("guide_url annotation failed: %s", e)


def _direct_action_safety_text(req: "ChatRequest") -> str:
    """Concatenate user-controlled fields from req for safety screening.

    Direct-action requests (canvas_create / canvas_edit / canvas_remix /
    generate_learning_path / browse_collection) skip the regular pattern
    engine, so they would otherwise bypass the safety gate. We feed the
    raw user message plus all string-valued action_params into the same
    regex/LLM safety pipeline. Caps each field at 500 chars, total 2000.
    """
    chunks: list[str] = []
    if req.message:
        chunks.append(req.message[:500])
    for k, v in (req.action_params or {}).items():
        if isinstance(v, str) and v.strip():
            chunks.append(f"{k}: {v[:500]}")
        if sum(len(c) for c in chunks) >= 2000:
            break
    return " \n".join(chunks)[:2000]


# ── Helper: build WloCard list from raw dicts ─────────────────────
# Persona → preferred topic-page target group
_PERSONA_TO_TARGET = {
    "P-W-LK": "teacher",
    "P-W-RED": "teacher",
    "P-BER": "teacher",
    "P-VER": "general",
    "P-W-SL": "learner",
    "P-ELT": "learner",
    "P-W-POL": "general",
    "P-W-PRESSE": "general",
    "P-AND": "general",
}


def _sort_topic_pages(pages: list[dict], persona_id: str) -> list[dict]:
    """Sort topic-page variants so the best match for the persona comes first."""
    if not pages or len(pages) <= 1:
        return pages
    preferred = _PERSONA_TO_TARGET.get(persona_id, "general")

    def _rank(tp: dict) -> int:
        tg = tp.get("target_group", "").lower()
        if tg == preferred:
            return 0  # exact match first
        if tg == "general":
            return 1  # general as fallback
        if not tg:
            return 2  # unset
        return 3  # other

    return sorted(pages, key=_rank)


def _build_cards(raw: list[dict], persona_id: str = "") -> list[WloCard]:
    # ── Metadata inheritance: Themenseiten-Karten aus search_wlo_topic_pages
    # kommen nur mit Titel + Beschreibung + Varianten zurueck (keine
    # preview_url, disciplines, educational_contexts). Wenn in derselben
    # Ergebnis-Liste eine "normale" Sammlungskarte mit derselben node_id
    # existiert, uebernehmen wir deren reichere Metadaten in die
    # Themenseiten-Karte. Ergebnis: optisch konsistente Karten mit
    # Vorschau-Bild, Fach und Bildungsstufen auf Themenseiten-Ebene.
    by_nid: dict[str, dict] = {}
    for c in raw:
        nid = c.get("node_id") or ""
        if nid and nid in by_nid:
            # Merge: richer fields of one partner fill gaps in the other.
            existing = by_nid[nid]
            for k in (
                "preview_url", "description", "disciplines",
                "educational_contexts", "keywords",
                "learning_resource_types", "license", "publisher",
                "url", "wlo_url",
            ):
                if not existing.get(k) and c.get(k):
                    existing[k] = c[k]
            # Merge topic_pages by variant_id (no duplicates)
            existing_tps = existing.setdefault("topic_pages", [])
            existing_vids = {v.get("variant_id") for v in existing_tps if isinstance(v, dict)}
            for v in c.get("topic_pages") or []:
                if isinstance(v, dict) and v.get("variant_id") not in existing_vids:
                    existing_tps.append(v)
                    existing_vids.add(v.get("variant_id"))
            # If the merged card now has topic_pages, ensure it's a collection.
            if existing_tps:
                existing["node_type"] = "collection"
        elif nid:
            by_nid[nid] = dict(c)

    cards = []
    seen: set[str] = set()
    # Emit in original order — first occurrence of each node_id wins position.
    for c in raw:
        nid = c.get("node_id") or ""
        if nid and nid in seen:
            continue
        if nid:
            seen.add(nid)
            merged = by_nid[nid]
        else:
            merged = c
        tp = _sort_topic_pages(merged.get("topic_pages", []), persona_id)
        cards.append(WloCard(
            node_id=merged.get("node_id", ""),
            title=merged.get("title", ""),
            description=merged.get("description", ""),
            disciplines=merged.get("disciplines", []),
            educational_contexts=merged.get("educational_contexts", []),
            keywords=merged.get("keywords", []),
            learning_resource_types=merged.get("learning_resource_types", []),
            url=merged.get("url", ""),
            wlo_url=merged.get("wlo_url", ""),
            preview_url=merged.get("preview_url", ""),
            license=merged.get("license", ""),
            publisher=merged.get("publisher", ""),
            node_type=merged.get("node_type", "content"),
            topic_pages=tp,
        ))
    return cards


PAGE_SIZE = 5  # Max cards per page


# ── Lernpfad-Diversity helper ─────────────────────────────────────
def _get_used_lp_ids(session_state: dict) -> set[str]:
    raw = session_state.get("entities", {}).get("_lp_used_node_ids", "")
    if not raw:
        return set()
    try:
        return set(json.loads(raw))
    except Exception:
        return set()


def _add_used_lp_ids(session_state: dict, new_ids: list[str]) -> None:
    used = _get_used_lp_ids(session_state)
    used.update(i for i in new_ids if i)
    # Keep last 100 to bound size
    session_state.setdefault("entities", {})["_lp_used_node_ids"] = json.dumps(list(used)[-100:])


def _filter_cards_used_in_text(cards_raw: list[dict], response_text: str) -> list[dict]:
    """Keep only cards whose URL, wlo_url, node_id OR title appears in the LP
    response. The LP prompt asks the LLM for `[Titel](URL)` links, so URL match
    is the primary signal. Title match is a narrow fallback for cases where the
    LLM rewrites/truncates the URL.

    De-duplicates by node_id AND url (the same resource can appear under
    multiple collections with distinct node_ids) and preserves original order.

    Fallback: if *nothing* matches (e.g. LLM error or non-standard formatting),
    return the original list — it's safer to show too many cards than none.
    """
    if not cards_raw or not response_text:
        return cards_raw
    text_lower = response_text.lower()
    used: list[dict] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for c in cards_raw:
        nid = (c.get("node_id") or "").strip()
        url = (c.get("url") or "").strip()
        if nid and nid in seen_ids:
            continue
        if url and url in seen_urls:
            continue
        wlo = (c.get("wlo_url") or "").strip()
        matched = False
        # 1. URL / wlo_url / node_id — exact substring match (primary)
        if url and url in response_text:
            matched = True
        elif wlo and wlo in response_text:
            matched = True
        elif nid and nid in response_text:
            matched = True
        else:
            # 2. Title fallback — only for multi-word titles (≥ 3 words after
            #    stripping common provider suffixes). A single-word match like
            #    "Photosynthese" is too generic: it matches the LP topic itself
            #    and produces false positives. The YouTube/provider suffix
            #    (" | Mathe by Daniel Jung", " – Serlo") gets trimmed first.
            title = (c.get("title") or "").strip()
            if title:
                primary = title
                for sep in [" | ", " – ", " - "]:
                    primary = primary.split(sep)[0]
                primary = primary.strip()
                words = [w for w in primary.split() if len(w) >= 3]
                if len(words) >= 3 and len(primary) >= 15 and primary.lower() in text_lower:
                    matched = True
        if matched:
            used.append(c)
            if nid:
                seen_ids.add(nid)
            if url:
                seen_urls.add(url)
    return used if used else cards_raw


def _filter_unused_cards(cards_raw: list[dict], used: set[str]) -> tuple[list[dict], bool]:
    """Return (filtered_cards, was_reset). Resets when nothing new is left."""
    if not used:
        return cards_raw, False
    fresh = [c for c in cards_raw if c.get("node_id") and c["node_id"] not in used]
    if not fresh:
        return cards_raw, True  # nothing new — reuse all but signal reset
    return fresh, False


# ── Action: Browse collection contents ────────────────────────────
async def _handle_browse_collection(
    req: ChatRequest, session_state: dict,
) -> ChatResponse:
    """Directly call get_collection_contents MCP tool (like original Boerdi)."""
    collection_id = req.action_params.get("collection_id", "")
    title = req.action_params.get("title", "Sammlung")
    skip_count = req.action_params.get("skip_count", 0)

    if not collection_id:
        return ChatResponse(
            session_id=req.session_id,
            content="Keine Sammlungs-ID angegeben.",
        )

    tools_called = ["get_collection_contents"]
    pagination = None

    try:
        # Fetch PAGE_SIZE + 1 to detect if there are more
        result_text = await call_mcp_tool("get_collection_contents", {
            "nodeId": collection_id,
            "maxItems": PAGE_SIZE + 1,
            "skipCount": skip_count,
        })
        cards_raw = parse_wlo_cards(result_text)
        await resolve_discipline_labels(cards_raw)
        total_from_mcp = parse_total_count(result_text)

        # Mark as content items (not collections)
        for c in cards_raw:
            c.setdefault("node_type", "content")

        # Determine if there are more items
        has_more = len(cards_raw) > PAGE_SIZE
        display_cards_raw = cards_raw[:PAGE_SIZE]
        persona = session_state.get("persona_id", "")
        cards = _build_cards(display_cards_raw, persona)

        # Build pagination info
        total = total_from_mcp if total_from_mcp > 0 else (
            skip_count + len(cards_raw) if has_more else skip_count + len(cards_raw)
        )
        pagination = PaginationInfo(
            total_count=total,
            skip_count=skip_count,
            page_size=PAGE_SIZE,
            has_more=has_more,
            collection_id=collection_id,
            collection_title=title,
        )

        if cards:
            showing = f"{skip_count + 1}–{skip_count + len(cards)}"
            total_label = f" von {total}" if total > 0 else ""
            response_text = f"**{title}** — Ergebnisse {showing}{total_label}:"
        else:
            response_text = f'In der Sammlung "{title}" habe ich leider keine Inhalte gefunden.'

    except Exception as e:
        logger.error("browse_collection error: %s", e)
        cards = []
        response_text = f'Fehler beim Laden der Inhalte von "{title}": {e}'
        tools_called.append("error")

    # Generate quick replies for collection browse context.
    # Quick-replies are pure UX sugar — a B-API blip on the QR-LLM call must
    # never crash a successful response, so we degrade to an empty list.
    try:
        quick_replies = await generate_quick_replies(
            message=req.message,
            response_text=response_text,
            classification={
                "persona_id": session_state.get("persona_id", "P-AND"),
                "intent_id": "INT-W-03",
                "next_state": "state-6",
                "entities": session_state.get("entities", {}),
            },
            session_state=session_state,
        )
    except Exception as _qr_err:
        logger.warning("browse_collection quick_replies failed: %s", _qr_err)
        quick_replies = []
    quick_replies = _attach_guide_qr(req, quick_replies, session_state, response_text=response_text)

    debug = DebugInfo(
        persona=session_state.get("persona_id", ""),
        intent="INT-W-03",
        state="state-6",
        pattern="ACTION: browse_collection",
        tools_called=tools_called,
        entities=session_state.get("entities", {}),
    )

    await save_message(
        req.session_id, "assistant", response_text,
        cards=[c.model_dump() for c in cards],
        debug=debug.model_dump(),
    )

    # Canvas integration: route collection contents into the canvas instead
    # of duplicating them in the chat stream. The chat bubble gets a short
    # announcement; the full card grid lives in the canvas card pane.
    _canvas_title = f"Inhalte: {title}" if title else "Sammlungs-Inhalte"
    page_action = {
        "action": "canvas_show_cards",
        "payload": {
            "cards": [c.model_dump() for c in cards],
            "query": title or "",
            "title": _canvas_title,
            "source": "collection",
            "collection_id": collection_id,
            "pagination": pagination.model_dump() if pagination else None,
            # append=true when skip_count>0 -> frontend appends instead of replacing
            "append": skip_count > 0,
        },
    }

    _attach_guide_urls(req, cards, page_action)

    return ChatResponse(
        session_id=req.session_id,
        content=response_text,
        cards=cards,
        quick_replies=quick_replies,
        debug=debug,
        pagination=pagination,
        page_action=page_action,
    )


# ── Action: Generate learning path ───────────────────────────────
def _extract_headings(markdown: str, topic: str, levels: str = "##") -> list[str]:
    """Extract H2 (or H2+H3) headings from the markdown, skipping duplicate
    or wrapper headings that just echo the topic and filtering out meta-
    sections like "Wie liest man diese Übersicht?" / "Lösungen" that would
    otherwise become the single visible section and make the chat preview
    look empty.
    """
    import re as _re
    # Try H2 first — if few, also include H3
    h2 = _re.findall(rf"^{levels}\s+(.+?)\s*$", markdown or "", flags=_re.MULTILINE)
    if len(h2) < 2:
        h2 = _re.findall(r"^#{2,3}\s+(.+?)\s*$", markdown or "", flags=_re.MULTILINE)

    # If still too few, extract bold-bullet "**Hauptast**"-pattern from list
    # structures (common in Strukturübersicht / Glossar where headings are
    # nested instead of H2'd).
    if len(h2) < 2:
        bullet_bold = _re.findall(
            r"^\s*[-*+]\s+\*\*(.+?)\*\*",
            markdown or "", flags=_re.MULTILINE,
        )
        if bullet_bold:
            h2 = bullet_bold

    # Strip markdown syntax and trailing punctuation
    cleaned = [h.strip().strip("*_`").strip() for h in h2]
    tl = (topic or "").strip().lower()

    # Meta-sections: filter unless they're the only thing we have. These
    # are "how to use / solutions / meta" titles that don't describe content.
    META_PATTERNS = (
        r"wie\s+liest\s+man",
        r"^lösungen?$",
        r"^loesungen?$",
        r"^quellen(angabe)?$",
        r"^hinweise?$",
        r"^anhang$",
        r"^glossar$",  # only when it's a meta-ref, not the main content
        r"^weiterführende",
        r"^weiterfu[eh]hrende",
        r"^literaturverzeichnis$",
    )
    def _is_meta(h: str) -> bool:
        hl = h.strip().strip("*_`").lower()
        return any(_re.search(p, hl) for p in META_PATTERNS)

    non_meta = [h for h in cleaned if h and h.lower() != tl and not _is_meta(h)]
    meta = [h for h in cleaned if h and h.lower() != tl and _is_meta(h)]

    # Prefer non-meta sections; only fall back to meta when we'd otherwise
    # have nothing.
    out = non_meta if non_meta else meta
    return out[:6]


def _canvas_completion_message(
    label: str, topic: str, markdown: str, canvas_enabled: bool = True,
) -> str:
    """Build a rich chat-bubble text when a canvas-material is created.

    Strategy (in order):
      1. Extract non-meta H2 sections (works for Infoblatt, Strukturübersicht).
      2. If only meta headings (e.g. "Lösungen" on an Arbeitsblatt),
         count numbered tasks/questions and report that count instead.
      3. Last resort: just announce the canvas opened.
    """
    import re as _re
    sections = _extract_headings(markdown, topic)
    lines = [f"Ich habe dir ein **{label}** zum Thema *{topic}* erstellt."]

    # Has the extractor only returned meta headings (e.g. ["Lösungen"]) —
    # that means the document is task-driven (Arbeitsblatt/Quiz). Count
    # numbered tasks instead so the preview is meaningful.
    META_ONLY_SET = {"lösungen", "loesungen", "quellen", "hinweise"}
    only_meta = bool(sections) and all(
        s.strip().lower() in META_ONLY_SET for s in sections
    )

    if sections and not only_meta:
        lines.append("")
        lines.append("Abschnitte:")
        for i, s in enumerate(sections[:5], 1):
            lines.append(f"{i}. **{s}**")
    else:
        # Count numbered tasks at start-of-line ("1.", "2.", ...) — a robust
        # signal for Arbeitsblatt/Quiz/Übung documents.
        numbered = _re.findall(
            r"^\s*(\d{1,2})\.\s+\S",
            markdown or "",
            flags=_re.MULTILINE,
        )
        # Filter out the numbered "Lösungen"-list at the end by counting only
        # unique consecutive numbering from 1
        task_count = 0
        prev = 0
        for n in numbered:
            try:
                ni = int(n)
            except ValueError:
                continue
            if ni == prev + 1:
                task_count += 1
                prev = ni
            elif ni == 1:
                # restart of numbering (e.g. solutions section) — stop counting tasks
                break
        if task_count >= 2:
            lines.append("")
            lines.append(f"Enthält **{task_count} Aufgaben**" + (
                " mit Lösungen." if any(s.strip().lower() in META_ONLY_SET for s in (sections or [])) else "."
            ))
        elif sections:
            # Even meta-only: show them rather than nothing
            lines.append("")
            lines.append("Abschnitte:")
            for i, s in enumerate(sections[:5], 1):
                lines.append(f"{i}. **{s}**")

    lines.append("")
    if canvas_enabled:
        lines.append(
            "Du siehst es rechts im Canvas — ich kann es direkt anpassen, "
            "wenn du z.B. \"mach die Aufgaben einfacher\" oder \"füge Lösungen "
            "hinzu\" schreibst."
        )
    else:
        # Inline-Modus: das Material landet unter dieser Bubble im Chat-
        # Verlauf statt im Canvas. Print-Button vom Frontend angeboten
        # (siehe `boerdi:printable-canvas`-Sentinel).
        lines.append(
            "Das Material steht direkt unter dieser Nachricht — du kannst "
            "es mit dem Druck-Button als PDF speichern. Sag mir gerne, was "
            "angepasst werden soll (z.B. *\"mach die Aufgaben einfacher\"* "
            "oder *\"füge Lösungen hinzu\"*)."
        )
    return "\n".join(lines)


def _lp_completion_message(
    topic: str, markdown: str, canvas_enabled: bool = True,
) -> str:
    """Build a rich chat-bubble text for a completed learning path.

    The full path lives in the canvas — but the chat bubble needs more than
    a terse "guck im canvas"-pointer. Extract the H2/H3-Überschriften (Phasen)
    from the markdown so the user sees the roadmap inline.
    """
    phases = _extract_headings(markdown, topic)
    if canvas_enabled:
        lines = [
            f"Ich habe dir den **Lernpfad zu *{topic}*** im Canvas rechts aufgebaut."
        ]
    else:
        # Inline-Modus: Lernpfad landet direkt im Chat-Verlauf, Print-Button
        # vom Frontend angeboten (siehe `**Lernpfad:`-intrinsic marker plus
        # `boerdi:printable-canvas`-Sentinel).
        lines = [
            f"Ich habe dir den **Lernpfad zu *{topic}*** direkt unter dieser "
            f"Nachricht aufgebaut."
        ]
    if phases:
        lines.append("")
        lines.append("Er ist in diese Phasen gegliedert:")
        for i, p in enumerate(phases, 1):
            lines.append(f"{i}. **{p}**")
    lines.append("")
    if canvas_enabled:
        lines.append(
            "Du kannst ihn im Canvas drucken, als Markdown speichern oder mir "
            "sagen, was angepasst werden soll (z.B. *\"mach ihn für Klasse 5 "
            "einfacher\"* oder *\"füge einen Schritt zur Sicherung hinzu\"*)."
        )
    else:
        lines.append(
            "Du kannst ihn mit dem Druck-Button unten als PDF speichern oder "
            "mir sagen, was angepasst werden soll (z.B. *\"mach ihn für "
            "Klasse 5 einfacher\"* oder *\"füge einen Schritt zur Sicherung "
            "hinzu\"*)."
        )
    return "\n".join(lines)


async def _handle_generate_learning_path(
    req: ChatRequest, session_state: dict,
) -> ChatResponse:
    """Fetch collection contents, then LLM structures them into a learning path."""
    collection_id = req.action_params.get("collection_id", "")
    title = req.action_params.get("title", "Sammlung")

    if not collection_id:
        return ChatResponse(
            session_id=req.session_id,
            content="Keine Sammlungs-ID angegeben.",
        )

    tools_called = ["get_collection_contents"]
    lp_reset_notice = ""

    try:
        # Step 1: Fetch up to 16 items for a representative sample.
        # Use a wider window so we can deduplicate against previously used items.
        result_text = await call_mcp_tool("get_collection_contents", {
            "nodeId": collection_id,
            "maxItems": 24,
            "skipCount": 0,
        })

        cards_raw = parse_wlo_cards(result_text)
        await resolve_discipline_labels(cards_raw)
        for c in cards_raw:
            c.setdefault("node_type", "content")

        # Diversity: skip items that were already used in earlier learning paths
        used_ids = _get_used_lp_ids(session_state)
        cards_raw, was_reset = _filter_unused_cards(cards_raw, used_ids)
        if was_reset:
            lp_reset_notice = (
                "\n\n_Hinweis: Es waren keine neuen Inhalte verfügbar, "
                "deshalb wird die Auswahl jetzt wiederholt._"
            )
            session_state.setdefault("entities", {})["_lp_used_node_ids"] = "[]"
        cards_raw = cards_raw[:16]

        if not cards_raw:
            return ChatResponse(
                session_id=req.session_id,
                content=f'Leider keine Inhalte in der Sammlung "{title}" gefunden, '
                        f'aus denen ein Lernpfad erstellt werden koennte.',
                debug=DebugInfo(
                    pattern="ACTION: generate_learning_path",
                    tools_called=tools_called,
                ),
            )

        # Step 2: Generate learning path via LLM — use only the filtered subset
        tools_called.append("llm_learning_path")
        contents_text = "\n".join(
            f"- **{c.get('title','')}** ({', '.join(c.get('learning_resource_types', [])) or 'Material'})"
            f"{(' — ' + c.get('description','')[:200]) if c.get('description') else ''}"
            f"{(' URL: ' + c.get('url','')) if c.get('url') else ''}"
            for c in cards_raw
        )
        response_text = await generate_learning_path_text(
            collection_title=title,
            contents_text=contents_text[:6000],
            session_state=session_state,
        )
        if lp_reset_notice:
            response_text = (response_text or "") + lp_reset_notice

        # Mark these node_ids as used so the next LP varies (based on the
        # full candidate pool, not the post-filter subset — otherwise the
        # diversity logic never sees the unused items).
        _add_used_lp_ids(session_state, [c.get("node_id", "") for c in cards_raw])

        # Show only the items the LLM actually referenced in the path.
        cards_raw = _filter_cards_used_in_text(cards_raw, response_text)

        persona = session_state.get("persona_id", "")
        cards = _build_cards(cards_raw, persona)

    except Exception as e:
        logger.error("generate_learning_path error: %s", e)
        cards = []
        response_text = f'Fehler beim Erstellen des Lernpfads für "{title}": {e}'
        tools_called.append("error")

    # Generate quick replies (best-effort — never block a finished LP on QR).
    try:
        quick_replies = await generate_quick_replies(
            message=req.message,
            response_text=response_text,
            classification={
                "persona_id": session_state.get("persona_id", "P-AND"),
                "intent_id": "INT-W-10",
                "next_state": "state-6",
                "entities": session_state.get("entities", {}),
            },
            session_state=session_state,
        )
    except Exception as _qr_err:
        logger.warning("learning_path quick_replies failed: %s", _qr_err)
        quick_replies = []
    quick_replies = _attach_guide_qr(req, quick_replies, session_state, response_text=response_text)

    debug = DebugInfo(
        persona=session_state.get("persona_id", ""),
        intent="INT-W-10",
        state="state-6",
        pattern="ACTION: generate_learning_path",
        tools_called=tools_called,
        entities=session_state.get("entities", {}),
    )

    await save_message(
        req.session_id, "assistant", response_text,
        cards=[c.model_dump() for c in cards],
        debug=debug.model_dump(),
    )
    # Route the LP into the canvas (material pane) and hand the selected
    # cards as an optional second pane the user can flip to via the tab
    # switch in the canvas header. The chat bubble keeps only a short
    # announcement — the full learning-path markdown lives in the canvas
    # and can be printed / downloaded / edited there.
    _lp_title = f"Lernpfad: {title}" if title else "Lernpfad"
    _m = _re_lp_title.search((response_text or "").lstrip().splitlines()[0] if response_text else "")
    if _m:
        _lp_title = _m.group(1).strip() or _lp_title

    # Switch session into canvas-edit mode so follow-up messages can be
    # treated as refinements ("mach ihn fuer Klasse 5 einfacher").
    session_state["state_id"] = "state-12"
    session_state.setdefault("entities", {})["_canvas_material_type"] = "lernpfad"
    session_state["entities"]["_canvas_topic"] = title or ""
    await update_session(
        req.session_id,
        state_id="state-12",
        entities=json.dumps(session_state.get("entities", {})),
    )

    # If the LP step failed inside the try/except above, response_text
    # is the user-facing error string (no markdown headings) — fall back
    # to a plain chat bubble in that case instead of pretending we built
    # a canvas document.
    _lp_failed = (response_text or "").startswith("Fehler beim Erstellen des Lernpfads")
    if _lp_failed:
        _attach_guide_urls(req, cards, None)
        return ChatResponse(
            session_id=req.session_id,
            content=response_text,
            cards=cards,
            quick_replies=quick_replies,
            debug=debug,
        )

    # Im Inline-Modus (canvas-enabled="false") wird der Lernpfad direkt im
    # Chat-Verlauf gerendert — Prosa muss das spiegeln, nicht „im Canvas
    # rechts" sagen. _widget_modes() schaut auf req.environment.
    _canvas_on = _widget_modes(req)["canvas_enabled"]
    short_ack = _lp_completion_message(title, response_text or "", canvas_enabled=_canvas_on)

    _attach_guide_urls(req, cards, None)

    return ChatResponse(
        session_id=req.session_id,
        content=short_ack,
        cards=cards,
        quick_replies=quick_replies,
        debug=debug,
        page_action={
            "action": "canvas_open",
            "payload": {
                "title": _lp_title,
                "material_type": "lernpfad",
                "material_type_label": "🗺️ Lernpfad",
                "markdown": response_text or "",
            },
        },
    )


# ── Canvas action handlers ───────────────────────────────────────
async def _handle_canvas_create(
    req: ChatRequest, session_state: dict,
) -> ChatResponse:
    """Create a new canvas document from explicit action parameters.

    Triggered from the widget when the user clicks a material-type chip or
    otherwise sends a structured create request. Returns a short chat text
    and a `canvas_open` page_action with the full markdown.
    """
    topic = (req.action_params.get("topic") or "").strip()
    raw_type = req.action_params.get("material_type") or ""
    type_key = resolve_material_type(raw_type) or "auto"

    if not topic:
        return ChatResponse(
            session_id=req.session_id,
            content="Bitte nenne mir ein Thema für den Inhalt.",
        )

    memories = await get_memory(req.session_id)
    memory_context = "\n".join(f"- {m['key']}: {m['value']}" for m in (memories or [])[:10])

    _mts = get_material_types()
    label = _mts[type_key]["label"]
    emoji = _mts[type_key]["emoji"]

    try:
        title, markdown = await generate_canvas_content(
            topic=topic,
            material_type_key=type_key,
            session_state=session_state,
            memory_context=memory_context,
        )
    except Exception as e:
        # Don't propagate to a 500 — degrade to a friendly chat message so the
        # user sees what went wrong (e.g. transient B-API/LLM rate-limit) and
        # can retry. Without this, the frontend's generic catch-all swallows
        # the error and just says "konnte ich leider nicht erstellen".
        logger.error("canvas_create generation failed: %s", e)
        err_debug = DebugInfo(
            persona=session_state.get("persona_id", ""),
            intent="INT-W-11",
            state="state-12",
            pattern="ACTION: canvas_create_error",
            tools_called=["canvas_service.generate_canvas_content", "error"],
            entities=session_state.get("entities", {}),
        )
        msg = (
            f"Ich konnte das **{label}** zum Thema *{topic}* gerade nicht "
            f"erstellen ({type(e).__name__}). Versuch es nochmal — meistens "
            "klappt es beim zweiten Anlauf."
        )
        await save_message(req.session_id, "assistant", msg,
                           debug=err_debug.model_dump())
        return ChatResponse(
            session_id=req.session_id,
            content=msg,
            quick_replies=["Nochmal versuchen", "Anderes Material"],
            debug=err_debug,
        )

    _canvas_on_mat = _widget_modes(req)["canvas_enabled"]
    response_text = _canvas_completion_message(
        label, topic, markdown, canvas_enabled=_canvas_on_mat,
    )

    debug = DebugInfo(
        persona=session_state.get("persona_id", ""),
        intent="INT-W-11",
        state="state-12",
        pattern="ACTION: canvas_create",
        tools_called=["canvas_service.generate_canvas_content"],
        entities=session_state.get("entities", {}),
    )

    # Mark canvas state in session so follow-up edits know they're in canvas mode
    session_state["state_id"] = "state-12"
    session_state.setdefault("entities", {})["_canvas_material_type"] = type_key
    session_state["entities"]["_canvas_topic"] = topic
    # Store the last canvas markdown so text-based follow-up edits
    # ("mach es einfacher") can pick it up without the frontend resending it.
    session_state["entities"]["_canvas_last_markdown"] = markdown

    await save_message(
        req.session_id, "assistant", response_text,
        debug=debug.model_dump(),
    )
    await update_session(
        req.session_id,
        state_id="state-12",
        entities=json.dumps(session_state["entities"]),
    )

    return ChatResponse(
        session_id=req.session_id,
        content=response_text,
        quick_replies=[
            "Mach es einfacher",
            "Füge Lösungen hinzu",
            "Mehr Übungen",
            "Kürzer fassen",
        ],
        debug=debug,
        page_action={
            "action": "canvas_open",
            "payload": {
                "title": title,
                "material_type": type_key,
                "material_type_label": f"{emoji} {label}",
                "material_type_category": get_material_type_category(type_key),
                "markdown": markdown,
            },
        },
    )


async def _handle_canvas_remix(
    req: ChatRequest, session_state: dict,
) -> ChatResponse:
    """Remix an existing WLO resource into a new material of the same type.

    action_params:
      - title       (str)   — original resource title, also used as topic
      - url         (str)   — page URL for full-text extraction (optional)
      - description (str)
      - keywords    (list[str])
      - disciplines (list[str])
      - educational_contexts (list[str])
      - learning_resource_types (list[str])  — used to pick the target type
      - publisher   (str)
      - license     (str)
      - material_type_override (str, optional) — force a specific canvas type
    """
    p = req.action_params or {}
    topic = (p.get("title") or p.get("topic") or "").strip()
    if not topic:
        return ChatResponse(
            session_id=req.session_id,
            content="Kein Titel für den Remix angegeben.",
        )

    # Decide on the target material type
    mt_override = (p.get("material_type_override") or "").strip()
    mt_key = resolve_material_type(mt_override) if mt_override else None
    if not mt_key:
        mt_key = infer_material_type_from_lrt(p.get("learning_resource_types") or [])
    if not mt_key:
        mt_key = "auto"
    _mts = get_material_types()
    label = _mts[mt_key]["label"]
    emoji = _mts[mt_key]["emoji"]

    # Try to grab the page's full text. Failures are fine — the LLM still
    # has metadata to work with.
    url = (p.get("url") or "").strip()
    extracted_text = ""
    extraction_ok = False
    if url:
        try:
            ex = await extract_text_from_url(url, max_chars=4000)
            if ex and ex.get("text"):
                extracted_text = ex["text"]
                extraction_ok = True
                logger.info(
                    "remix: extracted %s chars from %s (original %s)",
                    ex.get("cleaned_length"), url, ex.get("original_length"),
                )
        except Exception as e:
            logger.info("remix: text extraction failed: %s", e)

    source_meta = {
        "title": p.get("title") or "",
        "description": p.get("description") or "",
        "disciplines": p.get("disciplines") or [],
        "educational_contexts": p.get("educational_contexts") or [],
        "keywords": p.get("keywords") or [],
        "publisher": p.get("publisher") or "",
        "license": p.get("license") or "",
        "url": url,
    }

    memories = await get_memory(req.session_id)
    memory_context = "\n".join(f"- {m['key']}: {m['value']}" for m in (memories or [])[:10])

    try:
        title_out, md = await generate_canvas_remix(
            topic=topic,
            material_type_key=mt_key,
            source_meta=source_meta,
            source_text=extracted_text,
            session_state=session_state,
            memory_context=memory_context,
        )
    except Exception as e:
        # Same hardening as in _handle_canvas_create — graceful chat-bubble
        # instead of a 500 when the LLM/B-API blips.
        logger.error("canvas_remix generation failed: %s", e)
        err_debug = DebugInfo(
            persona=session_state.get("persona_id", ""),
            intent="INT-W-11",
            state="state-12",
            pattern="ACTION: canvas_remix_error",
            tools_called=["canvas_service.generate_canvas_remix", "error"],
            entities=session_state.get("entities", {}),
        )
        msg = (
            f"Den Remix als **{label}** zu *{topic}* konnte ich gerade nicht "
            f"erstellen ({type(e).__name__}). Versuch es nochmal — meistens "
            "klappt es beim zweiten Anlauf."
        )
        await save_message(req.session_id, "assistant", msg,
                           debug=err_debug.model_dump())
        return ChatResponse(
            session_id=req.session_id,
            content=msg,
            quick_replies=["Nochmal versuchen", "Anderes Material"],
            debug=err_debug,
        )

    short_note = "" if extraction_ok else " *(Volltext war nicht abrufbar — Remix basiert auf Metadaten.)*"
    _canvas_on_remix = _widget_modes(req)["canvas_enabled"]
    if _canvas_on_remix:
        response_text = (
            f"Ich habe dir einen **Remix als {label}** zum Thema *{topic}* im Canvas "
            f"erstellt.{short_note} Sag mir einfach, was ich anpassen soll "
            "(z.B. *\"mach es einfacher\"* oder *\"füge Lösungen hinzu\"*)."
        )
    else:
        response_text = (
            f"Ich habe dir einen **Remix als {label}** zum Thema *{topic}* erstellt — "
            f"er steht direkt unter dieser Nachricht.{short_note} Den Druck-Button "
            f"findest du am Ende des Materials. Sag mir einfach, was ich anpassen "
            f"soll (z.B. *\"mach es einfacher\"* oder *\"füge Lösungen hinzu\"*)."
        )

    debug = DebugInfo(
        persona=session_state.get("persona_id", ""),
        intent="INT-W-11",
        state="state-12",
        pattern="ACTION: canvas_remix",
        tools_called=[
            "canvas_service.generate_canvas_remix",
            *(["text_extraction_service"] if extraction_ok else []),
        ],
        entities=session_state.get("entities", {}),
    )

    session_state["state_id"] = "state-12"
    session_state.setdefault("entities", {})["_canvas_material_type"] = mt_key
    session_state["entities"]["_canvas_topic"] = topic
    # Store fresh markdown so follow-up edits ("mach es einfacher") operate
    # on THIS remix, not on a stale prior canvas.
    session_state["entities"]["_canvas_last_markdown"] = md

    await save_message(
        req.session_id, "assistant", response_text,
        debug=debug.model_dump(),
    )
    await update_session(
        req.session_id,
        state_id="state-12",
        entities=json.dumps(session_state["entities"]),
    )

    return ChatResponse(
        session_id=req.session_id,
        content=response_text,
        quick_replies=[
            "Mach es einfacher",
            "Füge Lösungen hinzu",
            "Mehr Übungen",
            "Kürzer fassen",
        ],
        debug=debug,
        page_action={
            "action": "canvas_open",
            "payload": {
                "title": title_out,
                "material_type": mt_key,
                "material_type_label": f"{emoji} {label} (Remix)",
                "material_type_category": get_material_type_category(mt_key),
                "markdown": md,
            },
        },
    )


async def _handle_canvas_edit(
    req: ChatRequest, session_state: dict,
) -> ChatResponse:
    """Apply a chat-originated edit instruction to existing canvas markdown."""
    current_md = req.action_params.get("current_markdown", "")
    instruction = (req.action_params.get("edit_instruction") or req.message or "").strip()

    if not current_md:
        return ChatResponse(
            session_id=req.session_id,
            content="Kein Canvas-Inhalt uebergeben. Bitte erstelle zuerst ein Material.",
        )
    if not instruction:
        return ChatResponse(
            session_id=req.session_id,
            content="Welche Aenderung soll ich am Canvas-Inhalt vornehmen?",
        )

    # Import here to avoid circular dep at module load time
    from app.services.canvas_service import CanvasEditRefused
    try:
        new_md = await edit_canvas_content(
            current_markdown=current_md,
            edit_instruction=instruction,
            session_state=session_state,
        )
    except CanvasEditRefused as e:
        # Moderation flagged the edit — return a polite refusal without
        # running the LLM. UX: user sees the reason, Canvas stays as-is.
        refusal_debug = DebugInfo(
            persona=session_state.get("persona_id", ""),
            intent="INT-W-12",
            state="state-12",
            pattern="ACTION: canvas_edit_refused",
            tools_called=["canvas_service._moderate_canvas_edit"],
            entities=session_state.get("entities", {}),
        )
        await save_message(
            req.session_id, "assistant", str(e),
            debug=refusal_debug.model_dump(),
        )
        return ChatResponse(
            session_id=req.session_id,
            content=str(e),
            debug=refusal_debug,
        )
    except Exception as e:
        # Any other LLM/B-API failure (rate-limit, network, bad JSON, …) —
        # return a friendly chat bubble instead of a 500. The canvas content
        # in the widget stays as-is, so the user can simply retry.
        logger.error("canvas_edit generation failed: %s", e)
        err_debug = DebugInfo(
            persona=session_state.get("persona_id", ""),
            intent="INT-W-12",
            state="state-12",
            pattern="ACTION: canvas_edit_error",
            tools_called=["canvas_service.edit_canvas_content", "error"],
            entities=session_state.get("entities", {}),
        )
        msg = (
            f"Die Änderung konnte ich gerade nicht anwenden ({type(e).__name__}). "
            "Der bisherige Canvas-Inhalt bleibt unverändert. Versuch es nochmal — "
            "meistens klappt es beim zweiten Anlauf."
        )
        await save_message(req.session_id, "assistant", msg,
                           debug=err_debug.model_dump())
        return ChatResponse(
            session_id=req.session_id,
            content=msg,
            quick_replies=["Nochmal versuchen", "Einfacher schreiben"],
            debug=err_debug,
        )

    response_text = (
        "Erledigt. Der Canvas-Inhalt ist jetzt angepasst. "
        "Sag mir, falls ich noch etwas ändern soll."
    )

    debug = DebugInfo(
        persona=session_state.get("persona_id", ""),
        intent="INT-W-12",
        state="state-12",
        pattern="ACTION: canvas_edit",
        tools_called=["canvas_service.edit_canvas_content"],
        entities=session_state.get("entities", {}),
    )

    # Persist the new markdown so subsequent text-based edits
    # ("nochmal kürzer") can pick it up without frontend passing it.
    session_state.setdefault("entities", {})["_canvas_last_markdown"] = new_md
    await update_session(
        req.session_id,
        entities=json.dumps(session_state["entities"]),
    )

    await save_message(
        req.session_id, "assistant", response_text,
        debug=debug.model_dump(),
    )

    return ChatResponse(
        session_id=req.session_id,
        content=response_text,
        quick_replies=[
            "Noch einfacher",
            "Mehr Beispiele",
            "Zurück zum Original",
            "Als Arbeitsblatt umwandeln",
        ],
        debug=debug,
        page_action={
            "action": "canvas_update",
            "payload": {"markdown": new_md},
        },
    )


# ── Main chat endpoint ───────────────────────────────────────────
_LLM_DELIVERY_CLAIM_RE = _re.compile(
    r"\b("
    r"hab(?:e)?\s+dir|hab\s+rausgefischt|hab(?:e)?\s+gefunden|"
    r"rausgefischt|rausgezogen|rausgesucht|rausgelegt|rausgepickt|"
    r"hier\s+sind\s+(?:die\s+)?(?:passende|treffer)|"
    r"hab\s+direkt\s+(?:was|ein)|"
    r"passende\s+(?:sammlung|themenseite|treffer|material|inhalte)|"
    r"kuratierte?\s+(?:sammlung|auswahl|treffer)|"
    r"hab\s+dir\s+was\s+passend|"
    r"hab\s+ein\s+paar\s+passend|"
    r"schau\s+(?:dir|mal)|zeig\s+(?:dir|ich)"
    r")\b",
    _re.IGNORECASE,
)


def _looks_like_search_query(message: str) -> bool:
    """Heuristik: wirkt der User-Input wie eine konkrete Suchanfrage?

    Greift wenn die Nachricht substantiellen Inhalt hat (>= 5 Zeichen Text
    nach Whitespace) und nicht offensichtlich eine Klärungs- oder
    Meta-Frage ist (z.B. ``"was kannst du?"`` triggert nicht).
    """
    msg = (message or "").strip()
    if len(msg) < 5:
        return False
    low = msg.lower()
    # Generic meta/clarification phrases that aren't real searches.
    # Diese matchen unabhängig von der Länge: "Was ist WirLernenOnline?"
    # (24 chars) und "Was ist WLO?" (12 chars) sind beide reine
    # Definition-Fragen, kein Suchanker. Welle C Sprint 6 Hotfix:
    # vorher hatte die Liste nur kurze Phrasen + 25-Zeichen-Limit, was
    # "Was ist WirLernenOnline?" als Suche durchwischen liess —
    # Safety-Net Fallback-Search hat dann eine MCP-Suche darüber
    # ausgelöst und Cards in eine RAG-Antwort geschmuggelt.
    no_search_phrases_exact = (
        "was ist wlo",
        "was ist wirlernenonline",
        "was ist wir lernen online",
        "wer steckt hinter wlo",
        "wer steckt hinter wirlernenonline",
        "was ist oer",
        "was ist edu-sharing",
        "was ist eine themenseite",
        "was ist eine sammlung",
        "was bedeutet oer",
    )
    if any(p in low for p in no_search_phrases_exact):
        return False
    # Kurze Meta-/Greeting-Phrasen (mit Längenlimit, sonst false-positive
    # bei Sätzen wie "Hi, kannst du mir helfen mit Mathe?")
    no_search_phrases_short = (
        "was kannst du", "wie kann ich", "hilfe", "help",
        "hallo", "hi ", "moin", "guten tag",
    )
    if any(p in low for p in no_search_phrases_short) and len(low) < 25:
        return False
    return True


async def _fallback_inline_search(message: str, classification_entities: dict) -> list[Any]:
    """Kompakter Fallback-Search wenn der LLM eine Liefer-Aussage gemacht
    hat aber keine Cards in der Response sind (Inline-Mode-Bug).

    Strategie: ``search_wlo_content`` mit dem User-Message als ``query``,
    plus optional ``discipline``/``educationalContext`` aus den
    klassifizierten Entities — damit der Treffer thematisch passt.
    Maximal 5 Treffer (passt zum Inline-Limit). Bei Fehlern leere Liste,
    NIEMALS exception nach außen.
    """
    try:
        from app.services.mcp_client import call_mcp_tool as _ct
        from app.services.mcp_client import parse_wlo_cards as _pc
        args: dict[str, Any] = {"query": message, "maxResults": 5}
        # Optional Filter aus den klassifizierten Entities übernehmen
        fach = classification_entities.get("fach") if isinstance(classification_entities, dict) else None
        stufe = classification_entities.get("stufe") if isinstance(classification_entities, dict) else None
        if isinstance(fach, str) and fach.strip():
            args["discipline"] = fach.strip()
        if isinstance(stufe, str) and stufe.strip():
            args["educationalContext"] = stufe.strip()
        raw = await _ct("search_wlo_content", args)
        if not raw:
            logger.info("fallback inline search: leer für query='%s'", message[:60])
            return []
        cards = _pc(raw)
        logger.info(
            "fallback inline search: %d Cards für query='%s'",
            len(cards or []), message[:60],
        )
        return cards or []
    except Exception as _e:
        # WICHTIG: warning statt debug, damit Import-/MCP-Fehler nicht
        # stillschweigend Fallback + Auto-Augmentation lahmlegen.
        logger.warning("fallback inline search failed: %s", _e)
        return []


async def _postprocess_response_for_widget_modes(
    req: ChatRequest, resp: ChatResponse,
    classification_entities: dict | None = None,
) -> ChatResponse:
    """Wrap response through widget-modes postprocess.

    Greift NACH ``_chat_impl`` und allen ``_handle_*``-Action-Handlern,
    damit auch direct-action-Responses (Canvas-Create, Lernpfad usw.)
    die Display-Flags des Hosts berücksichtigen.

    Idempotent: wenn alle Modes default sind (Pydantic-None → True),
    ist das ein No-Op. Bei einem Bestand-Frontend ohne neue Flags
    bleibt das Verhalten 1:1 wie vorher.

    **Inline-Mode-Safety-Net**: wenn ``cards_enabled=false`` UND die Cards
    der Response leer sind UND der LLM-Antworttext eine Liefer-Aussage
    enthält („hab dir rausgefischt", „hier sind die Treffer", …), startet
    das Backend einen Fallback-``search_wlo_content``-Aufruf mit der
    User-Frage als Query. So sieht der User die versprochenen Treffer auch
    dann, wenn der LLM-Tool-Loop sie aus irgendeinem Grund nicht
    durchgereicht hat (typisches Symptom: bot sagt „ich habe gefunden"
    aber keine Inline-Links erscheinen).
    """
    try:
        modes = _widget_modes(req)
        env = req.environment
        guide_mode_on = bool(getattr(env, "guide_mode", False))

        # Vom LLM (via select_top_cards-Tool) gewählte IDs aus debug holen.
        # _chat_impl stasht sie in phase3_modulations.selected_card_ids.
        # Bei direct-action-Handlern (Canvas-Create etc.) ist die Liste leer
        # und wir fallen auf algorithmische Sortierung zurück — kein Bruch.
        selected_card_ids: list[str] = []
        try:
            dbg = resp.debug
            if dbg is not None:
                p3 = getattr(dbg, "phase3_modulations", None) or {}
                raw_ids = p3.get("selected_card_ids") or []
                if isinstance(raw_ids, list):
                    selected_card_ids = [str(x) for x in raw_ids if isinstance(x, str) and x.strip()]
        except Exception:
            selected_card_ids = []

        cards_for_postprocess: list[Any] = list(resp.cards or [])

        # ── Universal Medientyp-Filter (Welle C Sprint 6 Hotfix) ──────
        #
        # Bei expliziter medientyp-Vorgabe ("nur Videos", "nur Audio",
        # ``entities.medientyp=Video`` aus dem Classifier oder aus vorigen
        # Turns) raus mit Sammlungen + Themenseiten + Cards anderen
        # Typs — modus-agnostisch (also auch im Kacheln-Mode mit
        # ``cards_enabled=true``, nicht nur Inline).
        #
        # WICHTIG: ``session_state`` und ``classification`` sind im Scope
        # dieser Funktion NICHT verfügbar (nur ``req`` + ``resp`` werden
        # übergeben — Wrapper-Pattern für die Postprocess). Wir lesen die
        # finalen entities deshalb aus ``resp.debug.entities`` ab; die
        # Engine hat sie dort hingelegt, inkl. session-akkumulierter Slots.
        _debug_entities: dict[str, Any] = {}
        try:
            _dbg_obj = resp.debug
            if _dbg_obj is not None:
                _dbg_ents = getattr(_dbg_obj, "entities", None)
                if isinstance(_dbg_ents, dict):
                    _debug_entities = {
                        k: v for k, v in _dbg_ents.items()
                        if not str(k).startswith("_")
                    }
        except Exception:
            _debug_entities = {}
        _universal_wanted = _resolve_wanted_content_types(
            req.message or "",
            session_entities=_debug_entities,
            classification_entities=classification_entities,
        )
        if _universal_wanted and cards_for_postprocess:
            _before = len(cards_for_postprocess)
            cards_for_postprocess = [
                c for c in cards_for_postprocess
                if (
                    (c.get("node_type") if isinstance(c, dict)
                     else getattr(c, "node_type", None)) == "content"
                    and _card_matches_wanted_types(c, _universal_wanted)
                )
            ]
            if _before != len(cards_for_postprocess):
                logger.info(
                    "universal type-filter: %d → %d cards (medientyp=%s)",
                    _before, len(cards_for_postprocess), sorted(_universal_wanted),
                )

        # Safety-Net: bei Liefer-Aussage + Suchanfrage, aber KEINE Cards in
        # der Response (oder LLM-IDs matchen 0 Cards = Selection-Collapse).
        # Klassischer LLM-Bug: Modell behauptet etwas geliefert zu haben
        # ohne Tools gerufen zu haben (oder mit falschen IDs).
        #
        # Greift MODUS-AGNOSTISCH — vorher war's auf ``cards_enabled=false``
        # (Inline-Modus) beschränkt, dann war der Kacheln-/Canvas-Modus
        # ungeschützt: bei Liefer-Behauptung ohne Tools sah der User „habe
        # dir was gezogen" aber leere Kacheln-Lane. Lotsen-Modus verstärkte
        # das, weil dort die Lotsen-Inline-Links als Ersatz-Anker greifen.
        # Selection-Collapse bleibt Inline-spezifisch (im Kacheln-Modus
        # filtert das Frontend nicht nach IDs, alle Cards werden gezeigt).
        _claim = _LLM_DELIVERY_CLAIM_RE.search(resp.content or "")
        _query_like = _looks_like_search_query(req.message or "")
        _selection_collapses = (
            (not modes["cards_enabled"])  # nur im Inline-Pfad relevant
            and bool(selected_card_ids)
            and bool(cards_for_postprocess)
            and not any(
                (c.get("node_id") if isinstance(c, dict) else getattr(c, "node_id", None))
                in set(selected_card_ids)
                for c in cards_for_postprocess
            )
        )
        # Welle C Sprint 6 Hotfix — Pattern-Gate gegen RAG-only Patterns.
        # Wenn das aktive Pattern explizit ``tools=[]`` oder eine reine
        # RAG-Source-Konfig hat (PAT-20 Orientierungs-Guide, PAT-10
        # Fakten-Bulletin in Pure-RAG-Mode), darf das Safety-Net KEINE
        # MCP-Fallback-Search auslösen. User-Bug: "Was ist WirLernenOnline?"
        # → PAT-20 (RAG-only) → LLM-Antwort enthält "zeig ich dir direkt"
        # → Delivery-Claim matched → Fallback-Search wirft 5 Content-Cards
        # in eine Definition-Antwort, die gar keine Cards haben sollte.
        _is_rag_only_pattern = False
        try:
            _dbg_obj = resp.debug
            if _dbg_obj is not None:
                _p3 = getattr(_dbg_obj, "phase3_modulations", None) or {}
                _src = _p3.get("sources") or []
                _tools = _p3.get("tools") or []
                # Reine RAG: sources enthält 'rag' UND keine MCP-Tools
                # Pure no-tools: explizit leere Tool-Liste (PAT-20)
                if isinstance(_tools, list) and len(_tools) == 0:
                    _is_rag_only_pattern = True
                elif (
                    isinstance(_src, list)
                    and "rag" in _src
                    and "mcp" not in _src
                ):
                    _is_rag_only_pattern = True
        except Exception:
            _is_rag_only_pattern = False
        if _is_rag_only_pattern and not cards_for_postprocess:
            # Bewusster Skip — RAG-Pattern liefert per Definition keine
            # Cards. Wenn der LLM "zeig ich dir direkt" o.ä. sagt, ist das
            # ein Conversation-Hook, kein Liefer-Statement.
            logger.info(
                "safety-net skipped: RAG-only pattern (tools=%s, sources=%s) for msg=%r",
                _tools, _src, (req.message or "")[:60],
            )
            _claim = None  # Safety-Net unten greift damit nicht
        if (
            _claim
            and _query_like
            and (not cards_for_postprocess or _selection_collapses)
        ):
            _mode_label = "inline" if not modes["cards_enabled"] else "kacheln"
            logger.info(
                "safety-net (%s): %s — Fallback-Search auf '%s'",
                _mode_label,
                "leere Cards" if not cards_for_postprocess else "LLM-IDs matchen 0 Cards",
                (req.message or "")[:60],
            )
            fb_cards = await _fallback_inline_search(
                req.message or "",
                classification_entities or {},
            )
            if fb_cards:
                logger.info("safety-net (%s): %d Cards aus Fallback",
                            _mode_label, len(fb_cards))
                cards_for_postprocess = fb_cards
                # Fallback-Cards haben frische IDs, die LLM-Auswahl ist
                # ungültig dafür — sonst würde der Filter wieder auf 0
                # zusammenklappen. Algorithmische Sortierung übernimmt.
                selected_card_ids = []

        # ── Auto-Augmentation v2: wenn LLM nur 1-2 Sammlungen/Themenseiten
        # gepickt hat, automatisch Einzelinhalte dazuholen, damit der User
        # bis zu 5 Optionen sieht. Deterministisch im Backend, statt den
        # LLM mit Mix-Logik zu belasten (zu komplex/inkonsistent).
        # Trigger:
        #   - Inline-Modus aktiv
        #   - LLM hat explizit IDs gewählt (kein Fallback-Pfad)
        #   - Selection ist < 5
        #   - ALLE gewählten Cards sind collection (Sammlung oder Themenseite)
        # Dann: search_wlo_content auf User-Frage, bis zu (5 - selection)
        # Einzelinhalte anhängen, IDs dedupen.
        if (
            not modes["cards_enabled"]
            and selected_card_ids
            and cards_for_postprocess
            and not _selection_collapses  # nur wenn die LLM-Auswahl gültig ist
        ):
            _user_msg = req.message or ""
            # session_state nicht im Scope — debug.entities ist der Snapshot.
            _wanted_types = _resolve_wanted_content_types(
                _user_msg,
                session_entities=_debug_entities,
                classification_entities=classification_entities,
            )
            _wants_specific_type = bool(_wanted_types)

            # Type-Fokus-Strict-Filter: bei „Nur Videos zu X" wählt der LLM
            # trotz Prompt-Hinweis regelmäßig auch Sammlungen oder andere
            # Typen mit (`reasoning: Zwei Videos zuerst, danach zwei Samm-
            # lungen`). Backend-seitig hier hart filtern — nur Cards mit
            # matching ``learning_resource_types`` bleiben in der Auswahl.
            # Augmentation füllt danach mit weiteren matching-Cards auf.
            if _wants_specific_type:
                _strict_ids = set()
                for _i in selected_card_ids:
                    _c = next(
                        (c for c in cards_for_postprocess
                         if (c.get("node_id") if isinstance(c, dict)
                             else getattr(c, "node_id", None)) == _i),
                        None,
                    )
                    if _c is not None and _card_matches_wanted_types(_c, _wanted_types):
                        _strict_ids.add(_i)
                if _strict_ids:
                    _before = len(selected_card_ids)
                    selected_card_ids = [i for i in selected_card_ids if i in _strict_ids]
                    if _before != len(selected_card_ids):
                        logger.info(
                            "inline-mode type-strict filter: %d → %d IDs "
                            "(Typ: %s)",
                            _before, len(selected_card_ids),
                            sorted(_wanted_types),
                        )

            _selected_set = set(selected_card_ids)
            _picked = [
                c for c in cards_for_postprocess
                if (c.get("node_id") if isinstance(c, dict)
                    else getattr(c, "node_id", None)) in _selected_set
            ]
            # Augmentations-Bedingung: LLM hat weniger als 5 gepickt UND
            # der In-Memory-Pool enthält noch ungenutzte Einzelinhalte.
            #
            # Vorher: bei Typ-Fokus ("nur Videos") wurde Augmentation komplett
            # übersprungen — das führte zu 1-Treffer-Antworten, obwohl 5+
            # Videos im Pool waren. Jetzt: bei Typ-Fokus läuft Augmentation,
            # filtert aber strikt auf die gewünschten ``learning_resource_types``,
            # damit nur Cards des angefragten Typs angehängt werden (kein
            # Audio zwischen Videos).
            _has_extra_content_in_pool = any(
                (c.get("node_type") if isinstance(c, dict)
                 else getattr(c, "node_type", None)) != "collection"
                and (c.get("node_id") if isinstance(c, dict)
                     else getattr(c, "node_id", None)) not in _selected_set
                and _card_matches_wanted_types(c, _wanted_types)
                for c in cards_for_postprocess
            )
            if (
                _picked
                and len(_picked) < 5
                and _has_extra_content_in_pool
            ):
                _needed = 5 - len(_picked)
                logger.info(
                    "inline-mode auto-augment: %d gepickt (LLM), "
                    "ergänze bis zu %d Einzelinhalte aus Pool für '%s'",
                    len(_picked), _needed, _user_msg[:60],
                )
                _existing_ids = {
                    (c.get("node_id") if isinstance(c, dict)
                     else getattr(c, "node_id", None))
                    for c in _picked
                }
                # SCHRITT 1: Bereits geladene Einzelinhalte aus
                # cards_for_postprocess nehmen (durch speculative extra-spec
                # parallel zum primary tool oft schon vorhanden). Spart MCP-
                # Round-Trip + ist konsistent mit der Card-Reihenfolge die
                # der LLM gesehen hat.
                _added = 0
                for _c in cards_for_postprocess:
                    if _added >= _needed:
                        break
                    _nid = (_c.get("node_id") if isinstance(_c, dict)
                            else getattr(_c, "node_id", None))
                    _ntype = (_c.get("node_type") if isinstance(_c, dict)
                              else getattr(_c, "node_type", None))
                    if not _nid or _nid in _existing_ids or _ntype == "collection":
                        continue
                    # Bei Typ-Fokus ("nur Videos") nur Cards des gewünschten
                    # Typs anhängen — sonst landet ein Audio zwischen Videos.
                    if not _card_matches_wanted_types(_c, _wanted_types):
                        continue
                    selected_card_ids.append(_nid)
                    _existing_ids.add(_nid)
                    _added += 1
                logger.info(
                    "inline-mode auto-augment: %d Einzelinhalte aus "
                    "vorhandenen Cards ergänzt%s",
                    _added,
                    f" (Typ-Filter: {sorted(_wanted_types)})" if _wanted_types else "",
                )
                # SCHRITT 2: Reicht der In-Memory-Pool noch nicht? Fallback
                # auf frischen search_wlo_content-Call.
                if _added < _needed:
                    try:
                        _extra = await _fallback_inline_search(
                            _user_msg, classification_entities or {},
                        )
                    except Exception as _aug_err:
                        logger.warning("auto-augment fallback failed: %s", _aug_err)
                        _extra = []
                    for _c in _extra:
                        if _added >= _needed:
                            break
                        _nid = (_c.get("node_id") if isinstance(_c, dict)
                                else getattr(_c, "node_id", None))
                        _ntype = (_c.get("node_type") if isinstance(_c, dict)
                                  else getattr(_c, "node_type", None))
                        if not _nid or _nid in _existing_ids or _ntype == "collection":
                            continue
                        if not _card_matches_wanted_types(_c, _wanted_types):
                            continue
                        cards_for_postprocess.append(_c)
                        selected_card_ids.append(_nid)
                        _existing_ids.add(_nid)
                        _added += 1
                    if _extra:
                        logger.info(
                            "inline-mode auto-augment: nach Fallback insgesamt "
                            "%d Einzelinhalte ergänzt",
                            _added,
                        )

        # ── Lotsen-URL-Rewrite VOR v2 Curation ────────────────────────
        # MUSS vor ``run_pipeline_v2`` laufen, weil v2 intern
        # ``annotate_cards_with_link`` aufruft und dabei ``card.url``
        # von der externen Provider-URL auf die Repo-Render-URL
        # überschreibt. Danach wäre die ``{external→repo}``-Map leer
        # und der LLM-Text behielte die externen URLs.
        if guide_mode_on and resp.content and cards_for_postprocess:
            try:
                _rewritten_text = _rewrite_external_urls_to_repo(
                    resp.content, cards_for_postprocess, guide_mode_on,
                )
                if _rewritten_text != resp.content:
                    resp = resp.model_copy(update={"content": _rewritten_text})
            except Exception as _rw_err:
                logger.debug("pre-v2 response_text URL rewrite skipped: %s", _rw_err)

        # ── Option C v2 — Curation-Layer auf v1-Cards ────────────────
        # Wenn ``CARD_PIPELINE_V2=1`` aktiv UND keine direct-action UND
        # v1 hat Cards beschafft: v2 läuft als reine Curation-Schicht auf
        # v1's Pool — keine eigenen MCP-Calls. Das spart Latenz, vermeidet
        # Pool-Divergenz und greift LLM-Re-Rank konsistent.
        #
        # Aktivierungsbedingungen (alle müssen erfüllt sein):
        #   1. ``CARD_PIPELINE_V2`` aktiv
        #   2. Keine direct-action (LP, Canvas, browse-collection bauen
        #      Cards selbst und kuratieren nicht)
        #   3. v1 hat Cards beschafft (sonst ist's ein Klärungs-Turn —
        #      v2 darf da keine Cards reinhalluzinieren)
        #
        # Was v2 macht:
        #   * normalize_cards: Host-Rewrite + node_type + Dedup
        #   * select_final_cards: Mix + Relevance-Filter + LLM-Re-Rank
        #   * annotate_cards_with_link: link-Feld setzen
        #
        # Phase 10 wird v2 zur Default-Beschaffung machen — bis dahin ist
        # v1's Pool die Eingabe für v2 (gleiche Pool-Größe, gleiche IDs).
        _is_direct_action = bool((getattr(req, "action", "") or "").strip())
        if (
            card_pipeline_v2_enabled()
            and not _is_direct_action
            and cards_for_postprocess  # v1 hat Cards → v2 läuft als Curation
        ):
            try:
                from app.services.card_pipeline import (
                    run_pipeline_v2 as _v2_run,
                    summarize_pipeline_result as _v2_summary,
                )
                # Welle C Sprint 6 Hotfix — Filter-Persistenz via Resolver.
                # Vorher: ``_wanted_types`` wurde NUR aus der aktuellen
                # User-Nachricht ermittelt. Folge: "nur Videos" als
                # Folge-Turn ohne nochmaliges Thema → wanted=set() (kein
                # Match) → Sammlungen/Themenseiten blieben drin, obwohl
                # User klar Einzelinhalte wollte.
                _wanted_types = _resolve_wanted_content_types(
                    req.message or "",
                    session_entities=_debug_entities,
                    classification_entities=classification_entities,
                )
                _page_ctx = (
                    getattr(req.environment, "page_context", None) or {}
                )
                _coll_id = (
                    str(_page_ctx.get("collection_id") or "").strip()
                    if isinstance(_page_ctx, dict) else ""
                ) or None
                _v2 = await _v2_run(
                    user_message=req.message or "",
                    guide_mode=guide_mode_on,
                    wanted_content_types=_wanted_types or None,
                    collection_id=_coll_id,
                    selected_node_ids=selected_card_ids or None,
                    prefetched_pool=cards_for_postprocess,  # ← v1-Pool curieren
                )
                # A/B-Log: erst v1-IDs, dann v2-Output — leicht diff-bar.
                _v1_ids = [
                    (c.get("node_id") if isinstance(c, dict)
                     else getattr(c, "node_id", ""))
                    for c in cards_for_postprocess
                ]
                logger.info(
                    "[v1] cards=%d ids=%s", len(_v1_ids), _v1_ids,
                )
                logger.info(_v2_summary(_v2))
                # Cards austauschen — v2 ist jetzt Quelle der Wahrheit.
                # selected_card_ids spiegelt die v2-Reihenfolge wider, damit
                # der Inline-Sort in _apply_widget_modes_postprocess sie
                # nicht umstellt.
                #
                # Type-Fokus ist STRICT: auch leeres v2-Ergebnis wird
                # durchgereicht — der User hat einen konkreten Inhaltstyp
                # verlangt (z.B. Arbeitsblätter), und Sammlungen/Themenseiten
                # in der Antwort wären verwirrend. Lieber "keine Treffer"
                # als falsche Mix-Cards. Bei "general" / "collection-contents"
                # gilt der alte Sicherheitsfallback (v1 bleibt, wenn v2 0
                # liefert), weil dort der Relevance-Filter manchmal zu strikt
                # ist.
                v2_intent = _v2.get("intent_kind", "")
                v2_cards = _v2.get("cards") or []
                if v2_intent == "type-focus":
                    # Strict: v2 entscheidet final.
                    cards_for_postprocess = v2_cards
                    selected_card_ids = [
                        str(c.get("node_id") or "") for c in v2_cards
                        if isinstance(c, dict) and c.get("node_id")
                    ]
                    _selection_collapses = False
                    if not v2_cards:
                        logger.info(
                            "v2 type-focus lieferte 0 Cards — leere Card-Liste "
                            "wird durchgereicht (User-Anfrage forderte "
                            "spezifischen Inhaltstyp, keine Mix-Cards).",
                        )
                elif v2_cards:
                    cards_for_postprocess = v2_cards
                    selected_card_ids = [
                        str(c.get("node_id") or "") for c in v2_cards
                        if isinstance(c, dict) and c.get("node_id")
                    ]
                    _selection_collapses = False
                else:
                    # general/collection-contents mit 0 v2-Cards: vermutlich
                    # Relevance-Filter zu strikt → v1's Cards behalten als
                    # Fallback.
                    logger.warning(
                        "v2 curation (intent=%s) lieferte 0 Cards, "
                        "behalte v1's %d Cards als Fallback.",
                        v2_intent, len(cards_for_postprocess),
                    )
            except Exception as _v2_err:
                logger.warning(
                    "v2 Curation-Layer fehlgeschlagen, bleibe bei v1: %s",
                    _v2_err,
                )

        # ── Re-Annotation der ``guide_url``-Felder für den Lotsen-Pfad ──
        # _chat_impl macht ``_attach_guide_urls`` einmal vor Response-Return.
        # Default-Limit dort ist ``max_guide_targets_per_turn`` (=5) — damit
        # bekommen Cards an Position 6+ KEIN ``guide_url``.
        #
        # Greift sowohl im Inline-Modus (cards-enabled=false) als auch im
        # Kacheln-Modus (cards-enabled=true), weil Safety-Net und Auto-
        # Augmentation in BEIDEN Modi Cards nachreichen können, die
        # zwischen _chat_impl-Run und _apply_widget_modes_postprocess
        # entstanden sind. Diese frischen Cards haben sonst keine
        # ``guide_url``, womit der Lotsen-Button („Bring mich hin") im
        # Frontend fehlt — auch bei Kacheln. Idempotent, weil
        # ``pick_guide_url`` deterministisch ist.
        if guide_mode_on and cards_for_postprocess:
            try:
                _host = (getattr(req.environment, "host", "") or "").strip()
                if _host:
                    from app.services.guide_mode_service import (
                        annotate_cards_with_guide_url as _annotate,
                        host_is_allowed as _host_ok,
                    )
                    if _host_ok(_host):
                        _annotate(
                            cards_for_postprocess, enabled=True, host=_host,
                            max_targets=20,
                        )
            except Exception as _ann_err:
                logger.warning("inline-mode re-annotate guide_url failed: %s", _ann_err)

        # ── Phase 4a: Card-Pipeline v2 — card.link setzen ─────────
        # ``annotate_cards_with_link`` ist idempotent: wenn v2 sie schon
        # gerufen hat, ist das hier ein no-op. Ohne v2 (Feature-Toggle
        # aus, direct-action, keine Cards) setzt dieser Aufruf card.link
        # erstmalig. Danach kann ``_build_inline_card_links`` direkt auf
        # ``card.link`` zugreifen (Single Source of Truth).
        #
        # Hinweis: der ``_rewrite_external_urls_to_repo``-Aufruf wurde
        # BEWUSST nach oben (vor v2 Curation) verschoben, weil v2 intern
        # ``annotate_cards_with_link`` ruft und dabei ``card.url`` von der
        # externen Provider-URL auf die Repo-URL überschreibt. Stünde der
        # Rewrite hier, wäre ``card.url == card.link`` (beides Repo) und
        # die ``{extern→repo}``-Map leer → no-op → LLM-Text behielte
        # externe URLs.
        try:
            from app.services.card_pipeline import (
                annotate_cards_with_link as _v2_attach_link,
            )
            # ``q=``-Param der Collection-Browse-URL: bevorzugt das extrahierte
            # ``thema`` aus den Entities (z.B. "Klimawandel"), fällt nur dann
            # auf die volle User-Message zurück, wenn der Classifier noch kein
            # Thema isoliert hat. Verhindert dass die Browse-URL die ganze
            # User-Frage als Filter trägt ("Welche Materialien hast du zu
            # Klimawandel?") — was praktisch kein Repo-Match liefert.
            _sq_topic = (session_state.get("entities") or {}).get("thema") or ""
            _v2_attach_link(
                cards_for_postprocess or [],
                guide_mode=guide_mode_on,
                search_query=(str(_sq_topic).strip() or (req.message or "")),
                require_allowed=guide_mode_on,
            )
        except Exception as _link_err:  # pragma: no cover — additiv, darf nicht crashen
            logger.debug("card.link annotation skipped: %s", _link_err)

        # ── Canvas-Sync: page_action.payload.cards auf v2-gecurated angleichen ──
        # Hintergrund: ``_chat_impl`` baut die ``page_action`` mit Cards
        # BEVOR der v2-Curation-Layer läuft. Wenn v2 die Card-Liste
        # filtert/umordnet (z.B. type-focus wirft Sammlungen raus), würde
        # die Canvas-Komponente noch die alte v1-Liste sehen, die Chat-Cards
        # aber die neue v2-Liste. → Inkonsistenz: User sieht im Chat die
        # Videos, im Canvas weiterhin Sammlungen.
        # Fix: nach v2-Curation + Link-Annotation die page_action-Cards
        # mit cards_for_postprocess synchronisieren.
        try:
            _pa = resp.page_action
            _pa_dict = (_pa if isinstance(_pa, dict)
                        else (_pa.model_dump() if _pa else None))
            if (
                _pa_dict
                and _pa_dict.get("action") in ("show_results", "canvas_show_cards")
                and isinstance(_pa_dict.get("payload"), dict)
                and "cards" in _pa_dict["payload"]
            ):
                _synced_cards = []
                for _c in (cards_for_postprocess or []):
                    if isinstance(_c, dict):
                        _synced_cards.append(_c)
                    elif hasattr(_c, "model_dump"):
                        try:
                            _synced_cards.append(_c.model_dump())
                        except Exception:
                            pass
                _pa_dict["payload"]["cards"] = _synced_cards
                resp = resp.model_copy(update={"page_action": _pa_dict})
                logger.debug(
                    "page_action.payload.cards synced with v2-curated cards (%d)",
                    len(_synced_cards),
                )
        except Exception as _sync_err:  # pragma: no cover — Defensiv
            logger.debug("page_action cards-sync skipped: %s", _sync_err)

        qrs, cards_out, pa, txt = _apply_widget_modes_postprocess(
            modes=modes,
            quick_replies=list(resp.quick_replies or []),
            cards=cards_for_postprocess,
            page_action=resp.page_action if isinstance(resp.page_action, dict)
                        else (resp.page_action.model_dump() if resp.page_action else None),
            response_text=resp.content or "",
            guide_mode_on=guide_mode_on,
            user_message=req.message or "",
            selected_card_ids=selected_card_ids,
        )

        # Re-Extraktion: ``_apply_widget_modes_postprocess`` kann Guide-QRs
        # (``__guide__|Label|URL``) als Bullet-Markdown an ``response_text``
        # anhängen — siehe ``_guide_inline_lines`` — und im Inline-Mode
        # (``cards-enabled=false``) zusätzlich die Treffer-Cards als Inline-
        # Markdown-Links. Beide sind im NORMALEN Layout die einzige Anzeige-
        # form für Treffer/Lotsen (sichtbare Bullets/Links im Bot-Text) und
        # MÜSSEN dort bleiben.
        #
        # Seit dem Default-Flip 2026-05-21 ist die gruppierte Box-Darstellung
        # Standard. Re-Extraktion läuft per Default, außer im LEGACY-Inline-
        # Mode:
        #   - cards_enabled=False + inline_result_grouping=False → Legacy:
        #     Cards werden als Markdown-Bullets im Text inline angehängt,
        #     die müssen sichtbar bleiben. Re-Extraktion AUS.
        #   - cards_enabled=False + inline_result_grouping=True/None →
        #     Welle-C.5-Refactor: Cards bleiben im Array, Frontend rendert
        #     sie in Boxen. Keine Inline-Bullets im Text. Re-Extraktion AN
        #     (für LLM-flowing-text-Links + Lotsen-QRs in web_links).
        #   - inline_result_grouping=False (egal cards_enabled): Legacy-
        #     Layout → Re-Extraktion AUS.
        env = req.environment
        _ig_flag = getattr(env, "inline_result_grouping", None)
        _ce_flag = getattr(env, "cards_enabled", None)
        _legacy_inline_mode = (_ce_flag is False) and (_ig_flag is False)
        _grouping_on = (_ig_flag is not False) and (not _legacy_inline_mode)

        if _grouping_on:
            _existing_links = [l.model_dump() if hasattr(l, "model_dump") else dict(l)
                               for l in (resp.web_links or [])]
            _final_txt, _new_links = _extract_web_links_from_text(txt, cards=cards_out)
            # Merge: bestehende web_links bleiben (mit ihrer Reihenfolge),
            # neue aus dem appended-Bullet-Lauf werden ergänzt, dedupliziert
            # nach URL.
            _seen_urls = {l.get("url") for l in _existing_links if isinstance(l, dict)}
            for nl in _new_links:
                if nl.get("url") not in _seen_urls:
                    _existing_links.append(nl)
                    _seen_urls.add(nl.get("url"))
        else:
            _final_txt = txt
            _existing_links = [l.model_dump() if hasattr(l, "model_dump") else dict(l)
                               for l in (resp.web_links or [])]

        # ChatResponse rekonstruieren — Pydantic-Modell aufgrund von
        # Validierungsregeln kopieren wir per model_copy(update=...).
        return resp.model_copy(update={
            "content": _final_txt,
            "cards": cards_out,
            "quick_replies": qrs,
            "page_action": pa,
            "web_links": _existing_links,
        })
    except Exception as _e:  # pragma: no cover — postprocess darf nie blockieren
        logger.warning("widget-modes postprocess failed: %s", _e)
        return resp


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Process a chat message through the 3-phase pattern engine.

    Serialized per session_id via an asyncio.Lock so that two concurrent
    requests from the same session never read/write session_state in parallel.
    Different sessions still run fully in parallel.
    """
    lock = await _get_session_lock(req.session_id)
    try:
        async with lock:
            try:
                _resp = await _chat_impl(req)
                return await _postprocess_response_for_widget_modes(req, _resp)
            except Exception as _impl_err:
                # Top-level safety net: any unhandled exception in _chat_impl
                # (config bug, attribute error in pattern engine, DB hiccup, …)
                # gets converted into a graceful chat bubble instead of HTTP 500.
                # The frontend's catch-all would otherwise swallow it as a
                # generic "konnte ich leider nicht …" message with no debug
                # info — better to surface the exception type to the user so
                # they can report it.
                logger.exception("chat endpoint unhandled exception: %s", _impl_err)
                err_debug = DebugInfo(
                    pattern="ERROR: unhandled_chat_exception",
                    tools_called=["error"],
                )
                try:
                    await save_message(
                        req.session_id, "assistant",
                        f"[unhandled error: {type(_impl_err).__name__}]",
                        debug=err_debug.model_dump(),
                    )
                except Exception:
                    pass  # never let DB-write failures mask the original error
                return ChatResponse(
                    session_id=req.session_id,
                    content=(
                        "Da ist intern etwas schiefgelaufen "
                        f"({type(_impl_err).__name__}). Versuch es nochmal — "
                        "wenn es bestehen bleibt, gib mir kurz Bescheid."
                    ),
                    quick_replies=["Nochmal versuchen"],
                    debug=err_debug,
                )
    finally:
        # Cleanup MUST run AFTER ``async with lock`` exits; otherwise the
        # lock is still held and the refcount-pop check would leak entries.
        await _release_session_lock(req.session_id)


async def _chat_impl(
    req: ChatRequest,
    tracer_listener: Any = None,
    on_token: Any = None,
) -> ChatResponse:
    """Core chat pipeline.

    ``tracer_listener`` is an optional callback used by the streaming
    endpoint (POST /api/chat/stream) to receive ``phase`` events live as
    the Tracer fires them.

    ``on_token`` (Phase-2) is forwarded to ``generate_response`` so the
    final-answer LLM call can stream tokens back. The streaming endpoint
    wraps both into the SSE event queue. Default ``None`` for both keeps
    the regular non-streaming POST /api/chat unchanged.
    """
    # Clear per-request MCP query-meta accumulator so each turn starts fresh.
    reset_query_metas()

    # 1. Load/create session
    session = await get_or_create_session(req.session_id)
    history = await get_messages(req.session_id, limit=20)

    # Parse stored session state
    session_state = {
        "persona_id": session.get("persona_id", ""),
        "state_id": session.get("state_id", "state-1"),
        "entities": json.loads(session.get("entities", "{}")),
        "signal_history": json.loads(session.get("signal_history", "[]")),
        "turn_count": session.get("turn_count", 0),
    }

    env = req.environment.model_dump()

    # Inject page_context entities (node_id, collection_id, search_query,
    # topic_page_slug, subject_slug, document_title)
    page_ctx = env.get("page_context", {})
    for key in (
        "node_id", "collection_id", "search_query",
        "topic_page_slug", "subject_slug", "document_title", "page_type",
    ):
        if page_ctx.get(key):
            session_state["entities"][key] = page_ctx[key]

    # ── Resolve page context → structured metadata ────────────────
    # If the widget was embedded on a theme page (or edu-sharing node
    # render URL), turn the raw node_id / slug into title/description/
    # disciplines/stufen via MCP. Cached per-session, TTL 30 min.
    try:
        from app.services import page_context_service
        await page_context_service.resolve_page_context(page_ctx, session_state)
    except Exception as _pc_err:
        logger.warning("page_context auto-resolve skipped: %s", _pc_err)

    # Save user message
    await save_message(req.session_id, "user", req.message)

    # ── 0. Rate limiting (vor allem anderen) ─────────────────────
    _client_ip = (env.get("page_context") or {}).get("ip", "") or ""
    _rl = check_rate_limit(req.session_id, _client_ip)
    if not _rl["allowed"]:
        await log_safety_event(
            req.session_id, req.message, decision=None,
            ip=_client_ip, rate_limited=True,
        )
        return ChatResponse(
            session_id=req.session_id,
            content=_rl["blocked_message"],
            quick_replies=[],
        )

    # NB: Card-Pipeline v2 wird NICHT mehr hier per fire-and-forget
    # geloggt — der Hauptpfad-Switch sitzt jetzt in
    # ``_postprocess_response_for_widget_modes`` (Option C). Damit hat der
    # v2-Pfad Zugriff auf die LLM-Auswahl (selected_card_ids) und kann sie
    # als Re-Rank-Hint nutzen. Der A/B-Log entsteht dort ebenfalls.

    # ── Handle direct actions (bypass classification) ─────────
    # IMPORTANT: direct actions skip the pattern engine but MUST still go
    # through the same safety gate the standard flow runs. Otherwise an
    # attacker could call /api/chat with action=canvas_edit + a harmful
    # edit_instruction and never face safety classification at all.
    _direct_actions = {
        "browse_collection",
        "generate_learning_path",
        "canvas_create",
        "canvas_edit",
        "canvas_remix",
    }
    if req.action in _direct_actions:
        from app.services.safety_service import (
            assess_safety as _da_assess_safety,
            _regex_gate as _da_regex_gate,
        )
        _safety_text = _direct_action_safety_text(req)
        _signals = session_state.get("signal_history", [])
        # ``assess_safety`` runs ``_regex_gate`` first internally and short-
        # circuits on a hard regex hit, so a single call here gives us the
        # full multi-stage gate with the LLM stages too.
        try:
            _da_safety = await _da_assess_safety(_safety_text, _signals)
        except Exception as _da_err:
            logger.warning("direct-action safety assess failed: %s", _da_err)
            _da_safety = _da_regex_gate(_safety_text, _signals)
        if _da_safety.risk_level == "high":
            await log_safety_event(
                req.session_id, _safety_text, decision=_da_safety.model_dump(),
                ip=_client_ip,
            )
            _block_msg = (
                "Diese Anfrage konnte ich nicht bearbeiten — sie verletzt "
                "Sicherheits- oder Inhaltsregeln. Probier es bitte mit einer "
                "anderen Formulierung erneut."
            )
            err_debug = DebugInfo(
                pattern="SAFETY: blocked_direct_action",
                tools_called=[],
                safety=_da_safety,
                entities={"action": str(req.action or "")},
            )
            try:
                await save_message(
                    req.session_id, "assistant", _block_msg,
                    debug=err_debug.model_dump(),
                )
            except Exception:
                pass
            return ChatResponse(
                session_id=req.session_id,
                content=_block_msg,
                quick_replies=[],
                debug=err_debug,
            )
        if req.action == "browse_collection":
            return await _handle_browse_collection(req, session_state)
        # Host-Flag ai-content-enabled="false" sperrt die KI-Material-
        # Actions vollständig — selbst wenn das Frontend sie direkt
        # anfragt (z.B. via Canvas-Quick-Reply). Alt-Response statt LLM-
        # Aufruf, damit kein Token-Verbrauch und kein Canvas-Aufgehen.
        _ai_blocked_actions = {
            "generate_learning_path", "canvas_create",
            "canvas_edit", "canvas_remix",
        }
        if req.action in _ai_blocked_actions:
            _modes_act = _widget_modes(req)
            if not _modes_act["ai_content_enabled"]:
                from app.services.config_loader import load_widget_modes_config as _lwm
                _wm = _lwm()
                _alt = _wm.get("ai_disabled_alt_response") or {}
                _alt_text = str(_alt.get("text") or
                                "Ich kann gerade kein neues Material erstellen.").strip()
                _alt_qrs = list(_alt.get("quick_replies") or []) \
                    if _modes_act["quick_replies_enabled"] else []
                await add_message(req.session_id, "user", req.message)
                await add_message(req.session_id, "assistant", _alt_text)
                return ChatResponse(
                    session_id=req.session_id,
                    content=_alt_text,
                    cards=[],
                    quick_replies=_alt_qrs,
                    page_action=None,
                )
        if req.action == "generate_learning_path":
            return await _handle_generate_learning_path(req, session_state)
        elif req.action == "canvas_create":
            return await _handle_canvas_create(req, session_state)
        elif req.action == "canvas_edit":
            return await _handle_canvas_edit(req, session_state)
        elif req.action == "canvas_remix":
            return await _handle_canvas_remix(req, session_state)

    # Phase A2 — Token-Cost-Tracking: ein Accumulator pro Turn, durchgeschleift
    # an alle LLM-Helper. Sammelt prompt/completion/cached-Tokens je Modell,
    # landet am Ende in DebugInfo.token_usage.
    from app.services.llm_service import usage_accumulator_new
    usage_acc = usage_accumulator_new()

    # 1b. Safety assessment (Triple-Schema T-12/19) — multi-stage gating
    #     Stage 1: regex (always)
    #     Stage 2: OpenAI moderation (eskaliert bei Verdacht)
    #     Stage 3: LLM legal classifier (parallel zu Stage 2)
    #
    # Optimization: safety and classify_input are logically independent —
    # we run both concurrently with asyncio.gather(). Saves ~600 ms per
    # turn. The fast regex pre-gate runs inline first so a hard CRISIS
    # match still aborts before we waste an LLM classify call.
    from app.services.safety_service import assess_safety, _regex_gate
    from app.services.trace_service import Tracer
    tracer = Tracer(listener=tracer_listener)

    # Safety + classify run as a single parallel block. We measure the
    # combined wall-clock as one trace entry — splitting them produced a
    # confusing "0 ms" entry for the parallel-spawned classify call.
    tracer.start("safety_classify", "Safety + Classification (parallel)")
    quick_gate = _regex_gate(req.message, session_state.get("signal_history", []))

    if quick_gate.risk_level == "high":
        # Hard crisis from regex → no point spending LLM cycles on classify.
        safety = quick_gate
        # Synthesize a minimal classification so the rest of the pipeline
        # can run unchanged. Pattern engine will pick PAT-CRISIS via the
        # safety.enforced_pattern override below.
        from app.models.schemas import ClassificationResult
        classification = ClassificationResult(
            persona_id=session_state.get("persona_id") or "P-AND",
            intent_id="INT-W-04",
            intent_confidence=0.0,
            signals=[],
            entities={},
            next_state=session_state.get("state_id") or "state-1",
            turn_type="initial",
        )
        tracer.end({
            "fast_path": "regex_crisis",
            "risk_level": safety.risk_level,
            "stages": safety.stages_run,
            "escalated": False,
            "legal_flags": safety.legal_flags,
            "classify_skipped": "crisis_short_circuit",
        })
    else:
        # Run safety LLM stages and classify_input in parallel.
        safety_task = asyncio.create_task(
            assess_safety(req.message, session_state.get("signal_history", []))
        )
        classify_task = asyncio.create_task(
            classify_input(req.message, history, session_state, env, req.canvas_state, usage_acc=usage_acc)
        )
        _results = await asyncio.gather(safety_task, classify_task, return_exceptions=True)
        safety, classification = _results
        if isinstance(safety, Exception):
            logger.error("safety task failed: %s", safety)
            safety = _regex_gate(req.message, session_state.get("signal_history", []))
        if isinstance(classification, Exception):
            logger.error("classify task failed: %s", classification)
            # Fall back to a default classification so the pipeline can continue
            from app.models.schemas import ClassificationResult as _CR
            classification = _CR(
                persona_id=session_state.get("persona_id") or "P-AND",
                intent_id="INT-W-02",
                intent_confidence=0.0,
                next_state=session_state.get("state_id") or "state-1",
            )
        tracer.end({
            "parallel": True,
            "risk_level": safety.risk_level,
            "stages": safety.stages_run,
            "escalated": safety.escalated,
            "legal_flags": safety.legal_flags,
            "intent": classification.intent_id,
            "persona": classification.persona_id,
            "intent_confidence": classification.intent_confidence,
            "next_state": classification.next_state,
        })

    # ── Speculative MCP prefetch — Variablen-Stubs ────────────────────
    # Welle-A.3 (2026-05): Der eigentliche Spec-Start wurde HINTER die
    # Pre-Route-Engine verschoben. Begründung: Pre-Route kann den Intent
    # umrouten (R-17 Themenseite → INT-W-03/PAT-28, R-15 Fachportal →
    # INT-W-13/PAT-26, R-19 Lerninhalt-Doppel-Trigger → INT-W-03). Wenn
    # der Spec-Call vorher startet, vergiftet er bei einer falschen
    # initialen Intent-Klassifikation den MCP-Session-State (z.B. läuft
    # search_wlo_collections, was den topic_pages-Index verbiegt — der
    # eigentlich gewollte search_wlo_topic_pages-Call findet dann keine
    # Treffer mehr).
    # Welle C Sprint 4 (2026-05-15): INT-W-03 sind in INT-W-03 gemergt.
    _spec_search_intents = {"INT-W-03", "INT-W-10"}
    spec_task: asyncio.Task | None = None
    spec_tool_name: str | None = None
    spec_tool_args: dict[str, Any] | None = None
    spec_query: str = ""
    extra_spec_tasks: list[tuple[str, asyncio.Task]] = []

    # Log every safety decision (filtered by config: log_all_turns)
    try:
        from app.services.config_loader import load_safety_config
        _log_cfg = (load_safety_config().get("logging") or {})
        if _log_cfg.get("enabled", True):
            if _log_cfg.get("log_all_turns", False) or safety.risk_level != "low":
                await log_safety_event(
                    req.session_id, req.message, safety, ip=_client_ip,
                )
    except Exception as _e:
        logger.warning("safety log failed: %s", _e)

    # ── Placeholder-Topic-Filter ─────────────────────────────────────
    # Wenn der Classifier "Thema" / "etwas" / "irgendwas" / "was" / "Material"
    # etc. als thema extrahiert hat, ist das KEIN echtes Thema, sondern ein
    # Meta-Wort aus der User-Frage ("Ich suche etwas zu einem Thema"). Solche
    # Platzhalter dürfen nicht zu einer MCP-Suche führen — die Engine soll
    # dann sauber degradieren ("nenn mir dein konkretes Thema") statt mit
    # Müll-Treffern ("Wortschatz" / "Startseite Mathematik" für Query="Thema")
    # die Karten-Liste zu fluten.
    #
    # Wortliste + min_length aus 01-base/placeholder-topics.yaml (Studio-
    # pflegbar). Defaults sind dieselben wie die alte Hardcode-Liste.
    try:
        from app.services.config_loader import load_placeholder_topics_config
        _ph_cfg = load_placeholder_topics_config()
        _PLACEHOLDER_TOPICS = _ph_cfg["topics"]
        _PLACEHOLDER_MIN_LEN = _ph_cfg["min_length"]
    except Exception as _ph_err:
        logger.debug("placeholder-topics config load failed: %s", _ph_err)
        _PLACEHOLDER_TOPICS = {
            "thema", "themen", "ein thema", "einem thema", "irgendwas",
            "etwas", "was", "irgendetwas", "irgendein thema", "sonstiges",
            "material", "materialien", "ein material", "ein paar materialien",
            "sachen", "dinge", "stuff", "topic", "etwas thema",
            "inhalt", "inhalte", "content",
        }
        _PLACEHOLDER_MIN_LEN = 3

    def _is_placeholder_topic(value: str | None) -> bool:
        s = (value or "").strip().lower()
        if not s:
            return False
        # Längen-Check: zu kurze Themen sind quasi immer Tippfehler oder
        # nicht-extrahierbarer Rest. "OER"/"DSGVO" (3-4) bleiben gültig.
        if _PLACEHOLDER_MIN_LEN > 0 and len(s) < _PLACEHOLDER_MIN_LEN:
            return True
        return s in _PLACEHOLDER_TOPICS

    if classification.entities and _is_placeholder_topic(
        classification.entities.get("thema")
    ):
        logger.info(
            "thema='%s' ist Platzhalter — auf leer gesetzt, damit Engine sauber nachfragt",
            classification.entities.get("thema"),
        )
        classification.entities["thema"] = ""

    # Auch stale Platzhalter aus vorherigem Turn aus session_state entfernen
    _ss_ents = session_state.get("entities") or {}
    if _is_placeholder_topic(_ss_ents.get("thema")):
        logger.info(
            "stale session_state.thema='%s' (Platzhalter) entfernt",
            _ss_ents.get("thema"),
        )
        _ss_ents["thema"] = ""

    # Update entities based on turn type
    turn_type = classification.turn_type
    new_entities = classification.entities

    if turn_type == "topic_switch":
        # Welle C Sprint 6 — Topic-Switch v3 mit Carry-over-Filter VOR der
        # Rule-Engine.
        #
        # ``shadow_router.build_context()`` liest ``classification.entities``
        # (nicht session_state.entities) für die Routing-Rules. Wenn der
        # LLM-Classifier den alten Slot als Carry-over zurückgibt (z.B.
        # ``thema="Bruchrechnung"`` nach "anderes Thema"), feuert
        # ``rule_topic_switch_needs_clarification`` nicht, weil
        # ``entity.thema`` non-empty ist. Pattern landet bei PAT-28/PAT-06
        # statt PAT-02-Klärung.
        #
        # Fix: Carry-over-Slots aus ``classification.entities`` POPPEN —
        # das macht den context für die Rule-Engine sauber.
        _prev_slots_pre = {
            k: v for k, v in (session_state.get("entities") or {}).items()
            if not str(k).startswith("_") and v
        }
        if classification.entities:
            _dropped_carry = []
            for k in list(classification.entities.keys()):
                if str(k).startswith("_"):
                    continue
                v = classification.entities.get(k)
                if v and _prev_slots_pre.get(k) == v:
                    classification.entities.pop(k)
                    _dropped_carry.append(k)
            if _dropped_carry:
                logger.info(
                    "topic_switch carry-over filter: popped %s from classification.entities (matched prev=%s)",
                    _dropped_carry, _prev_slots_pre,
                )
            # new_entities nach dem Reset neu binden, damit die Merge-
            # Schleife unten den gereinigten Stand sieht.
            new_entities = classification.entities
        #
        # Iterations-Historie:
        #   v1: nur ``session_state["entities"] = {}``. Bug: classification.
        #       entities mit alten Werten wurde danach gleich rein-gemerged.
        #   v2: classification.entities auch leeren. Bug: wenn User ein
        #       NEUES Thema nennt ("Goethe Faust"), wurde es mit gelöscht.
        #   v3 (aktuell): Carry-over erkennen — wenn der Classifier einen
        #       Slot mit DEM SELBEN Wert zurückgibt wie der vorige Turn,
        #       ist das mit hoher Wahrscheinlichkeit Carry-over (kein
        #       echter neuer Wert) → ignorieren. Nur Slots, die WIRKLICH
        #       neu/anders sind, überleben den Reset.
        #
        # Beispiele:
        #   "anderes Thema" + classification.thema="Bruchrechnung" (alt) →
        #       Carry-over erkannt → thema verworfen → Klärung
        #   "Goethe Faust" + classification.thema="Goethe Faust" (neu) →
        #       kein Match mit prev → übernommen
        #
        # Private Marker (_canvas_*, _lp_*) bleiben erhalten — sie sind
        # interner Canvas/Lernpfad-State, kein Such-Slot.
        _prev_slots = {
            k: v for k, v in (session_state.get("entities") or {}).items()
            if not str(k).startswith("_") and v
        }
        _preserved = {
            k: v for k, v in (session_state.get("entities") or {}).items()
            if str(k).startswith("_")
        }
        session_state["entities"] = _preserved
        _accepted: dict[str, Any] = {}
        _carry_over_dropped: dict[str, Any] = {}
        for k, v in (new_entities or {}).items():
            if not v:
                continue
            # Carry-over: Classifier liefert exakt den alten Wert zurück
            # bei einem topic_switch — höchst unwahrscheinlich, dass der
            # User genau das alte Thema neu genannt hat. Verwerfen.
            if _prev_slots.get(k) == v:
                _carry_over_dropped[k] = v
                continue
            session_state["entities"][k] = v
            _accepted[k] = v
        logger.info(
            "topic_switch: kept markers=%s, accepted_new=%s, carry_over_dropped=%s, "
            "prev_slots=%s",
            list(_preserved.keys()), _accepted, _carry_over_dropped, _prev_slots,
        )
    elif turn_type == "correction":
        for k, v in new_entities.items():
            if v:
                session_state["entities"][k] = v
    else:  # initial, follow_up, clarification
        for k, v in new_entities.items():
            if v:
                session_state["entities"][k] = v

    # ── Heuristic enrichment for the engine ─────────────────────
    # The classifier doesn't always extract material_typ from the
    # message text. Our heuristic alias-lookup catches more cases
    # (plurals, synonyms). Lift the heuristic value into
    # classification.entities so R-5 (soft-create) can match.
    _heuristic_mt = extract_material_type_from_message(req.message)
    if _heuristic_mt and not (classification.entities or {}).get("material_typ"):
        if classification.entities is None:
            classification.entities = {}
        classification.entities["material_typ"] = _heuristic_mt
        # Also lift into session_state so downstream code sees it
        session_state.setdefault("entities", {})["material_typ"] = _heuristic_mt

    # ── Pre-Route Rule Engine ────────────────────────────────────
    # Runs BEFORE pattern selection so persona/intent/state corrections
    # propagate into all downstream layers. Live rules (live: true in
    # routing-rules.yaml) overwrite the LLM classifier's output;
    # shadow rules log only. This is the migration target for the
    # legacy state-12-guard, soft-create-override, and persona-self-id
    # blocks that previously lived directly in this router.
    _pre_enforced_pattern: str | None = None
    try:
        from app.services.shadow_router import run_shadow as _run_shadow_pre
        _pre_ret = _run_shadow_pre(
            session_id=req.session_id or "anon",
            turn=int(session_state.get("turn_count", 0)),
            message=req.message or "",
            classification=classification,
            session_state=session_state,
            canvas_state=req.canvas_state if isinstance(req.canvas_state, dict) else None,
            safety=safety,
            actual={
                "intent_final": classification.intent_id,
                "state_final": classification.next_state,
                "pattern_id": None,
                "direct_action": None,
            },
            phase="pre",
        )
        # Capture pre-route enforced_pattern_id so the pattern selection
        # call below can honour it (alongside any safety override).
        if _pre_ret is not None:
            _pre_dec, _pre_live = _pre_ret
            if not _pre_live.is_noop():
                if _pre_live.enforced_pattern_id and _pre_live.enforced_pattern_id != "__from_safety__":
                    _pre_enforced_pattern = _pre_live.enforced_pattern_id
                    logger.info(
                        "pre-route enforces pattern: %s (rules=%s)",
                        _pre_live.enforced_pattern_id, _pre_live.fired_rules,
                    )
                if _pre_live.persona_override:
                    if classification.persona_id != _pre_live.persona_override:
                        logger.info(
                            "pre-route persona override: %s → %s (rules=%s)",
                            classification.persona_id, _pre_live.persona_override,
                            _pre_live.fired_rules,
                        )
                        classification.persona_id = _pre_live.persona_override
                if _pre_live.intent_override:
                    if classification.intent_id != _pre_live.intent_override:
                        logger.info(
                            "pre-route intent override: %s → %s (rules=%s)",
                            classification.intent_id, _pre_live.intent_override,
                            _pre_live.fired_rules,
                        )
                        classification.intent_id = _pre_live.intent_override
                if _pre_live.state_override:
                    if classification.next_state != _pre_live.state_override:
                        logger.info(
                            "pre-route state override: %s → %s (rules=%s)",
                            classification.next_state, _pre_live.state_override,
                            _pre_live.fired_rules,
                        )
                        classification.next_state = _pre_live.state_override
    except Exception as _pre_err:  # pragma: no cover — never block request
        logger.debug("pre-route engine failed: %s", _pre_err)

    # ── Speculative MCP prefetch — Tool-Start (post-Pre-Route) ────────
    # Für Such-Style-Intents starten wir die MCP-Suche im Hintergrund,
    # während Pattern-Selection / Policy / Context laufen. Wenn
    # generate_response() das Ergebnis braucht, sind die Cards meist
    # schon da → kein zweiter LLM-Tool-Round-Trip nötig.
    #
    # Wichtig: Dieser Block läuft NACH der Pre-Route, damit Intent- und
    # Pattern-Overrides aus R-15..R-19 berücksichtigt werden (besonders
    # R-17 Themenseiten-Suche → PAT-28). Ohne die neue Reihenfolge wurde
    # bei "Themenseite zu Photosynthese" zuerst search_wlo_collections
    # gefeuert, das den MCP-Session-State für search_wlo_topic_pages
    # vergiftet hat.
    def _spec_query_from_classification() -> str:
        ents = classification.entities or {}
        for k in ("thema", "fach", "topic", "query", "schlagwort"):
            v = ents.get(k)
            if v:
                return str(v)[:120]
        # Fall back to the raw user message stripped of obvious noise
        return req.message[:120]

    def _spec_has_enough_signal() -> bool:
        """Gate speculative prefetch on having any usable search anchor.

        Anchors (in priority order): explicit ``thema`` / ``topic`` /
        ``schlagwort`` / ``query`` slot, or — as a softer fallback —
        ``fach`` (Subject). With ``fach`` alone we still get a useful
        broad search (Themenseiten/Sammlungen zum Fach), which is what
        the user expects when they ask "Material zum Fach Mathematik".

        Without ANY anchor we skip the prefetch — PAT-02 (Geführte
        Klärung) takes over and asks for at least a Fach.
        """
        ents = classification.entities or {}
        thema = (ents.get("thema") or ents.get("topic")
                 or ents.get("query") or ents.get("schlagwort") or "")
        if str(thema).strip():
            return True
        fach = ents.get("fach")
        if fach and str(fach).strip():
            return True
        return False

    if (
        safety.risk_level != "high"
        and classification.intent_id in _spec_search_intents
        and _spec_has_enough_signal()
    ):
        try:
            spec_query = _spec_query_from_classification()
            _ents_for_spec = classification.entities or {}
            _medientyp = _ents_for_spec.get("medientyp")
            _fach = _ents_for_spec.get("fach")
            _stufe = _ents_for_spec.get("stufe")
            _msg_low = (req.message or "").lower()
            _wants_topic = any(k in _msg_low for k in (
                "themenseite", "themenseiten", "fachportal", "portalseite",
            ))
            _wants_samml = any(k in _msg_low for k in (
                "sammlung", "sammlungen", "kollektion",
            ))
            # _wants_content_only: True nur wenn explizit ein Medientyp
            # (Video / Arbeitsblatt / interaktive Übung / …) genannt ist.
            _wants_content_only = bool(_medientyp)

            # Welle-A.3: Themenseiten-Primary-Switch. Wenn die Pre-Route
            # bereits PAT-28 (Themenseiten-Suche) erzwungen hat ODER
            # INT-W-03 vorliegt, soll der Primary-Call direkt
            # search_wlo_topic_pages sein — nicht erst Collections als
            # Primary, was den Topic-Pages-Index auf dem MCP-Server
            # verbiegt.
            _topic_first = (
                _pre_enforced_pattern == "PAT-28"
                or classification.intent_id == "INT-W-03"
                or _wants_topic
            )

            if spec_query:
                # 1. Primary tool — Themenseiten-Suche dominiert
                #    Collections, sobald die Pre-Route oder der User
                #    explizit "Themenseite" signalisiert hat.
                if _topic_first:
                    spec_tool_name = "search_wlo_topic_pages"
                elif _wants_content_only:
                    spec_tool_name = "search_wlo_content"
                else:
                    # Generic / collection / learning-path intent →
                    # start with collections (rich cards with preview/desc/chips)
                    spec_tool_name = "search_wlo_collections"

                # Primary collections requests get capped at maxResults=5
                # whenever a topic_pages-search is also expected: the WLO MCP
                # server's session-state index for ``search_wlo_topic_pages``
                # is determined by the LAST collections call, and only sticks
                # for small result sets.
                _primary_max = 10
                if spec_tool_name == "search_wlo_collections" and (
                    _wants_topic
                    or classification.intent_id in (
                        "INT-W-03", "INT-W-10",
                    )
                ):
                    _primary_max = 5
                spec_tool_args = {
                    "query": spec_query, "maxResults": _primary_max,
                }
                if _medientyp and spec_tool_name == "search_wlo_content":
                    spec_tool_args["learningResourceType"] = _medientyp
                if _fach:
                    spec_tool_args["discipline"] = _fach
                if _stufe:
                    spec_tool_args["educationalContext"] = _stufe

                # Primary launch — bei Topic-Pages mit Warmup, sonst direkt.
                if spec_tool_name == "search_wlo_topic_pages":
                    spec_task = asyncio.create_task(
                        _topic_pages_with_warmup(spec_query, spec_tool_args),
                    )
                else:
                    spec_task = asyncio.create_task(
                        call_mcp_tool(spec_tool_name, spec_tool_args)
                    )
                logger.info(
                    "speculative primary=%s for intent=%s pre_pattern=%s args=%s",
                    spec_tool_name, classification.intent_id,
                    _pre_enforced_pattern, spec_tool_args,
                )

                # 2. Extra tools — fire in parallel to enrich the response.
                _extras: list[str] = []
                _all_search_intents = (
                    "INT-W-03", "INT-W-10",
                )
                if _topic_first:
                    # Primary war schon topic_pages → ergänze Collections
                    # + Content für die "staircase" (Themenseiten →
                    # Sammlungen → Inhalte).
                    _extras.append("search_wlo_collections")
                    if not _wants_content_only:
                        _extras.append("search_wlo_content")
                elif _wants_topic:
                    # Frontend hat "themenseite" im Text — primary war
                    # collections (R-17 hat nicht gegriffen), wir holen
                    # topic_pages dazu.
                    _extras.append("search_wlo_topic_pages")
                elif classification.intent_id in _all_search_intents:
                    # Generische Suche → Themenseiten als zusätzliche
                    # Card-Quelle (top of staircase) anbieten.
                    _extras.append("search_wlo_topic_pages")

                if classification.intent_id in _all_search_intents:
                    # Sicherstellen dass alle drei Tool-Klassen gelaufen
                    # sind. Doppelungen filtert das spätere Dedup anhand
                    # des Tool-Namens.
                    if not _wants_content_only:
                        _extras.append("search_wlo_content")
                    if _wants_content_only or _wants_samml:
                        _extras.append("search_wlo_collections")

                for extra_name in _extras:
                    if extra_name == spec_tool_name:
                        continue
                    extra_args: dict[str, Any] = {"query": spec_query, "maxResults": 5}
                    if _fach: extra_args["discipline"] = _fach
                    if _stufe: extra_args["educationalContext"] = _stufe

                    # search_wlo_topic_pages is session-stateful on the
                    # WLO MCP server. Run a dedicated warmup before the
                    # topic_pages call (unless we already are the primary).
                    if extra_name == "search_wlo_topic_pages":
                        t = asyncio.create_task(
                            _topic_pages_with_warmup(spec_query, extra_args),
                        )
                    else:
                        t = asyncio.create_task(call_mcp_tool(extra_name, extra_args))

                    extra_spec_tasks.append((extra_name, t))
                    logger.info("speculative extra=%s args=%s", extra_name, extra_args)
        except Exception as _e:
            logger.warning("speculative tool spawn failed: %s", _e)
            spec_task = None

    # Update persona — R-06: persist once detected, overwrite on correction or explicit change
    detected_persona = classification.persona_id
    if not session_state["persona_id"]:
        session_state["persona_id"] = detected_persona
    elif turn_type == "correction":
        session_state["persona_id"] = detected_persona
    elif detected_persona != "P-AND" and detected_persona != session_state["persona_id"]:
        # LLM detected a specific (non-fallback) persona that differs → update
        session_state["persona_id"] = detected_persona

    # Update signals
    new_signals = classification.signals
    signal_history = list(set(session_state["signal_history"] + new_signals))

    # Update state
    new_state = classification.next_state

    # Welle C Sprint 6 — Conversation-State-Plausibilität prüfen.
    # Validator ist Telemetrie-only (auto_correct=False). Implausible
    # Übergänge werden geloggt + in debug.state_transition_warning
    # ausgegeben, aber NICHT korrigiert — die Routing-Rules-Engine
    # (rule_state12_guard etc.) macht weiterhin die harten Korrekturen.
    try:
        from app.services.state_machine import validate_transition as _validate_trans
        _trans_check = _validate_trans(
            prev=session_state.get("state_id") or "",
            next_=new_state,
            intent=classification.intent_id,
            auto_correct=False,
        )
    except Exception as _exc:  # pragma: no cover — never fail the turn
        _trans_check = {
            "validated_state": new_state,
            "plausible": True,
            "reason": f"validator error: {_exc}",
            "prev_next_likely": [],
        }

    # ── Intent-Override: Create-Trigger (robust gegen Classifier-Drift) ──
    # Wenn der User klar ein Erstell-Verb ("Erstelle", "Mach mir ein", ...)
    # verwendet UND ein Material-Typ erkennbar ist (oder er bereits im
    # Canvas-State state-12 ist), overriden wir den Intent auf INT-W-11.
    # Das schuetzt den Canvas-Flow davor, dass der LLM-Classifier
    # "Erstelle mir ein Arbeitsblatt" faelschlich als INT-W-10
    # (Unterrichtsplanung) oder INT-W-03 (Inhalte abrufen) bucht.
    _wants_create = looks_like_create_intent(req.message)
    _detected_mt = extract_material_type_from_message(req.message)
    _in_canvas_state = session_state.get("state_id") == "state-12"
    # Canvas-Inhalt: der Client-Stand (canvas_state.markdown) gewinnt, weil der
    # User im Canvas manuell editiert haben koennte. Fallback auf session_state
    # nur wenn der Client nichts mitschickt (z.B. alter Chat-Client ohne
    # canvas_state-Feld, oder Canvas wurde gerade erst eroeffnet).
    _client_canvas_md = ""
    if isinstance(req.canvas_state, dict):
        _client_canvas_md = (req.canvas_state.get("markdown") or "").strip()
    _existing_canvas_md = (
        _client_canvas_md
        or ((session_state.get("entities") or {}).get("_canvas_last_markdown") or "")
    )
    # ── Canvas-Edit-Override (INT-W-12) ──
    # Wenn Canvas aktiv ist UND vorhandener Canvas-Inhalt besteht UND eine
    # Edit-Formulierung erkannt wird UND KEIN expliziter "neues X"-Override
    # vorliegt, routen wir die Nachricht als EDIT an _handle_canvas_edit
    # (inline) statt eine neue Generierung zu starten.
    from app.services.canvas_service import (
        looks_like_edit_intent, has_explicit_new_create_override,
    )
    # Canvas-Edit kann auch ausserhalb von state-12 erkannt werden — der
    # Classifier kann INT-W-12 setzen, selbst wenn das System-State noch nicht
    # auf 12 gewechselt ist (z.B. bei der ersten Edit-Nachricht). In beiden
    # Faellen wollen wir den Edit-Handler routen, solange echter
    # Canvas-Markdown vorhanden ist.
    _classifier_says_edit = classification.intent_id == "INT-W-12"
    _wants_edit = (
        bool(_existing_canvas_md)
        and (
            (_in_canvas_state and looks_like_edit_intent(req.message))
            or _classifier_says_edit
        )
        and not has_explicit_new_create_override(req.message)
    )
    if _wants_edit:
        logger.info(
            "Intent override: %s -> INT-W-12 (edit-verb in state-12, md_len=%d)",
            classification.intent_id, len(_existing_canvas_md),
        )
        # Shadow-route this canvas-edit turn before we redirect — otherwise
        # the early return below means it never reaches the main shadow hook.
        try:
            from app.services.shadow_router import run_shadow as _run_shadow_edit
            _run_shadow_edit(
                session_id=req.session_id or "anon",
                turn=int(session_state.get("turn_count", 0)),
                message=req.message or "",
                classification=classification,
                session_state=session_state,
                canvas_state=req.canvas_state if isinstance(req.canvas_state, dict) else None,
                safety=safety,
                actual={
                    "intent_final": "INT-W-12",
                    "state_final": "state-12",
                    "pattern_id": "PAT-25",
                    "direct_action": "canvas_edit",
                },
                phase="pre",
            )
        except Exception as _shadow_err:  # pragma: no cover
            logger.debug("shadow router (edit) failed: %s", _shadow_err)
        classification.intent_id = "INT-W-12"
        new_state = "state-12"
        # Route to canvas_edit handler with current markdown + instruction.
        # Carry over the original environment so device / page-context
        # signals stay available in the edit handler.
        edit_req = ChatRequest(
            session_id=req.session_id,
            message=req.message,
            action="canvas_edit",
            action_params={
                "current_markdown": _existing_canvas_md,
                "edit_instruction": req.message,
            },
            environment=req.environment,
            canvas_state=req.canvas_state,
        )
        return await _handle_canvas_edit(edit_req, session_state)

    # ── Soft-Create + State-12 Guard now in Engine ──────────────
    # R-5 (rule_soft_create) replaces the inline soft-create block.
    # R-4 (rule_state12_guard) replaces the inline state-12 guard.
    # Both fire as live rules in the pre-route engine pass above.
    # Heuristic-detected material_typ is lifted into entities before
    # the engine runs (see "Heuristic enrichment" block above), so R-5
    # has the full picture.
    #
    # Subtle simplifications vs. legacy code:
    #   * Position-based search-vs-create resolution is dropped — R-5
    #     fires on any create-verb regex; ambiguous mixed-intent turns
    #     ("zeig mir X und erstelle Y") fall back to the classifier's
    #     choice plus any other rules. Edge case, low frequency.
    #   * `looks_like_create_intent` (broader trigger set) is replaced
    #     by R-5's regex — covers ~95% of the same triggers.

    if classification.intent_id == "INT-W-11":
        # Priority for material_typ (fixes "stale type" bug):
        #   1. type detected from THIS turn's user message  (_detected_mt)
        #   2. classifier's extracted entity for this turn   (_mt_class)
        #   3. sticky session value (prior turn)             (_mt_session)
        # If the user explicitly mentions a type NOW, it always wins over
        # whatever the last turn set — otherwise clicking a new type chip
        # re-generates the previous type.
        _mt_session = session_state.get("entities", {}).get("material_typ")
        _mt_class = (classification.entities or {}).get("material_typ")
        _chosen = _detected_mt or _mt_class or _mt_session
        if _chosen and session_state["entities"].get("material_typ") != _chosen:
            session_state["entities"]["material_typ"] = _chosen
        # Also lift into classification.entities so the canvas flow reads
        # the fresh value without re-querying session state.
        if _chosen:
            if classification.entities is None:
                classification.entities = {}
            classification.entities["material_typ"] = _chosen

    # 2b. Build ContextSnapshot (Triple-Schema T-04/05)
    from app.services.context_service import build_context
    context_snapshot = build_context(env, session_state, classification)
    tracer.record("context", "Context snapshot built", {
        "page": context_snapshot.page,
        "device": context_snapshot.device,
        "turn": context_snapshot.turn_count,
    })

    # 2c. Policy assessment (Triple-Schema T-13/14)
    from app.services.policy_service import assess_policy
    tracer.start("policy", "Policy evaluation")
    policy = assess_policy(
        message=req.message,
        persona_id=session_state["persona_id"],
        intent_id=classification.intent_id,
    )
    tracer.end({
        "matched": policy.matched_rules,
        "blocked_tools": policy.blocked_tools,
        "allowed": policy.allowed,
    })

    # Merge policy blocks into safety blocked_tools (single enforcement path)
    for t in policy.blocked_tools:
        if t not in safety.blocked_tools:
            safety.blocked_tools.append(t)

    # 3. Pattern selection (Gate → Score → Modulate)
    #    Safety may enforce a specific pattern (e.g. PAT-CRISIS on self-harm);
    #    in that case select_pattern() bypasses gating/scoring entirely and
    #    returns the enforced pattern with its full core_rule + tool config.
    tracer.start("pattern", "Pattern selection (3-phase)")
    # Pattern enforcement priority:
    #   1. Safety layer (PAT-CRISIS, PAT-REFUSE-THREAT) always wins
    #   2. Pre-route engine (intent-specific Patterns like PAT-22/23/24)
    _enforced_for_select = safety.enforced_pattern or _pre_enforced_pattern or None
    winner, pattern_output, scores, eliminated = select_pattern(
        persona_id=session_state["persona_id"],
        state_id=new_state,
        intent_id=classification.intent_id,
        signals=new_signals,
        page=env.get("page", "/"),
        device=env.get("device", "desktop"),
        entities=session_state["entities"],
        intent_confidence=classification.intent_confidence,
        enforced_pattern_id=_enforced_for_select,
        pattern_id_hint=getattr(classification, "pattern_id_hint", None),
    )
    tracer.end({
        "winner": winner.id,
        "eliminated": len(eliminated),
        "tie_breaker": pattern_output.get("tie_breaker"),
    })

    # ── Post-route rule engine (shadow + selective live) ──────────
    # Runs after pattern selection so rules can see ``pattern_winner``,
    # ``pattern_runner_up`` and ``pattern_score_gap`` and break ties /
    # override on low-confidence. Rules marked ``live: true`` in YAML
    # actually re-route the request; everything else just logs.
    #
    # Two-pass logging: we run the engine, apply live effects locally
    # to derive the FINAL pattern, then re-call run_shadow with the
    # finalised ``actual`` so the agreement metric is correct.
    try:
        from app.services.shadow_router import run_shadow as _run_shadow
        from app.services.rule_engine import get_rule_engine as _get_engine
        from app.services.shadow_router import build_context as _build_ctx

        _runner_up_id = None
        _score_gap = None
        if scores:
            _ranked = sorted(scores.items(), key=lambda x: -x[1])
            if len(_ranked) >= 1 and _ranked[0][0] == winner.id and len(_ranked) >= 2:
                _runner_up_id = _ranked[1][0]
                _score_gap = round(_ranked[0][1] - _ranked[1][1], 4)

        # Step 1: peek-evaluate the engine to get the live decision before
        # we commit to logging. We don't write a record here.
        _engine = _get_engine()
        _peek_ctx = _build_ctx(
            message=req.message or "",
            classification=classification,
            session_state=session_state,
            canvas_state=req.canvas_state if isinstance(req.canvas_state, dict) else None,
            safety=safety,
            pattern_winner=winner.id,
            pattern_runner_up=_runner_up_id,
            pattern_score_gap=_score_gap,
            pattern_scores=scores,
        )
        _peek_dec = _engine.evaluate(_peek_ctx)
        _peek_live = _engine.extract_live(_peek_dec)

        # Step 2: apply live overrides
        _final_intent = classification.intent_id
        _final_state = new_state
        if not _peek_live.is_noop():
            logger.info(
                "live rule override: enforced=%s intent=%s state=%s rules=%s",
                _peek_live.enforced_pattern_id, _peek_live.intent_override,
                _peek_live.state_override, _peek_live.fired_rules,
            )
            if _peek_live.intent_override:
                classification.intent_id = _peek_live.intent_override
                _final_intent = _peek_live.intent_override
            if _peek_live.state_override:
                new_state = _peek_live.state_override
                _final_state = _peek_live.state_override
            if _peek_live.enforced_pattern_id and _peek_live.enforced_pattern_id != winner.id:
                winner, pattern_output, scores, eliminated = select_pattern(
                    persona_id=session_state["persona_id"],
                    state_id=new_state,
                    intent_id=classification.intent_id,
                    signals=new_signals,
                    page=env.get("page", "/"),
                    device=env.get("device", "desktop"),
                    entities=session_state["entities"],
                    intent_confidence=classification.intent_confidence,
                    enforced_pattern_id=_peek_live.enforced_pattern_id,
                )

        # Step 3: log with the FINAL pattern_id so agreement reflects reality
        _run_shadow(
            session_id=req.session_id or "anon",
            turn=int(session_state.get("turn_count", 0)),
            message=req.message or "",
            classification=classification,
            session_state=session_state,
            canvas_state=req.canvas_state if isinstance(req.canvas_state, dict) else None,
            safety=safety,
            actual={
                "intent_final": _final_intent,
                "state_final": _final_state,
                "pattern_id": winner.id,
                "direct_action": None,
            },
            pattern_winner=winner.id,
            pattern_runner_up=_runner_up_id,
            pattern_score_gap=_score_gap,
            pattern_scores=scores,
            phase="post",
        )
    except Exception as _shadow_err:  # pragma: no cover — never block request
        logger.debug("shadow router failed: %s", _shadow_err)

    # 3b. Safety: strip blocked tools from the chosen pattern
    if safety.blocked_tools:
        if "tools" in pattern_output:
            pattern_output["tools"] = [
                t for t in pattern_output["tools"] if t not in safety.blocked_tools
            ]
        logger.info("Safety blocked tools: %s", safety.blocked_tools)
    if safety.enforced_pattern and winner.id == safety.enforced_pattern:
        logger.info("Safety enforced pattern active: %s", winner.id)

    # ── Widget-Embed-Modus: ai-content-enabled=false ─────────────────
    # Wenn der Host die KI-Material-Generierung abgeschaltet hat und der
    # User trotzdem nach Lernpfad/Material fragt, antworten wir aus
    # widget-modes.yaml — kein LLM, kein Canvas, kein Token-Verbrauch.
    # Die Patterns PAT-19 (Lernpfad) und PAT-21 (Canvas-Create) decken
    # genau diese Anfragen; Intent INT-W-10 / INT-W-11 funktioniert als
    # robuster Backup-Trigger, falls die Pattern-Engine degradiert.
    _modes_early = _widget_modes(req)
    if not _modes_early["ai_content_enabled"] and (
        winner.id in ("PAT-19", "PAT-21")
        or classification.intent_id in ("INT-W-10", "INT-W-11")
    ):
        from app.services.config_loader import load_widget_modes_config as _lwm
        _wm = _lwm()
        _alt = _wm.get("ai_disabled_alt_response") or {}
        _alt_text = str(_alt.get("text") or
                        "Ich kann gerade kein neues Material erstellen.").strip()
        _alt_qrs = list(_alt.get("quick_replies") or []) \
            if _modes_early["quick_replies_enabled"] else []
        debug = DebugInfo(
            persona=session_state.get("persona_id", "P-AND"),
            intent=classification.intent_id,
            state=new_state,
            pattern=f"ACTION: ai_content_disabled (was {winner.id})",
            tools_called=[],
            policy=policy,
            safety=safety,
        )
        await update_session(
            req.session_id,
            new_state,
            session_state["persona_id"],
            classification.intent_id,
        )
        await add_message(req.session_id, "user", req.message)
        await add_message(req.session_id, "assistant", _alt_text)
        return ChatResponse(
            session_id=req.session_id,
            content=_alt_text,
            cards=[],
            quick_replies=_alt_qrs,
            page_action=None,
            debug=debug,
        )

    # 4. RAG areas → presented as callable tools alongside MCP tools
    #    "always" areas are always available as tools
    #    "on-demand" areas are available when pattern sources include "rag"
    rag_context = ""  # No longer blindly injected — LLM calls knowledge tools instead

    # Determine which RAG areas are available as tools for this request
    from app.services.config_loader import load_rag_config
    rag_config = load_rag_config()

    available_rag_areas: list[str] = []
    # Always-on areas are always available
    for area, cfg in rag_config.items():
        if cfg.get("mode") == "always":
            available_rag_areas.append(area)

    # On-demand areas available when pattern enables RAG
    if "rag" in pattern_output.get("sources", []):
        pattern_rag_areas = pattern_output.get("rag_areas", [])
        if pattern_rag_areas:
            available_rag_areas.extend(a for a in pattern_rag_areas if a not in available_rag_areas)
        else:
            for area, cfg in rag_config.items():
                if cfg.get("mode") == "on-demand" and area not in available_rag_areas:
                    available_rag_areas.append(area)

    # 5. Load memory context
    memories = await get_memory(req.session_id)
    memory_context = ""
    if memories:
        mem_parts = [f"- {m['key']}: {m['value']}" for m in memories[:10]]
        memory_context = "\nErinnerungen:\n" + "\n".join(mem_parts)

    # 6. Generate response
    #    Check if this is a learning path / lesson prep request with prior results
    classification_dict = classification.model_dump()
    _lp_keywords = {"lernpfad", "unterrichtsvorbereitung", "unterrichtsstunde", "unterrichtsplanung",
                     "unterricht vorbereiten", "unterrichtseinheit", "stundenentwurf"}
    _msg_lower = req.message.lower()
    # LP-Fast-Path darf NICHT feuern wenn der Classifier einen non-create
    # Intent gewählt hat. Der User will dann z.B. einen bestehenden Lernpfad
    # bearbeiten (INT-W-12), bewerten (INT-W-08) oder Feedback geben
    # (INT-W-04) — nicht einen neuen erstellen.
    # Welle C Sprint 4: INT-W-07 ist in INT-W-03 gemerged (Download =
    # Repo-Link-Output von Search-Pattern, kein Backend-File-Stream).
    _lp_blocking_intents = {
        "INT-W-04", "INT-W-05", "INT-W-08", "INT-W-09", "INT-W-12",
    }
    # Persona-Block: bestimmte Personas profitieren NICHT von einem
    # didaktisch strukturierten Lernpfad. P-W-PRESSE/P-W-POL erwarten
    # Recherche-Material für Artikel/Positionspapiere — nicht eine
    # Stunden-Strukturierung mit Lernzielen. Eval-Befund: für diese
    # Personas führt LP-Generierung zu unnatürlichen Antworten.
    _persona_blocks_lp = session_state.get("persona_id") in (
        "P-W-PRESSE", "P-W-POL",
    )
    # Host-Flag ai-content-enabled="false" sperrt LP-Erzeugung komplett —
    # die Alt-Response unten greift (siehe _ai_content_alt_response).
    _modes_main = _widget_modes(req)
    _has_lp_intent = (
        _modes_main["ai_content_enabled"]
        and classification.intent_id not in _lp_blocking_intents
        and not _persona_blocks_lp
        and (
            any(kw in _msg_lower for kw in _lp_keywords)
            or classification.intent_id == "INT-W-10"
        )
    )
    _last_contents_json = session_state.get("entities", {}).get("_last_contents", "")
    _last_collections_json = session_state.get("entities", {}).get("_last_collections", "")
    _lp_routed = False

    # Only route to LP builder if a concrete topic is known — fach alone is not enough
    _thema = session_state.get("entities", {}).get("thema", "")
    _lp_cards_collected: list[dict] = []  # cards found during LP content gathering

    # Plausibilitätscheck auf _thema, bevor wir einen Lernpfad generieren.
    # Dieselbe Logik wie beim Canvas-Fast-Path: wenn der Classifier einen
    # substring der Nachricht als thema fehlinterpretiert hat, lieber
    # degradieren statt einen unsinnigen Lernpfad zu bauen.
    def _thema_plausible(t: str) -> bool:
        if not t:
            return False
        import re as _rex
        _tl = t.lower().strip(" .,:;?!")
        if len(_tl) < 3:
            return False
        # Starts with pronoun/article → Satzrest
        if _rex.match(r"^(das|dieses|diese|dieser|der|die|den|dem|des|ein|eine|einen|einem|einer|eines|"
                      r"ihm|ihr|ihn|ihnen|mir|mich|dir|dich|uns|euch|es|sie|er)\b", _tl):
            return False
        # Starts with question/meta word
        if _rex.match(r"^(wie|was|wo|wann|warum|wer|wieso|wieviel|kannst|kann|könnte|könntest|"
                      r"hast|habt|gibt|gibts|ideen|vorschläge|tipps|möglichkeiten|"
                      r"eine frage|frage|ne frage|irgendwas|bitte|mal|gerne|gern|"
                      r"also|so|mal eben)\b", _tl):
            return False
        if t.rstrip().endswith("?"):
            return False
        # Query/meta verbs → existierendes Material, nicht LP-Thema
        if _rex.search(r"\b(runterladen|herunterladen|bewerten|bewertung|prüfen|"
                       r"ansehen|anschauen|kopieren|teilen|löschen|exportieren|"
                       r"ausdrucken|drucken|speichern|öffnen|schließen|abbrechen|"
                       r"bereitstellen|bereitstellung|schicken|senden|zusenden|"
                       r"weiterleiten|feedback|meinung|bewerte|review)\b", _tl):
            return False
        # Fragment-Rest nach Material-Typ-Strip: "e der aktuellen..."
        if _rex.match(r"^(e|er|es|en|em|n|s)\s", _tl):
            return False
        return True

    if _thema and not _thema_plausible(_thema):
        logger.info("LP fast-path: thema %r rejected as garbage, forcing degradation", _thema)
        _thema = ""
        session_state.setdefault("entities", {})["thema"] = ""

    # Force degradation when LP keywords detected but thema missing
    if _has_lp_intent and not _thema:
        _missing = [s for s in ["thema", "stufe"] if not session_state.get("entities", {}).get(s)]
        if _missing:
            pattern_output["degradation"] = True
            pattern_output["missing_slots"] = list(set(
                pattern_output.get("missing_slots", []) + _missing
            ))

    if _has_lp_intent and _thema:
        from app.services.llm_service import generate_learning_path_text
        contents_text = ""
        topic = _thema
        tools_called = []
        _lp_used = _get_used_lp_ids(session_state)
        _lp_new_ids: list[str] = []
        _lp_reset = False

        # Topic-switch detection: if classification gave us a NEW thema that
        # doesn't appear in any cached content/collection title, force a fresh
        # search (Priority 3) instead of reusing stale session items.
        _new_thema = (classification.entities or {}).get("thema", "").strip()
        _force_fresh_search = False
        if _new_thema:
            _haystack = (_last_contents_json + _last_collections_json).lower()
            if _new_thema.lower() not in _haystack:
                _force_fresh_search = True
                _last_contents_json = ""
                _last_collections_json = ""
                topic = _new_thema
                logger.info("LP topic switch → fresh search for '%s'", topic)

        try:
            # Priority 1: Use individual content items from session
            if _last_contents_json:
                _contents = json.loads(_last_contents_json)
                if _contents:
                    # Diversity: skip already-used items
                    _filtered = [c for c in _contents if c.get("node_id") and c["node_id"] not in _lp_used]
                    if not _filtered:
                        _filtered = _contents
                        _lp_reset = True
                    _contents = _filtered
                    _lp_new_ids.extend(c.get("node_id", "") for c in _contents)
                    _lp_cards_collected.extend(_contents)
                    contents_lines = []
                    for c in _contents:
                        types = ", ".join(c.get("learning_resource_types", [])) or "Material"
                        line = f"- **{c['title']}** ({types})"
                        if c.get("description"):
                            line += f"\n  {c['description'][:200]}"
                        if c.get("url"):
                            line += f"\n  URL: {c['url']}"
                        contents_lines.append(line)
                    contents_text = "\n".join(contents_lines)
                    tools_called = ["generate_learning_path (aus Einzelinhalten)"]

            # Priority 2: Fetch contents FROM session collections (not the collections themselves!)
            if not contents_text and _last_collections_json:
                _collections = json.loads(_last_collections_json)
                if _collections:
                    all_collection_contents = []
                    tools_called = []
                    for col in _collections[:5]:  # Max 5 collections
                        try:
                            col_contents = await call_mcp_tool("get_collection_contents", {
                                "nodeId": col["node_id"],
                                "maxItems": 8,
                                "skipCount": 0,
                            })
                            if col_contents:
                                all_collection_contents.append(
                                    f"### Aus Sammlung: {col.get('title', 'Unbekannt')}\n{col_contents}"
                                )
                                _col_cards_parsed = parse_wlo_cards(col_contents)
                                await resolve_discipline_labels(_col_cards_parsed)
                                _lp_cards_collected.extend(_col_cards_parsed)
                                tools_called.append(f"get_collection_contents ({col.get('title', '')[:30]})")
                        except Exception as e:
                            logger.warning("Failed to fetch contents for collection %s: %s", col.get("title"), e)
                    if all_collection_contents:
                        contents_text = "\n\n".join(all_collection_contents)
                        tools_called.append("generate_learning_path")

            # Priority 3: No session data — search for collections, fetch THEIR contents
            if not contents_text:
                import re as _re
                # Use entity 'thema' if available (from LLM classification)
                _topic_from_entities = session_state.get("entities", {}).get("thema", "")
                _topic_msg = ""
                if _topic_from_entities:
                    topic = _topic_from_entities
                else:
                    # Extract topic by removing LP/command keywords
                    _topic_msg = _msg_lower
                    # Remove whole phrases first
                    for phrase in ["aus der sammlung", "erstelle mir", "erstelle bitte", "bitte einen", "bitte ein"]:
                        _topic_msg = _topic_msg.replace(phrase, "")
                    # Then individual keywords
                    for kw in list(_lp_keywords) + ["erstelle", "erstell", "daraus", "einen", "ein", "bitte", "mir",
                                                      "wie sieht", "aus", "zum thema", "zur", "zu", "für", "fuer"]:
                        _topic_msg = _topic_msg.replace(kw, " ")
                    _topic_msg = _re.sub(r"\s+", " ", _topic_msg).strip()
                if _topic_msg:
                    topic = _topic_msg
                # Per-topic skipCount so repeated LP requests for the same topic
                # page through different search results.
                _topic_key = f"_lp_skip_{topic.lower()[:40]}"
                _search_skip = int(session_state.get("entities", {}).get(_topic_key, 0) or 0)
                logger.info("LP search: topic='%s' skip=%d", topic, _search_skip)
                try:
                    search_result = await call_mcp_tool("search_wlo_collections", {
                        "query": topic, "maxItems": 5, "skipCount": _search_skip,
                    })
                    search_cards = parse_wlo_cards(search_result)
                    await resolve_discipline_labels(search_cards)
                    logger.info("LP found %d collections", len(search_cards))
                    if not search_cards and _search_skip > 0:
                        # Pagination exhausted → reset and refetch
                        _search_skip = 0
                        _lp_reset = True
                        search_result = await call_mcp_tool("search_wlo_collections", {
                            "query": topic, "maxItems": 5, "skipCount": 0,
                        })
                        search_cards = parse_wlo_cards(search_result)
                        await resolve_discipline_labels(search_cards)
                    # Helper: how many unique items do we have so far?
                    def _unique_count(cards_list: list[dict]) -> int:
                        return len({c.get("node_id", "") for c in cards_list if c.get("node_id")})

                    all_lines: list[str] = []
                    tools_called = [f"search_wlo_collections ({topic[:30]})"]
                    # NOTE: topic must stay as the user asked for it (e.g.
                    # "Eiszeit"). We deliberately do NOT overwrite it with the
                    # first collection's title — doing so would rebrand the
                    # whole learning path to the collection's theme
                    # ("Formen der Erdoberfläche") instead of the user's
                    # actual topic, silently hijacking the request.
                    if search_cards:
                        for sc in search_cards[:3]:
                            col_id = sc.get("node_id")
                            col_title = sc.get("title", "")
                            if not col_id:
                                continue
                            try:
                                col_contents_text = await call_mcp_tool("get_collection_contents", {
                                    "nodeId": col_id, "maxItems": 16, "skipCount": 0,
                                })
                                col_cards = parse_wlo_cards(col_contents_text)
                                await resolve_discipline_labels(col_cards)
                                # Diversity filter: drop already-used items
                                fresh_cards = [c for c in col_cards
                                               if c.get("node_id") and c["node_id"] not in _lp_used]
                                if not fresh_cards and col_cards:
                                    fresh_cards = col_cards  # exhausted → use all, will reset later
                                    _lp_reset = True
                                if fresh_cards:
                                    _lp_cards_collected.extend(fresh_cards[:8])
                                    all_lines.append(f"### Aus Sammlung: {col_title}")
                                    for c in fresh_cards[:8]:
                                        types = ", ".join(c.get("learning_resource_types", [])) or "Material"
                                        line = f"- **{c.get('title','')}** ({types})"
                                        if c.get("description"):
                                            line += f"\n  {c['description'][:200]}"
                                        if c.get("url"):
                                            line += f"\n  URL: {c['url']}"
                                        all_lines.append(line)
                                        if c.get("node_id"):
                                            _lp_new_ids.append(c["node_id"])
                                    tools_called.append(f"get_collection_contents ({col_title[:30]})")
                            except Exception as e:
                                logger.warning("LP fetch failed for '%s': %s", col_title, e)

                    # ── Thin-candidates fallback ─────────────────────────
                    # For specific topics (e.g. "Eiszeit") search_wlo_collections
                    # sometimes returns only 1 weakly-related collection with
                    # a single item. A useful learning path needs at least a
                    # handful of distinct materials. If the collection-based
                    # search produced fewer than 4 unique candidates, pull in
                    # direct content-level hits via search_wlo_content.
                    if _unique_count(_lp_cards_collected) < 4:
                        try:
                            content_res = await call_mcp_tool("search_wlo_content", {
                                "query": topic, "maxItems": 10, "skipCount": 0,
                            })
                            content_cards = parse_wlo_cards(content_res)
                            await resolve_discipline_labels(content_cards)
                            # Drop items already present + previously used
                            _seen_ids = {c.get("node_id") for c in _lp_cards_collected}
                            fresh_content = [
                                c for c in content_cards
                                if c.get("node_id")
                                and c["node_id"] not in _seen_ids
                                and c["node_id"] not in _lp_used
                            ]
                            if fresh_content:
                                _lp_cards_collected.extend(fresh_content[:8])
                                all_lines.append(f"### Direkte Treffer zu \"{topic}\"")
                                for c in fresh_content[:8]:
                                    types = ", ".join(c.get("learning_resource_types", [])) or "Material"
                                    line = f"- **{c.get('title','')}** ({types})"
                                    if c.get("description"):
                                        line += f"\n  {c['description'][:200]}"
                                    if c.get("url"):
                                        line += f"\n  URL: {c['url']}"
                                    all_lines.append(line)
                                    if c.get("node_id"):
                                        _lp_new_ids.append(c["node_id"])
                                tools_called.append(f"search_wlo_content ({topic[:30]})")
                                logger.info(
                                    "LP thin-candidates fallback: added %d content items",
                                    len(fresh_content[:8]),
                                )
                        except Exception as e:
                            logger.warning("LP content fallback failed: %s", e)

                    if all_lines:
                        contents_text = "\n".join(all_lines)
                        tools_called.append("generate_learning_path")
                        # Advance skipCount for next LP request on same topic
                        session_state.setdefault("entities", {})[_topic_key] = _search_skip + 3
                except Exception as e:
                    logger.warning("Failed to search+fetch collections for LP: %s", e)

            logger.info("LP contents: %d chars, topic='%s'", len(contents_text) if contents_text else 0, topic)
            if contents_text:
                response_text = await generate_learning_path_text(
                    collection_title=topic,
                    contents_text=contents_text[:6000],
                    session_state=session_state,
                )
                if _lp_reset:
                    response_text = (response_text or "") + (
                        "\n\n_Hinweis: Es waren keine neuen Inhalte verfügbar, "
                        "deshalb wird die Auswahl jetzt wiederholt._"
                    )
                    session_state.setdefault("entities", {})["_lp_used_node_ids"] = "[]"
                _add_used_lp_ids(session_state, _lp_new_ids)
                # Welle B.5 (2026-05): Filter on cards mentioned in text is
                # now Pattern-driven (`card_text_link_required` flag). PAT-19
                # has it set to true so the existing LP-tile behaviour is
                # preserved. Other Patterns that might one day route through
                # this LP code path can opt out and keep the full card pool.
                if pattern_output.get("card_text_link_required", False):
                    wlo_cards_raw = _filter_cards_used_in_text(
                        _lp_cards_collected, response_text or ""
                    )
                else:
                    wlo_cards_raw = _lp_cards_collected
                _lp_routed = True

                # Also hand the learning-path text to the canvas so the user
                # can print/download it and edit it via chat commands.
                _lp_title = f"Lernpfad: {topic}" if topic else "Lernpfad"
                _lp_first_line = (response_text or "").lstrip().splitlines()[0] if response_text else ""
                _m = _re_lp_title.search(_lp_first_line)
                if _m:
                    _lp_title = _m.group(1).strip() or _lp_title
                # Mark state so follow-up chat messages are treated as
                # canvas-edits against this learning path.
                new_state = "state-12"
                session_state["entities"]["_canvas_material_type"] = "lernpfad"
                session_state["entities"]["_canvas_topic"] = topic or ""
                globals().setdefault("_lp_canvas_payload", None)
                # Set a local variable the page_action builder below picks up.
                _lp_full_markdown = response_text or ""
                _canvas_payload_out_lp = {
                    "action": "canvas_open",
                    "payload": {
                        "title": _lp_title,
                        "material_type": "lernpfad",
                        "material_type_label": "🗺️ Lernpfad",
                        "markdown": _lp_full_markdown,
                    },
                }
                # Replace the long LP text in the chat bubble with a short
                # announcement — the full path lives in the canvas, where
                # the user can print, download or edit it via chat commands.
                # Im Inline-Modus (canvas-enabled="false") landet der Pfad
                # direkt im Chat — Prosa-Variante muss das spiegeln.
                _canvas_on_lp = _widget_modes(req)["canvas_enabled"]
                response_text = _lp_completion_message(
                    topic, _lp_full_markdown, canvas_enabled=_canvas_on_lp,
                )

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Learning path from history failed: %s", e)

    # ── Canvas-Create via natural text (INT-W-11 + PAT-21) ────────
    # User tippt z.B. "Erstelle ein Arbeitsblatt zur Photosynthese"
    # → Classifier setzt INT-W-11, Pattern-Engine waehlt PAT-21
    # → wir generieren Canvas-Inhalt direkt, ohne generate_response.
    _canvas_routed = False
    _canvas_payload_out: dict | None = None
    _canvas_forced_quick_replies: list[str] = []
    # Ensure tools_called exists when we take the canvas fast-path. If the LP
    # block already set it, we leave that value intact.
    try:
        tools_called  # type: ignore[used-before-assignment]  # noqa: F821
    except NameError:
        tools_called = []
    # Trigger canvas flow whenever INT-W-11 is the winning intent — even if
    # the pattern engine eliminated PAT-21 (e.g. precondition_slots missing).
    # In that case we want to show the material-type degradation, not fall
    # through to a generic PAT-02 Clarification response.
    # Canvas-Create-Flow nur, wenn der Host ai-content-enabled NICHT auf
    # false gesetzt hat. Bei abgeschaltetem KI-Content liefert die
    # Alt-Response unten den freundlichen Hinweis.
    if (not _lp_routed
            and classification.intent_id == "INT-W-11"
            and _modes_main["ai_content_enabled"]):
        # Topic priority (fixes "stale topic" bug, same logic as material_typ):
        # 1. classifier extraction from THIS turn
        # 2. sticky session value (prior turn) — only when classifier is silent
        _c_topic = (
            ((classification.entities or {}).get("thema") or "").strip()
            or (session_state.get("entities", {}).get("thema") or "").strip()
        )
        # Type priority (fixes "stale type" bug):
        # 1. direct extraction from THIS turn's message (covers chip-clicks
        #    like "Rollenspielkarten" after a prior Infoblatt creation)
        # 2. classifier entity for this turn
        # 3. fallback to sticky session value from prior turn
        _mt_key = (
            extract_material_type_from_message(req.message)
            or resolve_material_type(
                (classification.entities or {}).get("material_typ", "")
            )
            or resolve_material_type(
                session_state.get("entities", {}).get("material_typ", "")
            )
        )

        # Topic-Fallback: wenn der Classifier kein 'thema' extrahiert hat,
        # aber Material-Typ bekannt ist, nutze die User-Message selbst als
        # Topic (nach Bereinigung: Create-Verben + Material-Typ-Wort raus).
        # Deckt analytische Anfragen ab, wo 'thema' oft komplex ist
        # ('OER-Lage in Deutschland', 'Vergleich WLO vs Schulbücher', etc.).
        if not _c_topic and _mt_key:
            import re as _re_topic

            # ── First-class extraction: explicit topic markers ──────
            # Most natural German create requests follow patterns like:
            #   "… zum Thema X …", "… über X …", "… zu X für Y …"
            # Extract just the noun phrase after the marker — that gives
            # us a much cleaner topic than stripping the full sentence.
            _msg_low = (req.message or "")
            _marker_match = _re_topic.search(
                r"\b(?:zum\s+thema|zu\s+dem\s+thema|über\s+das\s+thema|"
                r"über|zur|zum|zu)\s+"
                r"(?P<topic>[A-ZÄÖÜa-zäöüß][\wäöüÄÖÜß\s\-]{2,80}?)"
                r"(?=[,.?!]|\s+(?:für|zur|zum|in\s+der|im|auf|mit|"
                r"das\s+wäre|und\s+|bitte|gern|gerne|schritt)|\s*$)",
                _msg_low,
                flags=_re_topic.IGNORECASE,
            )
            if _marker_match:
                _candidate = _marker_match.group("topic").strip()
                # Clean trailing fillers + capitalise nicely
                _candidate = _re_topic.sub(r"\s+", " ", _candidate).strip(" .,:;-")
                if 3 <= len(_candidate) <= 80:
                    _c_topic = _candidate
                    # Skip the rest of the messy fallback
                    logger.info("Topic extracted via marker pattern: %r", _c_topic)

        if not _c_topic and _mt_key:
            import re as _re_topic
            _fallback = (req.message or "").strip()
            # strip role-prefixes like "Ich bin Lehrerin und möchte...", "Als
            # Redakteurin brauche ich..." — these are identity statements, not
            # topics. Must happen BEFORE verb-stripping so the subsequent strip
            # can find the verb.
            _fallback = _re_topic.sub(
                r"^\s*(ich\s+bin\s+\w+(?:in)?|"
                r"als\s+\w+(?:kraft|ist[in]*|e?r?|in)?)\b"
                r"[,\s]+(und\s+)?",
                "", _fallback, flags=_re_topic.IGNORECASE,
            )
            # strip leading create verbs (including polite Sie-Form)
            _fallback = _re_topic.sub(
                r"^\s*(erstelle?|generiere?|mach(?:\s+mir)?|bau\s+mir|schreib\s+mir|"
                r"entwirf|produziere|ich\s+brauche|brauche|ich\s+benötige|benötige|"
                r"ich\s+möchte|möchte|ich\s+hab(?:e)?|hab(?:e)?|ich\s+suche|suche|"
                r"hätte\s+ger?n|gib\s+mir|kannst\s+du|könntest\s+du|könnten\s+sie|"
                r"können\s+sie|würden\s+sie|würdest\s+du|hätten\s+sie|haben\s+sie|"
                r"fasse\s+zusammen|wandle)"
                r"\s+(mir\s+)?(bitte\s+)?(ein|eine|einen|die|der|das|den)?\s*",
                "", _fallback, flags=_re_topic.IGNORECASE,
            )
            # strip the detected material-type word
            _aliases = get_type_aliases()
            for _alias in sorted((k for k in _aliases.keys()), key=len, reverse=True):
                if len(_alias) >= 4 and _aliases[_alias] == _mt_key:
                    _fallback = _re_topic.sub(
                        rf"\b{_re_topic.escape(_alias)}\b", "", _fallback,
                        flags=_re_topic.IGNORECASE,
                    )
            # strip leading role prefixes ("als Verwaltungskraft", "als Journalist")
            _fallback = _re_topic.sub(
                r"^\s*als\s+\w+(?:kraft|ist[in]*|e?r?|in)\b[\s,]*",
                "", _fallback, flags=_re_topic.IGNORECASE,
            )
            # strip "zu", "über", "zum", "zur" + collapse whitespace
            _fallback = _re_topic.sub(r"^\s*(zu|über|zum|zur|ueber)\s+", "", _fallback, flags=_re_topic.IGNORECASE)

            # NEW: cut off subordinate clauses like "…, das mein Sohn nutzt"
            # / "…, mit dem die Schüler üben" / "…, dass meine Klasse versteht".
            # The relative clause is just background context, not part of the
            # topic. Without this, the topic became "Mathe in der 3. Klasse,
            # das mein Sohn für seine Hausaufgaben nutze…". Must run BEFORE
            # the trailing-verb stripper so the verb (which is now exposed at
            # end-of-string) can be removed in the next step.
            _fallback = _re_topic.sub(
                r"\s*,\s*(das|dass|der|die|den|dem|mit\s+dem|mit\s+der|"
                r"mit\s+denen|für\s+das|für\s+den|für\s+die|wo|womit|"
                r"woraus|in\s+dem|in\s+der|in\s+denen|um\s+zu|sodass|"
                r"so\s+dass|damit|weil|denn)\b.*$",
                "", _fallback, flags=_re_topic.IGNORECASE,
            )

            # NEW: cut off "für meine|seine|deine|ihre …" purpose clauses
            # ("für meine nächste Sitzung", "für seine Hausaufgaben"). These
            # describe USE not topic; they confuse the LLM downstream.
            _fallback = _re_topic.sub(
                r"\s+für\s+(meine|seine|deine|ihre|unsere|eure|"
                r"meinen|seinen|deinen|ihren|unseren|euren)\s+\w+.*$",
                "", _fallback, flags=_re_topic.IGNORECASE,
            )

            # NEW: strip TRAILING create-verbs ("…erstellen", "…generieren",
            # "…bauen") — they're often at the end of the user sentence,
            # e.g. "Kannst du mir ein Arbeitsblatt für Mathe erstellen?"
            # → after subordinate-cut: "Arbeitsblatt für Mathe erstellen"
            # → after trailing-verb-cut: "Arbeitsblatt für Mathe".
            _fallback = _re_topic.sub(
                r"\s+(erstellen|machen|bauen|generieren|schreiben|entwerfen|"
                r"produzieren|verfassen|zusammenstellen|herunterladen|"
                r"runterladen|zur\s+Verfügung\s+stellen|bereitstellen)"
                r"(\s+kannst|\s+könntest|\s+würdest|\s+wirst|\s+könnten\s+Sie|"
                r"\s+würden\s+Sie|\s+möchtest|\s+möchten\s+Sie)?\??\s*$",
                "", _fallback, flags=_re_topic.IGNORECASE,
            )

            _fallback = _re_topic.sub(r"\s+", " ", _fallback).strip(" .,:;-?")
            # Cap at 80 chars to avoid weirdly long topics
            _c_topic = _fallback[:80]

            # ── Plausibilitätscheck gegen garbage-Topics ──────────────
            # Der regex-Fallback oben kann Müll liefern, wenn die Nachricht
            # kein echter Create-Befehl mit Thema war, sondern z.B. eine Frage
            # zum Download, Feedback oder vage Äußerung. Beispiele aus dem Eval:
            #   "Kannst du mir das Arbeitsblatt runterladen?" → "das runterladen?"
            #   "Ich brauche Ideen für ein neues Arbeitsblatt" → "Ideen für ein neues"
            #   "Gibt's ne Übersicht zu Statistiken?" → "ne zu Statistiken"
            # In allen diesen Fällen: lieber Topic LEER lassen, damit das
            # System sauber degradiert und nach dem konkreten Thema fragt.
            if _c_topic:
                _tl = _c_topic.lower().strip(" .,:;?!")
                _bad = False
                # Zu kurz (weniger als ein echtes Wort)
                if len(_tl) < 3:
                    _bad = True
                # Beginnt mit Pronomen/Artikel/Possessiv (meist Satzreste ohne Sachsubstantiv)
                elif _re_topic.match(
                    r"^(das|dieses|diese|dieser|der|die|den|dem|des|ein|eine|einen|einem|einer|eines|"
                    r"ihm|ihr|ihre|ihres|ihrem|ihren|ihn|ihnen|"
                    r"mein|meine|meines|meinem|meinen|deiner?|deines|deinem|deinen|"
                    r"unser|unsere|unseres|unserem|unseren|euer|eure|"
                    r"mir|mich|dir|dich|uns|euch|es|sie|er)\b",
                    _tl,
                ):
                    _bad = True
                # Beginnt mit Frage-/Meta-Wort (das ist KEINE Create-Intention)
                elif _re_topic.match(
                    r"^(wie|was|wo|wann|warum|wer|wieso|wieviel|wie viel|"
                    r"kannst|kann|könnte|könntest|hast|habt|gibt|gibts|"
                    r"ideen|vorschläge|tipps|möglichkeiten|eine frage|frage|"
                    r"ne frage|irgendwas|irgendwie|neues|neu|alles|etwas|"
                    r"paar|einige|wenige|viele|ein paar|"
                    r"bitte|mal|gerne|gern|also|so|mal eben|kurz mal|"
                    r"hey|hi|hallo|servus|oh|na|hm|äh|eh)\b",
                    _tl,
                ):
                    _bad = True
                # Enthält Konversations-Filler ("das wäre super", "echt cool")
                # → der Fallback hat zu viel Satz erfasst, lieber leer lassen
                elif _re_topic.search(
                    r"\b(das\s+wäre|wäre\s+(echt|super|toll|cool|nett)|"
                    r"echt\s+(super|toll|cool)|"
                    r"das\s+wäre\s+echt\s+super|"
                    r"vielen\s+dank|danke|"
                    r"hilf(e|t)?\s+mir|kannst\s+du\s+mir)\b",
                    _tl,
                ):
                    _bad = True
                # Zu wenig substantielle Inhalt (reine Satz-Fragmente wie
                # "e der aktuellen", "zu Ihrem letzten", "paar Fragen zu")
                elif len(_tl) < 12 or (
                    # Erste 1-2 Zeichen sind kleinbuchstabiger Rest-Fragment,
                    # typisch nach Material-Typ-Strip: "e der aktuellen..."
                    _tl[:2].strip() in ("e", "er", "es", "en", "em", "n", "s")
                    and _tl[2:3] == " "
                ):
                    _bad = True
                # Endet auf Fragezeichen (Frage, keine Create-Directive)
                elif _c_topic.rstrip().endswith("?"):
                    _bad = True
                # Enthält Verben, die KEINE Erstellung bedeuten — User will
                # existierende Dinge aufrufen/manipulieren, kein neues Material
                elif _re_topic.search(
                    r"\b(runterladen|herunterladen|bewerten|bewertung|prüfen|"
                    r"ansehen|anschauen|kopieren|teilen|löschen|exportieren|"
                    r"ausdrucken|drucken|speichern|öffnen|schließen|abbrechen|"
                    r"bereitstellen|bereitstellung|schicken|senden|zusenden|"
                    r"weiterleiten|feedback|meinung|bewerte|review)\b",
                    _tl,
                ):
                    _bad = True
                # Enthält Meta-/Referenz-Tokens ("der letzten", "meiner klasse",
                # "meinem sohn") — deutet auf Abfrage-Intent, nicht Erstellung
                elif _re_topic.search(
                    r"\b(der letzt|die letzt|das letzt|meiner?\s+(klasse|tochter|"
                    r"sohn|kinder|schüler))\b",
                    _tl,
                ):
                    _bad = True
                if _bad:
                    logger.info(
                        "canvas-create topic fallback rejected as garbage: %r (msg: %r)",
                        _c_topic, (req.message or "")[:100],
                    )
                    _c_topic = ""
                else:
                    logger.info("canvas-create topic fallback: %r", _c_topic)

        if _c_topic and _mt_key:
            _mts_flow = get_material_types()
            _label = _mts_flow[_mt_key]["label"]
            _emoji = _mts_flow[_mt_key]["emoji"]
            try:
                _title, _md = await generate_canvas_content(
                    topic=_c_topic,
                    material_type_key=_mt_key,
                    session_state=session_state,
                    memory_context=memory_context,
                )
                _canvas_on_cc = _widget_modes(req)["canvas_enabled"]
                response_text = _canvas_completion_message(
                    _label, _c_topic, _md, canvas_enabled=_canvas_on_cc,
                )
                tools_called = ["canvas_service.generate_canvas_content"]
                wlo_cards_raw = []
                _canvas_routed = True
                _canvas_payload_out = {
                    "action": "canvas_open",
                    "payload": {
                        "title": _title,
                        "material_type": _mt_key,
                        "material_type_label": f"{_emoji} {_label}",
                        "material_type_category": get_material_type_category(_mt_key),
                        "markdown": _md,
                    },
                }
                new_state = "state-12"
                session_state["entities"]["_canvas_material_type"] = _mt_key
                session_state["entities"]["_canvas_topic"] = _c_topic
                # Store fresh markdown so subsequent edit-verb turns
                # ("mach es einfacher") operate on THIS canvas, not on an
                # older one that may still be in session memory.
                session_state["entities"]["_canvas_last_markdown"] = _md
                # Also refresh thema so next turn's classifier sees the
                # current topic, not a stale prior one.
                session_state["entities"]["thema"] = _c_topic
            except Exception as _e:
                # Same hardening as in _handle_canvas_create — graceful chat
                # bubble instead of bubbling a 500. The frontend would otherwise
                # show its generic "konnte ich leider nicht erstellen" message.
                logger.error("PAT-21 canvas generation failed: %s", _e)
                response_text = (
                    f"Ich konnte das **{_label}** zum Thema *{_c_topic}* gerade "
                    f"nicht erstellen ({type(_e).__name__}). Versuch es nochmal — "
                    "meistens klappt es beim zweiten Anlauf."
                )
                tools_called = ["canvas_service.generate_canvas_content", "error"]
                wlo_cards_raw = []
                _canvas_routed = True
                _canvas_payload_out = None
                new_state = session_state.get("state_id") or "state-5"
        elif _c_topic and not _mt_key:
            response_text = (
                f"Welches Material soll ich dir zum Thema **{_c_topic}** erstellen? "
                "Waehle einen Typ aus den Vorschlaegen oder schreib \"Automatisch\", "
                "damit ich den passenden Typ selbst waehle."
            )
            tools_called = []
            wlo_cards_raw = []
            _canvas_routed = True
            _canvas_forced_quick_replies = material_type_quick_replies_for_persona(
                session_state.get("persona_id") or ""
            )
        elif not _c_topic:
            response_text = (
                "Gerne erstelle ich dir ein Material. Zu welchem **Thema**? "
                "Beispiel: \"Erstelle ein Arbeitsblatt zur Photosynthese für Klasse 6\"."
            )
            tools_called = []
            wlo_cards_raw = []
            _canvas_routed = True

    response_outcomes: list = []

    # ── Resolve speculative tool task (if any) ──────────────────────
    # If safety/policy ended up blocking the speculated tool, we cancel
    # and discard. Otherwise we await the result and pass it to
    # generate_response so the LLM gets the data injected and can skip
    # its own tool round-trip.
    prefetched_tool_payload: dict | None = None
    if spec_task is not None:
        # Pattern sources: if the key is present, it's authoritative.
        # Missing key = default allow (legacy patterns without the field).
        # Empty list = pattern explicitly wants no external sources (e.g. PAT-20).
        _pat_sources = pattern_output.get("sources")
        _pat_forbids_mcp = _pat_sources is not None and "mcp" not in _pat_sources
        _pat_wants_no_tools = (
            "tools" in pattern_output and not pattern_output["tools"]
        ) and not (_pat_sources and "mcp" in _pat_sources)
        _degradation_blocks = (
            pattern_output.get("degradation")
            and "thema" in pattern_output.get("missing_slots", [])
        )

        # Welle-A.1 (2026-05): Der frühere Override-Block
        # ``_spec_override_pattern_block`` hat Pattern.sources umgangen,
        # sobald der Classifier einen Such-Intent + Anker vermutet hat.
        # Folge: PAT-10 (Fakten-Antwort) mit sources=[rag] feuerte trotzdem
        # MCP-Tools und produzierte z.B. bei "Was ist WirLernenOnline?"
        # halluzinierte Material-Cards. Jetzt strikt: Pattern bestimmt die
        # Quellen. Speculative wird verworfen, wenn das Pattern MCP nicht
        # explizit erlaubt oder ein leeres tools-Set hat.
        spec_blocked = (
            spec_tool_name in (safety.blocked_tools or [])
            or _pat_forbids_mcp           # pattern.sources whitelist verbietet MCP
            or _pat_wants_no_tools        # pattern.tools = [] + sources kein MCP
            or _lp_routed                 # LP path ran its own MCP logic, discard spec
            or _canvas_routed             # Canvas-create doesn't need search results
            or _degradation_blocks        # Missing thema → ask first, don't search
        )
        if spec_blocked:
            spec_task.cancel()
            try:
                await spec_task
            except (asyncio.CancelledError, Exception):
                pass
            logger.info("speculative %s discarded (blocked by safety/pattern)", spec_tool_name)
        else:
            try:
                spec_result_text = await spec_task
                if spec_result_text:
                    prefetched_tool_payload = {
                        "name": spec_tool_name,
                        "arguments": spec_tool_args,
                        "result_text": spec_result_text,
                    }
            except Exception as _e:
                logger.warning("speculative %s failed: %s", spec_tool_name, _e)

    # Extras (search_wlo_topic_pages, search_wlo_content) auch jetzt schon
    # awaiten und an generate_response durchreichen. Sie laufen seit
    # ``extra_spec_tasks.append`` parallel — wenn der LLM startet, sind sie
    # meist längst fertig (MCP < LLM-Inferenz). Damit sieht der LLM den
    # Gesamt-Treffer-Pool (Themenseiten + Sammlungen + Einzelinhalte) UND
    # kann gezielt 5 IDs auswählen, OHNE selbst ein zweites Such-Tool zu
    # rufen. Vorher: nur primary war sichtbar → LLM picked nur Sammlungen,
    # Backend musste mit auto-augment Einzelinhalte nachreichen, die der
    # LLM dann in seiner Prosa nicht erwähnen konnte.
    prefetched_extras_payload: list[dict] = []
    if extra_spec_tasks and not _lp_routed and not _canvas_routed:
        for _ex_name, _ex_task in extra_spec_tasks:
            if _ex_name in (safety.blocked_tools or []):
                _ex_task.cancel()
                try:
                    await _ex_task
                except (asyncio.CancelledError, Exception):
                    pass
                continue
            try:
                _ex_text = await _ex_task
                if _ex_text:
                    prefetched_extras_payload.append({
                        "name": _ex_name,
                        "arguments": {"query": spec_query, "maxResults": 5},
                        "result_text": _ex_text,
                    })
            except Exception as _ex_err:
                logger.warning(
                    "speculative extra %s failed: %s", _ex_name, _ex_err,
                )
        # Nachgelagerte extra-spec-Merge-Loop (~Zeile 4080) braucht jetzt
        # nichts mehr zu tun, weil die Cards via generate_response in
        # all_cards landen. Liste leeren, damit der spätere `for _name,
        # _task in extra_spec_tasks` no-op ist.
        extra_spec_tasks = []
        if prefetched_extras_payload:
            logger.info(
                "speculative extras pre-injected: %s",
                [p["name"] for p in prefetched_extras_payload],
            )

    if not _lp_routed and not _canvas_routed:
        # Hint the MCP client about the classifier's entities for this
        # turn (fach, thema, stufe, …). MCP tool preprocessors read these
        # to self-correct LLM-supplied arguments — e.g.
        # ``browse_collection_tree``'s UUID resolver overrides a wrong
        # Fachportal pick when ``hints["fach"]`` is set, and
        # ``get_collection_contents`` falls back to a name search when
        # the LLM passes a title. Per-async-task ContextVar so
        # concurrent sessions don't cross-contaminate.
        try:
            from app.services.mcp_client import set_request_hints as _set_request_hints
            _entities = classification_dict.get("entities", {}) or {}
            _set_request_hints({
                k: v for k, v in _entities.items()
                # Drop internal underscore-prefixed keys (page metadata cache)
                if not str(k).startswith("_")
            })
        except Exception:
            pass
        tracer.start("response", "LLM response generation")
        try:
            response_text, wlo_cards_raw, tools_called, response_outcomes = await generate_response(
                message=req.message,
                history=history,
                classification=classification_dict,
                pattern_output=pattern_output,
                pattern_label=winner.label,
                session_state=session_state,
                environment=env,
                rag_context=memory_context,  # Only memory, no blind RAG injection
                available_rag_areas=available_rag_areas,
                rag_config=rag_config,
                blocked_tools=safety.blocked_tools,
                prefetched_tool=prefetched_tool_payload,
                prefetched_extras=prefetched_extras_payload,
                canvas_state=req.canvas_state,
                usage_acc=usage_acc,
                on_token=on_token,
            )
            tracer.end({
                "tools": tools_called,
                "outcomes": len(response_outcomes),
                "prefetch": bool(prefetched_tool_payload),
            })
        except Exception as _gen_err:
            # The main LLM call is the single biggest source of intermittent
            # failures (B-API rate-limit, network blip, malformed JSON in tool
            # calls, …). Without this guard, every blip becomes a 500 →
            # frontend's catch-all swallows it as a generic "etwas ist
            # schiefgelaufen". Degrade to a friendly retry-prompt instead and
            # use the speculatively-prefetched cards if we have any.
            logger.error("generate_response failed: %s", _gen_err)
            tracer.end({"error": f"{type(_gen_err).__name__}: {_gen_err}"})
            response_text = (
                "Ich konnte gerade keine Antwort erzeugen "
                f"({type(_gen_err).__name__}). Versuch es nochmal — meistens "
                "klappt es beim zweiten Anlauf."
            )
            wlo_cards_raw = []
            tools_called = ["error"]
            response_outcomes = []
            # If a speculative MCP prefetch already returned cards, keep them
            # in the response so the user still sees something useful.
            if prefetched_tool_payload and prefetched_tool_payload.get("result_text"):
                try:
                    wlo_cards_raw = parse_wlo_cards(prefetched_tool_payload["result_text"])
                    await resolve_discipline_labels(wlo_cards_raw)
                except Exception as _spec_parse_err:
                    logger.warning(
                        "could not salvage spec cards in error path: %s",
                        _spec_parse_err,
                    )

    # Append policy disclaimers to the response (if any)
    if policy.required_disclaimers and response_text:
        disclaimers = "\n\n".join(f"_{d}_" for d in policy.required_disclaimers)
        response_text = f"{response_text}\n\n{disclaimers}"

    # ── Safety-Hinweis (Medium-Risk) ───────────────────────────────
    # Bei High-Risk uebernimmt PAT-CRISIS bereits die komplette Antwort
    # (inkl. Notfallnummern). Bei Medium-Risk gibt der LLM eine normale
    # Antwort – wir haengen aber einen sichtbaren Hinweis an, damit
    # der User weiss, dass bestimmte Kategorien geflaggt/Tools gesperrt
    # wurden und warum (Transparenz statt stilles Blockieren).
    if safety.risk_level == "medium" and response_text:
        _safety_notes: list[str] = []
        _legal_de = {
            "strafrecht": "strafrechtlich relevante",
            "jugendschutz": "jugendschutzrelevante",
            "persoenlichkeitsrechte": "persoenlichkeitsrechtliche",
            "datenschutz": "datenschutzbezogene",
        }
        if safety.legal_flags:
            _cats = ", ".join(_legal_de.get(f, f) for f in safety.legal_flags[:2])
            _safety_notes.append(
                f"Hinweis: Deine Anfrage beruehrt {_cats} Themen — ich kann dazu "
                f"keine eigenstaendige rechtliche Beratung geben."
            )
        elif safety.blocked_tools:
            _safety_notes.append(
                "Hinweis: Fuer diese Anfrage habe ich die Suche vorsichtshalber eingeschraenkt."
            )
        elif "possible_prompt_injection" in safety.reasons:
            _safety_notes.append(
                "Hinweis: Deine Nachricht enthaelt Formulierungen, die wie eine "
                "Anweisung an mich aussehen. Ich halte mich an meine Regeln."
            )
        if _safety_notes:
            response_text = f"{response_text}\n\n" + "\n\n".join(f"_{n}_" for n in _safety_notes)

    # Triple-Schema T-25/27: feedback from outcomes
    from app.services.outcome_service import adjust_confidence, derive_state_hint
    final_confidence = adjust_confidence(classification.intent_confidence, response_outcomes)
    state_hint = derive_state_hint(response_outcomes)
    if state_hint and state_hint != new_state:
        logger.info("Outcome-based state hint: %s -> %s", new_state, state_hint)
        new_state = state_hint

    # 6c. Merge extra speculative results (collections, topic-pages, content).
    #     These ran in parallel to the primary; their cards are appended
    #     now so the UI can render the full picture (grouped by node_type
    #     in the canvas). If a node_id is already present but the existing
    #     card is skinny (topic-pages-search returns minimal metadata),
    #     we merge the richer fields from the extra card instead of
    #     discarding it. Enrichment-target fields: preview_url, description,
    #     disciplines, educational_contexts, keywords, license, publisher,
    #     learning_resource_types.
    def _enrich_card_inplace(dst: dict, src: dict) -> bool:
        """Copy non-empty fields from src into dst where dst is empty. Returns True on any copy."""
        touched = False
        for f in ("preview_url", "description", "license", "publisher"):
            if not dst.get(f) and src.get(f):
                dst[f] = src[f]
                touched = True
        for f in ("disciplines", "educational_contexts", "keywords", "learning_resource_types"):
            if not (dst.get(f) or []) and (src.get(f) or []):
                dst[f] = src[f]
                touched = True
        # Preserve topic_pages (we want to keep the topic-page link)
        if not dst.get("topic_pages") and src.get("topic_pages"):
            dst["topic_pages"] = src["topic_pages"]
            touched = True
        return touched

    if extra_spec_tasks and not _lp_routed and not _canvas_routed:
        _by_id: dict[str, dict] = {
            c.get("node_id"): c for c in wlo_cards_raw if c.get("node_id")
        }
        for _name, _task in extra_spec_tasks:
            try:
                _text = await _task
                if not _text:
                    continue
                if _name == "search_wlo_topic_pages":
                    _extra_cards = parse_wlo_topic_page_cards(_text)
                else:
                    _extra_cards = parse_wlo_cards(_text)
                if not _extra_cards:
                    continue
                await resolve_discipline_labels(_extra_cards)
                _default_type = (
                    "collection" if ("collection" in _name or "topic" in _name) else "content"
                )
                _added = 0
                _enriched = 0
                for c in _extra_cards:
                    nid = c.get("node_id")
                    if not nid:
                        continue
                    if nid in _by_id:
                        # Enrich the existing skinny card with richer fields
                        if _enrich_card_inplace(_by_id[nid], c):
                            _enriched += 1
                        continue
                    c.setdefault("node_type", _default_type)
                    wlo_cards_raw.append(c)
                    _by_id[nid] = c
                    _added += 1
                if _added or _enriched:
                    tools_called.append(f"{_name} (extra)")
                    logger.info(
                        "extra-spec %s: %d new, %d enriched", _name, _added, _enriched,
                    )
            except Exception as _e:
                logger.warning("extra-spec %s failed: %s", _name, _e)

    # 6d. Synthesize a preview_url for any card that still lacks one.
    #     The edu-sharing preview endpoint accepts just the nodeId. Host
    #     wird zur Laufzeit aus ``REPO_BASE_URL`` aufgelöst, damit Staging-
    #     Nodes auf Staging-Previews zeigen (sonst 404).
    _PREVIEW_BASE = (
        f"{get_repo_base_url()}/edu-sharing/preview"
        "?nodeId={nid}&storeProtocol=workspace&storeId=SpacesStore"
    )
    for c in wlo_cards_raw:
        if not c.get("preview_url") and c.get("node_id"):
            c["preview_url"] = _PREVIEW_BASE.format(nid=c["node_id"])
        # Default description for bare topic-page cards so they don't look
        # empty in the UI. Only fills the gap, never overwrites real data.
        if c.get("topic_pages") and not (c.get("description") or "").strip():
            title = (c.get("title") or "").strip() or "das gewaehlte Thema"
            c["description"] = (
                f"Themenseite \"{title}\" — kuratierte Einstiegsseite mit "
                "Sammlungen, Materialien und weiterführenden Links, "
                "von der WLO-Fachredaktion zusammengestellt."
            )

    # 7. Build WloCard objects — send all, frontend limits display
    all_cards_raw = wlo_cards_raw
    cards = _build_cards(all_cards_raw, classification.persona_id)

    # Build pagination info so frontend knows to limit display.
    # All cards are already in the response — has_more=False because
    # there is nothing more to load from the server (client-side
    # "Mehr anzeigen" reveals the hidden ones).
    pagination = None
    if len(cards) > PAGE_SIZE:
        pagination = PaginationInfo(
            total_count=len(cards),
            skip_count=0,
            page_size=PAGE_SIZE,
            has_more=False,
        )

    # 7b. Store all shown cards in session for follow-up (learning paths, lesson prep)
    collection_refs = []
    content_refs = []
    for c in all_cards_raw:
        if c.get("node_type") == "collection" and c.get("node_id"):
            collection_refs.append({
                "node_id": c["node_id"],
                "title": c.get("title", ""),
            })
        elif c.get("node_id"):
            # Store enough fields that a later Lernpfad-rebuild (Priority 1
            # in the LP router) can reconstruct visually identical cards —
            # especially preview_url for thumbnails. Without this, LP cards
            # re-hydrated from session lose their previews and appear as
            # blank placeholders even though search results just had them.
            content_refs.append({
                "node_id": c["node_id"],
                "title": c.get("title", ""),
                "description": (c.get("description") or "")[:200],
                "url": c.get("url", ""),
                "wlo_url": c.get("wlo_url", ""),
                "preview_url": c.get("preview_url", ""),
                "learning_resource_types": c.get("learning_resource_types", []),
                "disciplines": c.get("disciplines", []),
                "educational_contexts": c.get("educational_contexts", []),
                "keywords": c.get("keywords", []),
                "license": c.get("license", ""),
                "publisher": c.get("publisher", ""),
            })
    if collection_refs:
        session_state["entities"]["_last_collections"] = json.dumps(
            collection_refs[:10]
        )
    if content_refs:
        session_state["entities"]["_last_contents"] = json.dumps(
            content_refs[:15]
        )

    # 8. Generate AI quick replies based on format_follow_up
    #    - "quick_replies": always generate (pattern expects clickable options)
    #    - "inline": pattern has conversational hooks in text, still generate
    #      quick replies as additional options
    #    - "none": skip quick replies (rare — only for terminal patterns)
    #    - Canvas degradation (material-type missing): use forced 12-chip list
    follow_up_mode = pattern_output.get("format_follow_up", "quick_replies")
    # Inline quick-replies (CHAT_INLINE_QUICK_REPLIES) — when generate_response()
    # produced both the answer AND quick_replies in a single LLM call via the
    # respond_to_user tool, the result lands here. Saves the separate ~1-2s
    # quick_replies LLM round-trip. Only honour it when at least one reply
    # came back; an empty list still falls through to the regular generator.
    _inline_qr = (
        session_state.get("_inline_quick_replies")
        if isinstance(session_state, dict) else None
    )
    if isinstance(_inline_qr, list) and _inline_qr:
        # Strip from session_state so the next turn doesn't reuse stale QR.
        session_state.pop("_inline_quick_replies", None)
    else:
        _inline_qr = None
    if _canvas_forced_quick_replies:
        quick_replies = _canvas_forced_quick_replies
    elif _inline_qr is not None:
        quick_replies = _inline_qr
    elif follow_up_mode != "none":
        try:
            quick_replies = await generate_quick_replies(
                message=req.message,
                response_text=response_text,
                classification=classification_dict,
                session_state=session_state,
                usage_acc=usage_acc,
            )
        except Exception as _qr_err:
            # Quick replies are optional UX — never crash a successful main
            # response on a B-API/LLM blip in the QR call. Degrade to none.
            logger.warning("main flow quick_replies failed: %s", _qr_err)
            quick_replies = []
    else:
        quick_replies = []

    # Webseiten-Lotse: deterministisch einen Bring-mich-hin-QR an Position
    # 0 setzen, wenn die User-Frage zu einer bekannten WLO-Seite passt
    # UND noch kein Guide-QR vom LLM dabei ist. Greift nur, wenn der User
    # Guide-Mode aktiv hat — sonst No-op.
    quick_replies = _attach_guide_qr(req, quick_replies, session_state, response_text=response_text)

    # Welle C Sprint 6 Hotfix — Lotsen-Marker aus Bot-Text strippen.
    #
    # Bug-Report: Bei Lotsen-Modus AUS erschien im Chat-Text ein
    # roher ``guide|Label|URL``-String (Markdown frisst ``__`` davor zu
    # Bold-Markup, übrig bleibt ``guide|...``). Das Marker-Format gehört
    # AUSSCHLIESSLICH in ``quick_replies``, niemals in den Antwort-Text.
    # Das LLM schmuggelt es trotzdem hin und wieder rein, weil das Tool-
    # Schema den Marker als Beispiel referenziert.
    #
    # Defensiv: bei jeder Antwort die Marker aus dem Response-Text
    # entfernen — sicher, weil das Marker-Format nie legitim im Bot-Text
    # auftaucht (Lotsen-Buttons werden ausschließlich über quick_replies
    # gerendert).
    response_text = _strip_guide_markers_from_text(response_text)

    # Collection-Relevanz: wenn nur Sammlungen geliefert wurden und keine
    # davon das Topic im Titel traegt, biete prominent den Wechsel zu
    # Einzelmaterialien an. Der User erkennt so sofort, dass die Sammlung
    # nur am Rand passt, und kann mit einem Klick tiefer suchen.
    _topic_for_check = (session_state.get("entities", {}).get("thema") or "").strip()
    if _topic_for_check and cards and not _canvas_forced_quick_replies:
        _all_coll = all(c.node_type == "collection" for c in cards)
        if _all_coll and not _collection_matches_topic(cards, _topic_for_check):
            _fallback_reply = f"Zeig mir stattdessen Einzelmaterialien zu {_topic_for_check}"
            if _fallback_reply not in (quick_replies or []):
                # Insert at position 0, trim list to <=4 to stay within UI
                quick_replies = [_fallback_reply] + (quick_replies or [])
                quick_replies = quick_replies[:4]

    # 9. Build page_action
    #    Priority:
    #     1. Canvas-open/update (PAT-21 or action handler) — dominates
    #     2. Host-page integration (/suche etc.) — legacy show_results
    #     3. Widget-context with cards — canvas_show_cards (Phase 1: move tiles to canvas)
    page_action = None
    # LP-derived canvas payload (set inside the LP block when _lp_routed=True)
    _lp_canvas = locals().get("_canvas_payload_out_lp")
    if _canvas_payload_out:
        page_action = _canvas_payload_out
    elif _lp_canvas:
        page_action = _lp_canvas
    elif cards:
        # Sicherheitsfilter: wenn die Suche ohne konkretes Thema/Fach lief,
        # sind die "Treffer" in aller Regel Müll (z.B. "Wortschatz" oder
        # "Startseite Mathematik" für eine Anfrage "Ich suche etwas zu
        # einem Thema"). Cards leeren — Engine fragt erst nach dem Thema.
        _has_real_topic = bool(
            (session_state.get("entities", {}).get("thema") or "").strip()
            or (session_state.get("entities", {}).get("fach") or "").strip()
        )
        # Ausnahme: Discovery-Pattern (Fachportale-Übersicht / Themen-
        # Drilldown / Themenseiten-Übersicht) zeigen per Definition eine
        # globale Liste — Filterung wäre falsch, weil der User EXPLIZIT
        # genau diese Übersicht angefragt hat. Auch reine Themenseiten-
        # Cards (mit topic_pages-Eigenschaft) gelten als "echte Treffer"
        # und werden nicht unterdrückt.
        _is_discovery_pattern = winner.id in ("PAT-26", "PAT-27")
        _has_topic_page_cards = any(
            (c.topic_pages if hasattr(c, "topic_pages") else None)
            for c in cards
        )
        if not _has_real_topic and not _is_discovery_pattern and not _has_topic_page_cards:
            logger.info(
                "Cards unterdrückt — kein konkretes Thema/Fach im Slot "
                "(pattern=%s)", winner.id,
            )
            cards = []
        # Re-prüfen ob nach Filterung noch Cards übrig sind
    if page_action is None and cards:
        _widget_active = bool((env.get("page_context") or {}).get("widget"))
        _host_page = (not _widget_active) and env.get("page") in ("/suche", "/startseite", "/")
        if _host_page:
            page_action = {
                "action": "show_results",
                "payload": {
                    "cards": [c.model_dump() for c in cards[:pattern_output.get("max_items", 5)]],
                    "query": session_state["entities"].get("thema", req.message),
                },
            }
        else:
            # Widget-Kontext: Kacheln ins Canvas statt in den Chat.
            # Wichtig: gleiche Kachel-Liste wie die Chat-Response (cards),
            # damit die Anzeige zwischen Chat-Unterdrueckung und Canvas
            # konsistent bleibt — sonst sieht der User unterschiedliche
            # Counts je nachdem ob Canvas offen ist.
            page_action = {
                "action": "canvas_show_cards",
                "payload": {
                    "cards": [c.model_dump() for c in cards],
                    "query": session_state["entities"].get("thema", req.message),
                    "pagination": pagination.model_dump() if pagination else None,
                    "append": False,
                },
            }

    # 10. Debug info — resolve human-readable labels for IDs
    from app.services.config_loader import load_persona_definitions, load_intents, load_states
    _persona_labels = {p["id"]: p.get("label", p["id"]) for p in load_persona_definitions()}
    _intent_labels = {i["id"]: i.get("label", i["id"]) for i in load_intents()}
    _state_labels = {s["id"]: s.get("label", s["id"]) for s in load_states()}

    _pid = session_state["persona_id"]
    _iid = classification.intent_id

    debug = DebugInfo(
        persona=f"{_pid} ({_persona_labels.get(_pid, _pid)})",
        intent=f"{_iid} ({_intent_labels.get(_iid, _iid)})",
        state=f"{new_state} ({_state_labels.get(new_state, new_state)})",
        turn_type=classification.turn_type,
        signals=new_signals,
        pattern=f"{winner.id} ({winner.label})",
        entities={k: v for k, v in session_state["entities"].items()
                  if not k.startswith("_")},
        tools_called=tools_called,
        phase1_eliminated=eliminated,
        phase2_scores=scores,
        phase3_modulations={
            "tone": pattern_output.get("tone"),
            "formality": pattern_output.get("formality"),
            "length": pattern_output.get("length"),
            "detail_level": pattern_output.get("detail_level"),
            "max_items": pattern_output.get("max_items"),
            "card_text_mode": pattern_output.get("card_text_mode", "minimal"),
            "response_type": pattern_output.get("response_type"),
            "format_primary": pattern_output.get("format_primary"),
            "format_follow_up": pattern_output.get("format_follow_up"),
            "sources": pattern_output.get("sources", []),
            "rag_areas": pattern_output.get("rag_areas", []),
            "tools": pattern_output.get("tools", []),
            "skip_intro": pattern_output.get("skip_intro"),
            "one_option": pattern_output.get("one_option", False),
            "add_sources": pattern_output.get("add_sources", False),
            "degradation": pattern_output.get("degradation", False),
            "missing_slots": pattern_output.get("missing_slots", []),
            "blocked_patterns": pattern_output.get("blocked_patterns", []),
            "core_rule": pattern_output.get("core_rule", ""),
            # Tie-Breaker (Bonus 2): zeigt ob/wie der LLM-Hint den Engine-
            # Winner überstimmt hat. None = nicht ausgelöst (Hint == Engine
            # oder Tie-Breaker disabled).
            "tie_breaker": pattern_output.get("tie_breaker"),
            # Welle C Sprint 6 — Conversation-State-Plausibilität.
            # plausible=False heißt: Classifier hat einen Übergang
            # gewählt, der nicht in next_likely steht. Telemetrie-only,
            # State wird NICHT automatisch korrigiert (Routing-Rules
            # bleiben die harte Eskalation).
            "state_transition": {
                "prev": session_state.get("state_id") or "",
                "next": new_state,
                "plausible": _trans_check.get("plausible"),
                "reason": _trans_check.get("reason", ""),
                "expected_next_likely": _trans_check.get("prev_next_likely", []),
            },
            # Inline-Mode-Curation (siehe llm_service.py:select_top_cards-Tool):
            # vom LLM gewählte Card-IDs in Anzeige-Reihenfolge. Wird vom
            # ``_apply_widget_modes_postprocess`` als Quelle der Wahrheit
            # genutzt — fällt auf algorithmische Sortierung zurück wenn
            # leer/None (LLM hat das Tool nicht gerufen).
            "selected_card_ids": session_state.get("_selected_card_ids") or [],
            "selected_card_reasoning": session_state.get("_selected_card_reasoning") or "",
        },
        # Triple-Schema v2
        outcomes=response_outcomes,
        safety=safety,
        confidence=final_confidence,
        policy=policy,
        context=context_snapshot,
        trace=tracer.entries,
        # Phase-1-Pattern-Hint (Shadow-Mode): LLM-Vorschlag + Engine-Match
        pattern_id_hint=getattr(classification, "pattern_id_hint", None),
        pattern_reasoning=getattr(classification, "pattern_reasoning", None),
        llm_engine_match=(
            getattr(classification, "pattern_id_hint", None) == winner.id
            if getattr(classification, "pattern_id_hint", None) else None
        ),
        # Phase-A2 Token-Cost-Tracking — aggregiert über alle LLM-Calls dieses Turns
        token_usage=usage_acc,
    )

    # 11. Update session state in DB
    await update_session(
        req.session_id,
        persona_id=session_state["persona_id"],
        state_id=new_state,
        entities=json.dumps(session_state["entities"]),
        signal_history=json.dumps(signal_history),
        turn_count=session_state["turn_count"] + 1,
    )

    # Save bot message (cleaned text + web_links werden weiter unten beim
    # Response-Build genauso wieder verwendet — siehe ``_final_text`` /
    # ``_web_links``). Hier zuerst rechnen, einmal save, einmal return.
    #
    # Die Extraktion strippt Inline-Markdown-Links aus dem Text und stellt
    # sie strukturiert in ``web_links`` bereit. Sie läuft seit Welle C.5
    # (Default-Flip 2026-05-21) per Default — wird nur im LEGACY-Inline-
    # Mode übersprungen:
    #   - ``inline-result-grouping=false`` (explizit) → altes Layout, Inline-
    #     Links bleiben als Lotsen-Bullets im Text.
    #   - ``cards-enabled=false`` + ``inline-result-grouping=false`` → Legacy:
    #     Cards werden vom Postprocess als Markdown-Bullets im Text angehängt,
    #     die müssen sichtbar bleiben — also Re-Extraktion AUS.
    #   - ``cards-enabled=false`` + ``inline-result-grouping=true/None`` →
    #     Welle-C.5-Refactor: keine Inline-Card-Bullets im Text, Frontend
    #     rendert Cards in Boxen. Re-Extraktion AN (für LLM-flowing-text-
    #     Links → Webseiten-Inhalte-Box).
    _ig_flag_impl = getattr(req.environment, "inline_result_grouping", None)
    _ce_flag_impl = getattr(req.environment, "cards_enabled", None)
    _legacy_inline_impl = (_ce_flag_impl is False) and (_ig_flag_impl is False)
    _grouping_on_impl = (_ig_flag_impl is not False) and (not _legacy_inline_impl)
    if _grouping_on_impl:
        _final_text, _web_links = _extract_web_links_from_text(
            response_text, cards=cards,
        )
    else:
        _final_text, _web_links = response_text, []
    # Collect all MCP query metadata accumulated during this turn — wir
    # bauen die Liste hier (vor save_message), damit sie GEMEINSAM mit dem
    # Bot-Text in ``debug_json`` persistiert wird. Beim Session-Restore
    # ``GET /messages`` → ``msg.debug._query_metas`` kommt der Search-CTA
    # ("Alle Treffer in der Suche…") dann auch nach Reopen/Page-Nav wieder.
    from app.models.schemas import QueryMetaEntry
    _raw_metas = get_query_metas()
    _query_meta_entries = []
    for _rm in _raw_metas:
        try:
            _query_meta_entries.append(QueryMetaEntry(
                tool_name=_rm.get("toolName", ""),
                query_type=_rm.get("queryType", ""),
                search_term=_rm.get("searchTerm", ""),
                criteria=_rm.get("criteria", []),
                pagination=_rm.get("pagination", {}),
                repository_url=_rm.get("repositoryUrl", ""),
                search_url=_rm.get("searchUrl", ""),
            ))
        except Exception:
            pass
    # ── Synthetic fallback meta für die Search-CTA (Welle C.5+, 2026-05-21) ──
    # Wenn das MCP für die Sammlungs-/Themenseiten-Tools keinen ``searchUrl``/
    # ``searchTerm`` mitliefert (passiert in Praxis bei manchen Tool-Variants),
    # bleibt die "Treffer zur Suche"-CTA im Frontend leer — obwohl Cards
    # gefunden wurden. Dann hat der Bot **defensiv** eine Suche durchgeführt,
    # die Frontend-Box sollte dem User auch den Sprung in die volle Suche
    # ermöglichen. Wir synthetisieren in diesem Fall einen Meta-Eintrag aus
    # den Klassifikations-Entities (thema / fach / Nachricht) + REPO_BASE_URL,
    # sodass der Frontend-Fallback (groupedSearchUrl) ohne Sonderlogik greift.
    _has_usable_search_signal = any(
        (m.search_url or m.search_term) for m in _query_meta_entries
    )
    if cards and not _has_usable_search_signal:
        _classif_entities = classification_dict.get("entities", {}) or {}
        _fallback_term = ""
        for _k in ("thema", "topic"):
            _v = (_classif_entities.get(_k) or "").strip()
            if _v:
                _fallback_term = _v
                break
        if not _fallback_term:
            _fach = (_classif_entities.get("fach") or "").strip()
            if _fach:
                _fallback_term = _fach
        if not _fallback_term:
            _msg = (req.message or "").strip()
            if _msg and len(_msg) <= 120:
                _fallback_term = _msg
        if _fallback_term:
            try:
                from app.models.schemas import QueryMetaEntry as _QME
                _repo = (get_repo_base_url() or "").rstrip("/")
                _synthetic = _QME(
                    tool_name="synthetic_fallback",
                    query_type="fallback",
                    search_term=_fallback_term,
                    criteria=[],
                    pagination={},
                    repository_url=_repo,
                    search_url="",
                )
                _query_meta_entries.append(_synthetic)
                logger.info(
                    "synthesized fallback queryMeta for search-CTA: term=%r repo=%r",
                    _fallback_term, _repo,
                )
            except Exception as _qm_err:
                logger.warning("fallback queryMeta synthesis failed: %s", _qm_err)

    if _query_meta_entries:
        tracer.record("query_meta", "MCP search queries", {
            "queries": [m.model_dump() for m in _query_meta_entries],
        })

    _debug_for_save = debug.model_dump()
    if _web_links:
        # Persistieren in debug_json, damit nach Page-Refresh / Bubble-
        # Reopen die strukturierte Link-Liste via ``GET /messages`` →
        # ``msg.debug._web_links`` wieder ans Frontend kommt.
        _debug_for_save["_web_links"] = _web_links
    if _query_meta_entries:
        # Analog zu ``_web_links``: damit nach Restore der Search-CTA
        # ("Alle Treffer zu „<term>" in der Suche") wieder erscheint —
        # er braucht ``search_url`` + ``search_term`` aus den query_metas.
        _debug_for_save["_query_metas"] = [
            m.model_dump() for m in _query_meta_entries
        ]

    await save_message(
        req.session_id, "assistant", _final_text,
        cards=[c.model_dump() for c in cards],
        debug=_debug_for_save,
    )

    # 12. Quality logging (non-blocking, fire-and-forget).
    # Governed by TWO switches:
    #   - 01-base/quality-log-config.yaml:logging.enabled  (feature flag)
    #   - 01-base/privacy-config.yaml:logging.quality      (privacy flag)
    # Both must be true. The privacy flag is the user-facing one (Studio).
    try:
        from app.services.config_loader import (
            load_quality_log_config, load_privacy_config,
        )
        _ql_cfg = (load_quality_log_config().get("logging") or {})
        _privacy = load_privacy_config()
        if _ql_cfg.get("enabled", True) and _privacy.get("quality", True):
            from app.services.database import log_quality_event
            asyncio.create_task(log_quality_event(
                session_id=req.session_id,
                message=req.message,
                turn_count=session_state["turn_count"],
                debug_info=debug.model_dump(),
                response_length=len(response_text or ""),
                cards_count=len(cards),
                page=env.get("page", "/"),
                device=env.get("device", "desktop"),
            ))
    except Exception as _e:
        logger.warning("quality log failed: %s", _e)

    # Webseiten-Guide-Modus: enrich cards with same-tab navigation URLs
    # IF the user has the toggle on AND runs on an allow-listed host.
    _attach_guide_urls(req, cards, page_action)

    # Widget-Embed-Modi (cards-/canvas-/quick-replies-enabled) werden
    # zentral im Endpoint-Wrapper ``_postprocess_response_for_widget_modes``
    # angewandt — siehe @router.post("") oben. Dadurch greifen sie auch
    # für direct-action-Returns (Canvas-Create, Lernpfad-Action) ohne
    # dass jeder Handler-Pfad einzeln angefasst werden muss.

    # Welle C Sprint 6 — Auto-Followup-Trigger pro Verlaufs-Phase.
    # In state-6 (Ergebnis-Kuratierung) hängt der Bot deterministisch
    # eine "Hat das geholfen?"-QR an (statt sich darauf zu verlassen,
    # dass der LLM-QR-Generator es trifft). Nur wenn cards präsentiert
    # wurden und keine vergleichbare Refinement-QR schon dabei ist.
    quick_replies = _apply_state_auto_followup(
        state_id=new_state,
        quick_replies=quick_replies,
        has_cards=bool(cards),
    )

    # ``_final_text`` + ``_web_links`` + ``_query_meta_entries`` wurden
    # bereits oben (vor save_message) berechnet — wiederverwenden, statt
    # ein zweites Mal zu extrahieren.
    return ChatResponse(
        session_id=req.session_id,
        content=_final_text,
        cards=cards,
        follow_up=pattern_output.get("format_follow_up", "quick_replies"),
        quick_replies=quick_replies,
        debug=debug,
        page_action=page_action,
        pagination=pagination,
        query_metas=_query_meta_entries,
        web_links=_web_links,
    )


def _apply_state_auto_followup(
    *,
    state_id: str,
    quick_replies: list[str],
    has_cards: bool,
) -> list[str]:
    """Append phase-specific Auto-Followups deterministically (Welle C Sprint 6).

    Nur state-6 (Ergebnis-Kuratierung) hat aktuell einen harten Trigger —
    nach Ergebnis-Lieferung soll der Bot proaktiv nach Pass-Quality fragen.
    Andere Phasen verlassen sich auf den LLM-Quick-Reply-Generator
    (der über die bot_directive aus states.yaml gesteuert wird).

    Idempotent: wenn die LLM-generierten QRs schon eine "Hat das geholfen?"-
    artige Frage enthalten, wird nichts dazugepackt.
    """
    if state_id != "state-6" or not has_cards:
        return quick_replies

    qrs = list(quick_replies) if quick_replies else []
    # Doublette-Schutz: hat der LLM schon eine Pass-Quality-Frage?
    pass_quality_keywords = (
        "geholfen", "gepasst", "passt", "passend", "richtig",
        "stimmt", "weiterhilft",
    )
    for q in qrs:
        q_lower = (q or "").lower()
        if any(kw in q_lower for kw in pass_quality_keywords):
            return qrs  # schon eine Pass-QR drin, nichts tun

    # Nicht überfüllen — wenn der LLM schon 4 QRs hatte, ersetze die letzte.
    auto_qr = "Hat das geholfen?"
    if len(qrs) >= 4:
        qrs[-1] = auto_qr
    else:
        qrs.append(auto_qr)
    return qrs


@router.post("/stream")
async def chat_stream(req: ChatRequest):
    """Streaming chat endpoint (Phase-1 SSE).

    Same body as POST /api/chat, but the response is a Server-Sent-Event
    stream that emits ``phase`` events live as the Tracer fires them, plus
    a final ``result`` event with the complete ChatResponse.

    Frontends receive interactive activity feedback during the 2-5s
    classification + tool-loop, instead of staring at a static spinner
    until the whole pipeline finishes.

    Event types:
      - ``phase``: ``{kind: 'start'|'end'|'record', step, label, data}``
        from the Tracer.
      - ``result``: full ChatResponse JSON (final).
      - ``error``: ``{message}`` if the pipeline failed.
      - keepalive comment lines (``: keepalive\\n\\n``) to keep the
        connection open through proxies during long tool-loops.

    The non-streaming POST /api/chat is unchanged for backwards-compat.
    """
    import asyncio as _asyncio

    # Mark this turn as streaming in the logs so it's distinguishable from
    # the regular POST /api/chat traffic when grepping production logs.
    logger.info(
        "chat_stream START session=%s msg=%r action=%s",
        req.session_id, (req.message or "")[:80], req.action or "-",
    )

    queue: _asyncio.Queue = _asyncio.Queue()
    DONE = object()
    PHASE = "phase"

    def _listener(kind: str, step: str, label: str, data: dict[str, Any]) -> None:
        # Sync call from Tracer → push event to async queue (non-blocking).
        try:
            queue.put_nowait((PHASE, {
                "kind": kind,
                "step": step,
                "label": label,
                "data": data,
            }))
        except Exception:
            pass  # never let a slow consumer break the pipeline

    # Phase-2 token streaming was rolled back — it only kicked in for the
    # last ~1-2 seconds (after the tool-loop) and the per-token re-render
    # caused visible flicker. The Streaming-Helper (``_stream_completion``
    # + ``_RespondToUserExtractor``) stays in llm_service for future
    # reuse, but ``on_token`` is no longer wired up here. Phase-1 phase
    # labels remain fully active.

    async def _run_impl():
        """Run the chat impl under the per-session lock and signal DONE."""
        lock = await _get_session_lock(req.session_id)
        try:
            async with lock:
                try:
                    return await _chat_impl(
                        req,
                        tracer_listener=_listener,
                    )
                except Exception as e:
                    logger.exception("chat_stream impl failed: %s", e)
                    return e
        finally:
            await _release_session_lock(req.session_id)
            queue.put_nowait(DONE)

    async def event_stream():
        impl_task = _asyncio.create_task(_run_impl())

        # Tell the client we're connected — flushes proxy buffers immediately.
        yield "event: connected\ndata: {}\n\n"

        # Drain queued events until the impl signals DONE. Use a small
        # timeout on get() so we can emit periodic keepalives during quiet
        # stretches (e.g. a slow MCP search) — many proxies close idle
        # SSE connections after 30s without bytes.
        while True:
            try:
                evt = await _asyncio.wait_for(queue.get(), timeout=10.0)
            except _asyncio.TimeoutError:
                yield ": keepalive\n\n"
                if impl_task.done():
                    break
                continue
            if evt is DONE:
                break
            try:
                kind, payload = evt
                yield (
                    f"event: {kind}\n"
                    f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                )
            except Exception as _ye:
                logger.warning("event-stream serialise failed: %s", _ye)

        # Drain any post-DONE events queued before listener detach (rare).
        while not queue.empty():
            evt = queue.get_nowait()
            if evt is DONE:
                continue
            try:
                kind, payload = evt
                yield (
                    f"event: {kind}\n"
                    f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                )
            except Exception:
                pass

        # Final result (or error). Using ``await impl_task`` is safe here —
        # _run_impl already returned by the time DONE was queued.
        result = await impl_task
        if isinstance(result, Exception):
            err_payload = {
                "message": f"{type(result).__name__}: {result}"[:400],
            }
            logger.warning(
                "chat_stream END session=%s status=error %s",
                req.session_id, err_payload["message"],
            )
            yield f"event: error\ndata: {json.dumps(err_payload)}\n\n"
        else:
            # Widget-Embed-Modi (cards/canvas/quick-replies) auch im SSE-
            # Pfad anwenden — der Wrapper in /api/chat greift hier nicht,
            # weil der Stream-Endpoint _chat_impl direkt aufruft.
            try:
                result = await _postprocess_response_for_widget_modes(req, result)
            except Exception as _we:
                logger.warning("stream widget-modes postprocess failed: %s", _we)
            try:
                payload = result.model_dump()
            except Exception as _pe:
                logger.warning("result.model_dump failed: %s", _pe)
                payload = {"content": "(serialise error)"}
            # Concise success line — pattern + total token count makes log
            # diagnosis fast without dumping the whole response body.
            try:
                _dbg = (payload.get("debug") or {}) if isinstance(payload, dict) else {}
                _tu = _dbg.get("token_usage") or {}
                logger.info(
                    "chat_stream END session=%s pattern=%s tokens=%s/%s cached=%s",
                    req.session_id,
                    str(_dbg.get("pattern", ""))[:40],
                    _tu.get("prompt_tokens", 0),
                    _tu.get("completion_tokens", 0),
                    _tu.get("cached_tokens", 0),
                )
            except Exception:
                pass
            yield (
                "event: result\n"
                f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            # Proxies should not buffer SSE.
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
