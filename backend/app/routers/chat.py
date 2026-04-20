"""Chat router — main conversation endpoint with 3-phase pattern engine."""

from __future__ import annotations

import asyncio
import json
import logging
import re
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
    get_or_create_session, update_session, save_message, get_messages, get_memory,
    log_safety_event,
)
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
)
from app.services.pattern_engine import select_pattern, get_patterns
from app.services.rag_service import get_rag_context, get_always_on_rag_context
from app.services.config_loader import get_on_demand_rag_areas

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Per-session locks (race-condition guard) ────────────────────
# Prevents two concurrent requests from the same session_id from clobbering
# each other's session_state. Locks are created lazily and cleaned up
# opportunistically when no waiters remain.
_session_locks: dict[str, asyncio.Lock] = {}
_session_locks_guard = asyncio.Lock()


async def _get_session_lock(session_id: str) -> asyncio.Lock:
    async with _session_locks_guard:
        lock = _session_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            _session_locks[session_id] = lock
        return lock


def _release_session_lock(session_id: str) -> None:
    """Drop the lock from the registry if no one is waiting on it."""
    lock = _session_locks.get(session_id)
    if lock is not None and not lock.locked():
        _session_locks.pop(session_id, None)


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

    # Generate quick replies for collection browse context
    quick_replies = await generate_quick_replies(
        message=req.message,
        response_text=response_text,
        classification={
            "persona_id": session_state.get("persona_id", "P-AND"),
            "intent_id": "INT-W-03a",
            "next_state": "state-6",
            "entities": session_state.get("entities", {}),
        },
        session_state=session_state,
    )

    debug = DebugInfo(
        persona=session_state.get("persona_id", ""),
        intent="INT-W-03a",
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

    # Generate quick replies
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

    short_ack = (
        f"Ich habe dir einen **Lernpfad zu *{title}*** im Canvas rechts aufgebaut. "
        "Du kannst ihn dort drucken, als Markdown speichern oder mir sagen, "
        "was angepasst werden soll (z.B. *\"mach ihn für Klasse 5 einfacher\"* "
        "oder *\"füge einen Schritt zur Sicherung hinzu\"*)."
    )

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

    title, markdown = await generate_canvas_content(
        topic=topic,
        material_type_key=type_key,
        session_state=session_state,
        memory_context=memory_context,
    )
    _mts = get_material_types()
    label = _mts[type_key]["label"]
    emoji = _mts[type_key]["emoji"]

    response_text = (
        f"Ich habe dir ein **{label}** zum Thema *{topic}* erstellt — "
        f"schau es dir im Canvas an. Schreib mir einfach, was ich anpassen soll "
        f"(z.B. \"mach die Aufgaben einfacher\" oder \"füge Lösungen hinzu\")."
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

    title_out, md = await generate_canvas_remix(
        topic=topic,
        material_type_key=mt_key,
        source_meta=source_meta,
        source_text=extracted_text,
        session_state=session_state,
        memory_context=memory_context,
    )

    short_note = "" if extraction_ok else " *(Volltext war nicht abrufbar — Remix basiert auf Metadaten.)*"
    response_text = (
        f"Ich habe dir einen **Remix als {label}** zum Thema *{topic}* im Canvas "
        f"erstellt.{short_note} Sag mir einfach, was ich anpassen soll "
        "(z.B. *\"mach es einfacher\"* oder *\"füge Lösungen hinzu\"*)."
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

    new_md = await edit_canvas_content(
        current_markdown=current_md,
        edit_instruction=instruction,
        session_state=session_state,
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
@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Process a chat message through the 3-phase pattern engine.

    Serialized per session_id via an asyncio.Lock so that two concurrent
    requests from the same session never read/write session_state in parallel.
    Different sessions still run fully in parallel.
    """
    lock = await _get_session_lock(req.session_id)
    async with lock:
        try:
            return await _chat_impl(req)
        finally:
            _release_session_lock(req.session_id)


async def _chat_impl(req: ChatRequest) -> ChatResponse:
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

    # ── Handle direct actions (bypass classification) ─────────
    if req.action == "browse_collection":
        return await _handle_browse_collection(req, session_state)
    elif req.action == "generate_learning_path":
        return await _handle_generate_learning_path(req, session_state)
    elif req.action == "canvas_create":
        return await _handle_canvas_create(req, session_state)
    elif req.action == "canvas_edit":
        return await _handle_canvas_edit(req, session_state)
    elif req.action == "canvas_remix":
        return await _handle_canvas_remix(req, session_state)

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
    tracer = Tracer()

    tracer.start("safety", "Safety assessment (multi-stage)")
    quick_gate = _regex_gate(req.message, session_state.get("signal_history", []))

    if quick_gate.risk_level == "high":
        # Hard crisis from regex → no point spending LLM cycles on classify.
        safety = quick_gate
        tracer.end({
            "risk_level": safety.risk_level,
            "stages": safety.stages_run,
            "escalated": False,
            "legal_flags": safety.legal_flags,
            "fast_path": "regex_crisis",
        })
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
        tracer.record("classify", "LLM classification", {"skipped": "crisis_short_circuit"})
    else:
        # Run safety LLM stages and classify_input in parallel.
        safety_task = asyncio.create_task(
            assess_safety(req.message, session_state.get("signal_history", []))
        )
        classify_task = asyncio.create_task(
            classify_input(req.message, history, session_state, env, req.canvas_state)
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
            "risk_level": safety.risk_level,
            "stages": safety.stages_run,
            "escalated": safety.escalated,
            "legal_flags": safety.legal_flags,
            "parallel": True,
        })
        tracer.record("classify", "LLM classification (parallel)", {
            "intent": classification.intent_id,
            "persona": classification.persona_id,
            "confidence": classification.intent_confidence,
            "next_state": classification.next_state,
        })

    # ── Speculative MCP prefetch ──────────────────────────────────────
    # For search-style intents we already know the query → start the MCP
    # call in the background while pattern selection / policy / context
    # build run. By the time generate_response() needs it, the cards are
    # usually already there and the LLM does NOT need a tool round-trip.
    _spec_search_intents = {"INT-W-03a", "INT-W-03b", "INT-W-03c", "INT-W-10"}
    spec_task: asyncio.Task | None = None
    spec_tool_name: str | None = None
    spec_tool_args: dict[str, Any] | None = None

    def _spec_query_from_classification() -> str:
        ents = classification.entities or {}
        for k in ("thema", "fach", "topic", "query", "schlagwort"):
            v = ents.get(k)
            if v:
                return str(v)[:120]
        # Fall back to the raw user message stripped of obvious noise
        return req.message[:120]

    # Extra speculative tasks that run in parallel next to the primary one.
    # Their results are merged into the cards list after the main response
    # is generated — this lets us return e.g. collections + content + topic
    # pages side-by-side when the user asks generically ("etwas zu Optik").
    extra_spec_tasks: list[tuple[str, asyncio.Task]] = []

    if safety.risk_level != "high" and classification.intent_id in _spec_search_intents:
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
            _wants_content_only = bool(_medientyp) or classification.intent_id == "INT-W-03b"

            if spec_query:
                # 1. Primary tool — always a tool whose output parse_wlo_cards
                #    understands (topic_pages has its own format and is handled
                #    as an extra below to enrich collection cards with their
                #    topic-page URLs).
                if _wants_content_only:
                    spec_tool_name = "search_wlo_content"
                else:
                    # Generic / topic / collection / learning-path intent →
                    # start with collections (rich cards with preview/desc/chips)
                    spec_tool_name = "search_wlo_collections"

                spec_tool_args: dict[str, Any] = {
                    "query": spec_query, "maxResults": 10,
                }
                if _medientyp and spec_tool_name == "search_wlo_content":
                    spec_tool_args["learningResourceType"] = _medientyp
                if _fach:
                    spec_tool_args["discipline"] = _fach
                if _stufe:
                    spec_tool_args["educationalContext"] = _stufe
                spec_task = asyncio.create_task(
                    call_mcp_tool(spec_tool_name, spec_tool_args)
                )
                logger.info("speculative primary=%s for intent=%s args=%s",
                            spec_tool_name, classification.intent_id, spec_tool_args)

                # 2. Extra tools — fire in parallel to enrich the response.
                #    Rules:
                #      - topic-pages query → also run collections
                #      - generic search (no explicit type preference) → also run
                #        the complementary search so user sees both types
                #      - explicit content-search with generic intent → also collections
                _extras: list[str] = []
                if _wants_topic:
                    # User explicitly asked for topic pages → also fetch
                    # topic_pages-specific listing and merge its URLs onto
                    # whichever collection cards match (enriches them with
                    # the /topic-pages? link).
                    _extras.append("search_wlo_topic_pages")
                if not _wants_content_only and not _wants_samml \
                        and classification.intent_id in ("INT-W-03a", "INT-W-03c", "INT-W-10"):
                    # Truly generic search — also show content alongside collections
                    _extras.append("search_wlo_content")
                elif _wants_content_only and classification.intent_id in ("INT-W-03a", "INT-W-03c", "INT-W-10"):
                    # Content-primary but generic intent → still offer collections as context
                    _extras.append("search_wlo_collections")

                for extra_name in _extras:
                    if extra_name == spec_tool_name:
                        continue
                    extra_args: dict[str, Any] = {"query": spec_query, "maxResults": 5}
                    if _fach: extra_args["discipline"] = _fach
                    if _stufe: extra_args["educationalContext"] = _stufe
                    t = asyncio.create_task(call_mcp_tool(extra_name, extra_args))
                    extra_spec_tasks.append((extra_name, t))
                    logger.info("speculative extra=%s args=%s", extra_name, extra_args)
        except Exception as _e:
            logger.warning("speculative tool spawn failed: %s", _e)
            spec_task = None

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

    # Update entities based on turn type
    turn_type = classification.turn_type
    new_entities = classification.entities

    if turn_type == "topic_switch":
        session_state["entities"] = {}
    elif turn_type == "correction":
        for k, v in new_entities.items():
            if v:
                session_state["entities"][k] = v
    else:  # initial, follow_up, clarification
        for k, v in new_entities.items():
            if v:
                session_state["entities"][k] = v

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

    # ── Intent-Override: Create-Trigger (robust gegen Classifier-Drift) ──
    # Wenn der User klar ein Erstell-Verb ("Erstelle", "Mach mir ein", ...)
    # verwendet UND ein Material-Typ erkennbar ist (oder er bereits im
    # Canvas-State state-12 ist), overriden wir den Intent auf INT-W-11.
    # Das schuetzt den Canvas-Flow davor, dass der LLM-Classifier
    # "Erstelle mir ein Arbeitsblatt" faelschlich als INT-W-10
    # (Unterrichtsplanung) oder INT-W-03b (Suchen) bucht.
    _wants_create = looks_like_create_intent(req.message)
    _detected_mt = extract_material_type_from_message(req.message)
    _in_canvas_state = session_state.get("state_id") == "state-12"
    _existing_canvas_md = (
        (session_state.get("entities") or {}).get("_canvas_last_markdown") or ""
    )
    # ── Canvas-Edit-Override (INT-W-12) ──
    # Wenn Canvas aktiv ist UND vorhandener Canvas-Inhalt besteht UND eine
    # Edit-Formulierung erkannt wird UND KEIN expliziter "neues X"-Override
    # vorliegt, routen wir die Nachricht als EDIT an _handle_canvas_edit
    # (inline) statt eine neue Generierung zu starten.
    from app.services.canvas_service import (
        looks_like_edit_intent, has_explicit_new_create_override,
    )
    _wants_edit = (
        _in_canvas_state
        and bool(_existing_canvas_md)
        and looks_like_edit_intent(req.message)
        and not has_explicit_new_create_override(req.message)
    )
    if _wants_edit:
        logger.info(
            "Intent override: %s -> INT-W-12 (edit-verb in state-12, md_len=%d)",
            classification.intent_id, len(_existing_canvas_md),
        )
        classification.intent_id = "INT-W-12"
        new_state = "state-12"
        # Route to canvas_edit handler with current markdown + instruction
        edit_req = ChatRequest(
            session_id=req.session_id,
            message=req.message,
            action="canvas_edit",
            action_params={
                "current_markdown": _existing_canvas_md,
                "edit_instruction": req.message,
            },
            device=req.device,
            page=req.page,
        )
        return await _handle_canvas_edit(edit_req, session_state)

    # Soft-Create: wenn ein Material-Typ explizit genannt wird UND kein
    # klares Such-Verb im Text steht, treat es als Create-Wunsch.
    # Deckt typische Verwaltungs-/Politik-/Presse-Formulierungen ab:
    #   "Als Verwaltungskraft brauche ich einen Bericht zur OER-Lage"
    #   "Für die Pressemappe ein Factsheet"
    _search_verbs = get_search_verbs()
    _msg_low_override = (req.message or "").lower()
    # Position-based mixed-intent resolution: "Zeig … UND erstelle …" should
    # go to CREATE (second clause is the actionable one); "Erstelle … und
    # zeig dazu" should also go to CREATE. We look up the earliest index of
    # any create- vs search-verb and use the later one as the primary intent
    # (second clause wins — matches how Germans coordinate with "und/dann").
    def _first_index(needles: tuple[str, ...]) -> int:
        best = -1
        for n in needles:
            i = _msg_low_override.find(n)
            if i >= 0 and (best < 0 or i < best):
                best = i
        return best
    _search_pos = _first_index(_search_verbs)
    _create_pos = _first_index(get_create_triggers())
    _has_search_verb = _search_pos >= 0
    _has_create_verb = _create_pos >= 0
    # Decide primacy when BOTH verbs present:
    #   - if search comes AFTER create: create wins (typical "Erstelle X und zeig mir Beispiele")
    #   - if create comes AFTER search: create STILL wins (second clause is
    #     the actionable one — "Zeig Material UND erstelle Quiz")
    #   - if only search: search wins
    # => Rule: if create-verb is present at all, create wins over search.
    _search_blocks_soft_create = _has_search_verb and not _has_create_verb
    _soft_create = bool(_detected_mt) and not _search_blocks_soft_create
    if classification.intent_id != "INT-W-11":
        if (_wants_create or _soft_create) and (_detected_mt or _in_canvas_state):
            logger.info(
                "Intent override: %s -> INT-W-11 (create=%s search=%s mt=%s prior_state=%s)",
                classification.intent_id,
                _create_pos if _has_create_verb else None,
                _search_pos if _has_search_verb else None,
                _detected_mt, session_state.get("state_id"),
            )
            classification.intent_id = "INT-W-11"
            if _detected_mt and not (classification.entities or {}).get("material_typ"):
                if classification.entities is None:
                    classification.entities = {}
                classification.entities["material_typ"] = _detected_mt
            if new_state != "state-12":
                new_state = "state-12"
    # Regardless of whether the intent was overridden, keep session_state
    # entities in sync: the pattern engine reads material_typ from there.
    # If the classifier already chose INT-W-11 but didn't name a material
    # type, lift the heuristically detected one into entities as well.
    # ── State-12 Precondition-Guard ──
    # state-12 (Canvas-Arbeit) darf NUR mit INT-W-11/INT-W-12 aktiv sein UND
    # entweder vorhandener Canvas-Markdown ODER ein konkretes Thema (damit
    # die Canvas-Pane nicht durch Unsinn aktiviert wird). Sonst: auf state-5
    # zurücksetzen.
    if new_state == "state-12":
        _ent_now = session_state.get("entities", {}) or {}
        _has_md = bool(_ent_now.get("_canvas_last_markdown"))
        _has_topic = bool(
            _ent_now.get("_canvas_topic")
            or _ent_now.get("thema")
            or (classification.entities or {}).get("thema")
            or (classification.entities or {}).get("topic")
        )
        _canvas_intent = classification.intent_id in ("INT-W-11", "INT-W-12")
        if not _canvas_intent or not (_has_md or _has_topic):
            logger.info(
                "State-12 guard: dropping to state-5 (intent=%s has_md=%s has_topic=%s)",
                classification.intent_id, _has_md, _has_topic,
            )
            new_state = "state-5"

    if classification.intent_id == "INT-W-11":
        _mt_session = session_state.get("entities", {}).get("material_typ")
        _mt_class = (classification.entities or {}).get("material_typ")
        _chosen = _mt_session or _mt_class or _detected_mt
        if _chosen and session_state["entities"].get("material_typ") != _chosen:
            session_state["entities"]["material_typ"] = _chosen

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
    winner, pattern_output, scores, eliminated = select_pattern(
        persona_id=session_state["persona_id"],
        state_id=new_state,
        intent_id=classification.intent_id,
        signals=new_signals,
        page=env.get("page", "/"),
        device=env.get("device", "desktop"),
        entities=session_state["entities"],
        intent_confidence=classification.intent_confidence,
        enforced_pattern_id=safety.enforced_pattern or None,
    )
    tracer.end({"winner": winner.id, "eliminated": len(eliminated)})

    # 3b. Safety: strip blocked tools from the chosen pattern
    if safety.blocked_tools:
        if "tools" in pattern_output:
            pattern_output["tools"] = [
                t for t in pattern_output["tools"] if t not in safety.blocked_tools
            ]
        logger.info("Safety blocked tools: %s", safety.blocked_tools)
    if safety.enforced_pattern and winner.id == safety.enforced_pattern:
        logger.info("Safety enforced pattern active: %s", winner.id)

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
    _has_lp_intent = any(kw in _msg_lower for kw in _lp_keywords) or classification.intent_id == "INT-W-10"
    _last_contents_json = session_state.get("entities", {}).get("_last_contents", "")
    _last_collections_json = session_state.get("entities", {}).get("_last_collections", "")
    _lp_routed = False

    # Only route to LP builder if a concrete topic is known — fach alone is not enough
    _thema = session_state.get("entities", {}).get("thema", "")
    _lp_cards_collected: list[dict] = []  # cards found during LP content gathering

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
                # Only expose the cards the LLM actually referenced in the
                # path as tiles — the rest were candidates the LLM discarded.
                wlo_cards_raw = _filter_cards_used_in_text(
                    _lp_cards_collected, response_text or ""
                )
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
                response_text = (
                    f"Ich habe dir den **Lernpfad zu *{topic}*** im Canvas "
                    "rechts aufgebaut. Du kannst ihn dort drucken, als "
                    "Markdown speichern oder mir sagen, was angepasst "
                    "werden soll (z.B. *\"mach ihn für Klasse 5 einfacher\"* "
                    "oder *\"füge einen Schritt zur Sicherung hinzu\"*)."
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
    if not _lp_routed and classification.intent_id == "INT-W-11":
        _c_topic = (session_state.get("entities", {}).get("thema") or "").strip()
        _mt_raw = (
            (classification.entities or {}).get("material_typ")
            or session_state.get("entities", {}).get("material_typ")
            or ""
        )
        _mt_key = resolve_material_type(_mt_raw) or extract_material_type_from_message(req.message)

        # Topic-Fallback: wenn der Classifier kein 'thema' extrahiert hat,
        # aber Material-Typ bekannt ist, nutze die User-Message selbst als
        # Topic (nach Bereinigung: Create-Verben + Material-Typ-Wort raus).
        # Deckt analytische Anfragen ab, wo 'thema' oft komplex ist
        # ('OER-Lage in Deutschland', 'Vergleich WLO vs Schulbücher', etc.).
        if not _c_topic and _mt_key:
            import re as _re_topic
            _fallback = (req.message or "").strip()
            # strip leading create verbs
            _fallback = _re_topic.sub(
                r"^\s*(erstelle?|generiere?|mach(?:\s+mir)?|bau\s+mir|schreib\s+mir|"
                r"entwirf|produziere|ich\s+brauche|brauche|ich\s+möchte|möchte|"
                r"hätte\s+ger?n|gib\s+mir|kannst\s+du|fasse\s+zusammen|wandle)"
                r"\s+(mir\s+)?(ein|eine|einen)?\s*",
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
            _fallback = _re_topic.sub(r"\s+", " ", _fallback).strip(" .,:;")
            # Cap at 80 chars to avoid weirdly long topics
            _c_topic = _fallback[:80]
            if _c_topic:
                logger.info("canvas-create topic fallback: %r", _c_topic)

        if _c_topic and _mt_key:
            _mts_flow = get_material_types()
            _label = _mts_flow[_mt_key]["label"]
            _emoji = _mts_flow[_mt_key]["emoji"]
            _title, _md = await generate_canvas_content(
                topic=_c_topic,
                material_type_key=_mt_key,
                session_state=session_state,
                memory_context=memory_context,
            )
            response_text = (
                f"Ich habe dir ein **{_label}** zum Thema *{_c_topic}* erstellt — "
                f"schau es dir im Canvas an. Schreib mir einfach, was ich anpassen soll."
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
        spec_blocked = (
            spec_tool_name in (safety.blocked_tools or [])
            or _pat_forbids_mcp
            or _pat_wants_no_tools
            or _lp_routed  # LP path ran its own MCP logic, discard spec
            or _canvas_routed  # Canvas-create doesn't need search results
            or _degradation_blocks  # Missing thema → ask first, don't search
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

    if not _lp_routed and not _canvas_routed:
        tracer.start("response", "LLM response generation")
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
            canvas_state=req.canvas_state,
        )
        tracer.end({
            "tools": tools_called,
            "outcomes": len(response_outcomes),
            "prefetch": bool(prefetched_tool_payload),
        })

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
    #     The edu-sharing preview endpoint accepts just the nodeId.
    _PREVIEW_BASE = (
        "https://redaktion.openeduhub.net/edu-sharing/preview"
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

    # Build pagination info so frontend knows to limit display
    pagination = None
    if len(cards) > PAGE_SIZE:
        pagination = PaginationInfo(
            total_count=len(cards),
            skip_count=0,
            page_size=PAGE_SIZE,
            has_more=True,
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
    if _canvas_forced_quick_replies:
        quick_replies = _canvas_forced_quick_replies
    elif follow_up_mode != "none":
        quick_replies = await generate_quick_replies(
            message=req.message,
            response_text=response_text,
            classification=classification_dict,
            session_state=session_state,
        )
    else:
        quick_replies = []

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
        # Widget-Kontext dominiert: wenn das Frontend den WidgetComponent
        # verwendet (egal auf welcher Seite es embeddet ist), markiert es
        # sich via page_context.widget=true. Dann gehen Kacheln immer ins
        # Canvas — unabhaengig von env.page. Die alte Host-Page-Erkennung
        # bleibt nur fuer echte Direct-Integrationen (WLO-Suche ohne Widget).
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
        },
        # Triple-Schema v2
        outcomes=response_outcomes,
        safety=safety,
        confidence=final_confidence,
        policy=policy,
        context=context_snapshot,
        trace=tracer.entries,
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

    # Save bot message
    await save_message(
        req.session_id, "assistant", response_text,
        cards=[c.model_dump() for c in cards],
        debug=debug.model_dump(),
    )

    # 12. Quality logging (non-blocking, fire-and-forget)
    try:
        from app.services.config_loader import load_quality_log_config
        _ql_cfg = (load_quality_log_config().get("logging") or {})
        if _ql_cfg.get("enabled", True):
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

    return ChatResponse(
        session_id=req.session_id,
        content=response_text,
        cards=cards,
        follow_up=pattern_output.get("format_follow_up", "quick_replies"),
        quick_replies=quick_replies,
        debug=debug,
        page_action=page_action,
        pagination=pagination,
    )


@router.get("/stream")
async def chat_stream():
    """SSE endpoint for streaming responses (future use)."""
    async def event_stream():
        yield "data: {\"type\": \"connected\"}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")
