"""Chat router — main conversation endpoint with 3-phase pattern engine."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

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
from app.services.mcp_client import call_mcp_tool, parse_wlo_cards, parse_total_count
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
def _build_cards(raw: list[dict]) -> list[WloCard]:
    cards = []
    for c in raw:
        cards.append(WloCard(
            node_id=c.get("node_id", ""),
            title=c.get("title", ""),
            description=c.get("description", ""),
            disciplines=c.get("disciplines", []),
            educational_contexts=c.get("educational_contexts", []),
            keywords=c.get("keywords", []),
            learning_resource_types=c.get("learning_resource_types", []),
            url=c.get("url", ""),
            wlo_url=c.get("wlo_url", ""),
            preview_url=c.get("preview_url", ""),
            license=c.get("license", ""),
            publisher=c.get("publisher", ""),
            node_type=c.get("node_type", "content"),
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
        total_from_mcp = parse_total_count(result_text)

        # Mark as content items (not collections)
        for c in cards_raw:
            c.setdefault("node_type", "content")

        # Determine if there are more items
        has_more = len(cards_raw) > PAGE_SIZE
        display_cards_raw = cards_raw[:PAGE_SIZE]
        cards = _build_cards(display_cards_raw)

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

    return ChatResponse(
        session_id=req.session_id,
        content=response_text,
        cards=cards,
        quick_replies=quick_replies,
        debug=debug,
        pagination=pagination,
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

        # Mark these node_ids as used so the next LP varies
        _add_used_lp_ids(session_state, [c.get("node_id", "") for c in cards_raw])

        cards = _build_cards(cards_raw)

    except Exception as e:
        logger.error("generate_learning_path error: %s", e)
        cards = []
        response_text = f'Fehler beim Erstellen des Lernpfads fuer "{title}": {e}'
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
    # Persist updated entities (incl. _lp_used_node_ids)
    await update_session(
        req.session_id,
        entities=json.dumps(session_state.get("entities", {})),
    )

    return ChatResponse(
        session_id=req.session_id,
        content=response_text,
        cards=cards,
        quick_replies=quick_replies,
        debug=debug,
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

    # Inject page_context entities (node_id, collection_id, search_query)
    page_ctx = env.get("page_context", {})
    for key in ("node_id", "collection_id", "search_query"):
        if page_ctx.get(key):
            session_state["entities"][key] = page_ctx[key]

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
            classify_input(req.message, history, session_state, env)
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

    if safety.risk_level != "high" and classification.intent_id in _spec_search_intents:
        try:
            spec_query = _spec_query_from_classification()
            if spec_query:
                if classification.intent_id == "INT-W-03b":
                    spec_tool_name = "search_wlo_content"
                else:
                    spec_tool_name = "search_wlo_collections"
                spec_tool_args = {"query": spec_query, "maxItems": 5, "skipCount": 0}
                spec_task = asyncio.create_task(
                    call_mcp_tool(spec_tool_name, spec_tool_args)
                )
                logger.info("speculative %s for intent=%s query=%r",
                            spec_tool_name, classification.intent_id, spec_query)
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
    )
    tracer.end({"winner": winner.id, "eliminated": len(eliminated)})

    # 3b. Safety override: enforced pattern + tool blocking
    if safety.blocked_tools:
        # Remove blocked tools from pattern output
        if "tools" in pattern_output:
            pattern_output["tools"] = [
                t for t in pattern_output["tools"] if t not in safety.blocked_tools
            ]
        logger.info("Safety blocked tools: %s", safety.blocked_tools)
    if safety.enforced_pattern:
        logger.info("Safety enforced pattern: %s", safety.enforced_pattern)
        # Override pattern_output with safety-mandated style
        pattern_output["tone"] = "empathisch"
        pattern_output["length"] = "kurz"
        pattern_output["tools"] = []  # No tool calls in crisis

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
    print(f"[LP-DEBUG] intent={_has_lp_intent}, msg='{_msg_lower[:60]}', contents={bool(_last_contents_json)}, collections={bool(_last_collections_json)}", flush=True)

    if _has_lp_intent:
        from app.services.llm_service import generate_learning_path_text
        contents_text = ""
        topic = session_state.get("entities", {}).get("thema", req.message)
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
                print(f"[LP-DEBUG] Topic switch detected → fresh search for '{topic}'", flush=True)

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
                print(f"[LP-DEBUG] Priority 3: searching topic='{topic}' skip={_search_skip}", flush=True)
                try:
                    search_result = await call_mcp_tool("search_wlo_collections", {
                        "query": topic, "maxItems": 5, "skipCount": _search_skip,
                    })
                    search_cards = parse_wlo_cards(search_result)
                    print(f"[LP-DEBUG] Found {len(search_cards)} collections", flush=True)
                    if not search_cards and _search_skip > 0:
                        # Pagination exhausted → reset and refetch
                        _search_skip = 0
                        _lp_reset = True
                        search_result = await call_mcp_tool("search_wlo_collections", {
                            "query": topic, "maxItems": 5, "skipCount": 0,
                        })
                        search_cards = parse_wlo_cards(search_result)
                    if search_cards:
                        all_lines: list[str] = []
                        tools_called = [f"search_wlo_collections ({topic[:30]})"]
                        topic = search_cards[0].get("title", topic)
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
                                # Diversity filter: drop already-used items
                                fresh_cards = [c for c in col_cards
                                               if c.get("node_id") and c["node_id"] not in _lp_used]
                                if not fresh_cards and col_cards:
                                    fresh_cards = col_cards  # exhausted → use all, will reset later
                                    _lp_reset = True
                                if fresh_cards:
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
                                print(f"[LP-DEBUG] FAILED for '{col_title}': {e}", flush=True)
                        if all_lines:
                            contents_text = "\n".join(all_lines)
                            tools_called.append("generate_learning_path")
                            # Advance skipCount for next LP request on same topic
                            session_state.setdefault("entities", {})[_topic_key] = _search_skip + 3
                except Exception as e:
                    logger.warning("Failed to search+fetch collections for LP: %s", e)

            print(f"[LP-DEBUG] contents_text={len(contents_text) if contents_text else 0} chars, topic='{topic}'", flush=True)
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
                wlo_cards_raw = []
                _lp_routed = True

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Learning path from history failed: %s", e)

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
        spec_blocked = (
            spec_tool_name in (safety.blocked_tools or [])
            or _pat_forbids_mcp
            or _pat_wants_no_tools
            or _lp_routed  # LP path ran its own MCP logic, discard spec
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

    if not _lp_routed:
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

    # Triple-Schema T-25/27: feedback from outcomes
    from app.services.outcome_service import adjust_confidence, derive_state_hint
    final_confidence = adjust_confidence(classification.intent_confidence, response_outcomes)
    state_hint = derive_state_hint(response_outcomes)
    if state_hint and state_hint != new_state:
        logger.info("Outcome-based state hint: %s -> %s", new_state, state_hint)
        new_state = state_hint

    # 7. Build WloCard objects — send all, frontend limits display
    all_cards_raw = wlo_cards_raw
    cards = _build_cards(all_cards_raw)

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
            content_refs.append({
                "node_id": c["node_id"],
                "title": c.get("title", ""),
                "description": (c.get("description") or "")[:200],
                "url": c.get("url", ""),
                "learning_resource_types": c.get("learning_resource_types", []),
            })
    if collection_refs:
        session_state["entities"]["_last_collections"] = json.dumps(
            collection_refs[:10]
        )
    if content_refs:
        session_state["entities"]["_last_contents"] = json.dumps(
            content_refs[:15]
        )

    # 8. Generate AI quick replies (always, 4 context-aware suggestions)
    quick_replies = await generate_quick_replies(
        message=req.message,
        response_text=response_text,
        classification=classification_dict,
        session_state=session_state,
    )

    # 9. Build page_action for host page integration
    page_action = None
    if cards and env.get("page") in ("/suche", "/startseite", "/"):
        page_action = {
            "action": "show_results",
            "payload": {
                "cards": [c.model_dump() for c in cards[:pattern_output.get("max_items", 5)]],
                "query": session_state["entities"].get("thema", req.message),
            },
        }

    # 10. Debug info
    debug = DebugInfo(
        persona=session_state["persona_id"],
        intent=classification.intent_id,
        state=new_state,
        signals=new_signals,
        pattern=f"{winner.id} ({winner.label})",
        entities=session_state["entities"],
        tools_called=tools_called,
        phase1_eliminated=eliminated,
        phase2_scores=scores,
        phase3_modulations={
            "tone": pattern_output.get("tone"),
            "formality": pattern_output.get("formality"),
            "length": pattern_output.get("length"),
            "max_items": pattern_output.get("max_items"),
            "skip_intro": pattern_output.get("skip_intro"),
            "degradation": pattern_output.get("degradation", False),
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

    return ChatResponse(
        session_id=req.session_id,
        content=response_text,
        cards=cards,
        follow_up=pattern_output.get("format_follow_up", "none"),
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
