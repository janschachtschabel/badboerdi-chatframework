"""BadBoerdi Backend — FastAPI application."""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.services.auth import require_studio_key
from app.services.database import init_db
from app.routers import chat, config, rag, speech, sessions, safety, quality, widget, eval as eval_router, routing_rules

load_dotenv()

# Configure root logging so INFO-level messages (warmup, safety timings,
# quality logs) are actually emitted. Override with LOG_LEVEL env var.
_log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    import logging
    import time

    log = logging.getLogger("startup")

    # Warn if Studio API key is not configured (all admin endpoints unprotected)
    if not (os.getenv("STUDIO_API_KEY") or "").strip():
        log.warning(
            "⚠ STUDIO_API_KEY is not set — all Studio/admin endpoints are UNPROTECTED. "
            "Set STUDIO_API_KEY in your environment for production deployments."
        )

    await init_db()

    # Sweep any 'running' eval_runs rows from a previous (crashed or killed)
    # backend process. A running row at startup is by definition orphaned —
    # its asyncio task cannot have survived a process restart.
    try:
        from app.services.eval_service import sweep_orphaned_runs
        await sweep_orphaned_runs()
    except Exception as e:
        log.debug("eval sweep skipped: %s", e)

    # Background: generate embeddings for seed chunks (non-blocking)
    async def _embed_seed_chunks():
        try:
            from app.routers.rag import embed_missing
            result = await embed_missing()
            if result.get("embedded", 0) > 0:
                log.info("Generated embeddings for %d seed chunks", result["embedded"])
        except Exception as e:
            log.warning("Seed embedding skipped: %s", e)

    # Background: preload all YAML configs into the mtime-cache
    # → First request skips ~5-20 ms of YAML parsing.
    async def _warmup_configs():
        try:
            t0 = time.perf_counter()
            from app.services import config_loader as cl
            cl.load_safety_config()
            cl.load_policy_config()
            cl.load_rag_config()
            cl.load_intents()
            cl.load_states()
            cl.load_entities()
            cl.load_persona_definitions()
            cl.load_device_config()
            cl.load_domain_rules()
            try:
                cl.load_quality_log_config()
            except Exception:
                pass
            log.info("Config warmup done in %.0fms", (time.perf_counter() - t0) * 1000)
        except Exception as e:
            log.warning("Config warmup skipped: %s", e)

    # Background: pre-initialise the OpenAI client + httpx connection pool and
    # send one cheap moderation ping so the first real chat turn does not pay
    # ~2-5 s of TLS handshake + DNS + client construction cost.
    async def _warmup_llm():
        try:
            t0 = time.perf_counter()
            from app.services.llm_provider import get_client, get_moderation_client
            client = get_client()
            # Fire-and-forget moderation ping — tiny, free, warms the connection.
            # Uses the dedicated moderation client so it works on b-api setups
            # too (when OPENAI_API_KEY is provided alongside).
            mod = get_moderation_client()
            if mod is not None:
                try:
                    await asyncio.wait_for(
                        mod.moderations.create(
                            model="omni-moderation-latest",
                            input="warmup",
                        ),
                        timeout=10.0,
                    )
                except Exception as e:
                    log.debug("LLM warmup moderation ping failed: %s", e)
            log.info("LLM warmup done in %.0fms", (time.perf_counter() - t0) * 1000)
        except Exception as e:
            log.warning("LLM warmup skipped: %s", e)

    # Background: preload the RAG cross-encoder reranker (ONNX int8,
    # ~130 MB) so the first real chat turn doesn't pay the ~1-1.5 s
    # model-load + first-inference cost.
    async def _warmup_reranker():
        try:
            from app.services.rag_service import warmup_reranker
            await warmup_reranker()
        except Exception as e:
            log.warning("Reranker warmup skipped: %s", e)

    # All background tasks run concurrently; none blocks request acceptance.
    asyncio.create_task(_embed_seed_chunks())
    asyncio.create_task(_warmup_configs())
    asyncio.create_task(_warmup_llm())
    asyncio.create_task(_warmup_reranker())
    yield


app = FastAPI(
    title="BadBoerdi API",
    version="0.1.0",
    lifespan=lifespan,
)

_cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=("*" not in _cors_origins),  # credentials only with specific origins
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health endpoint ──────────────────────────────────────────────────
# Used by the Docker HEALTHCHECK (and any external load balancer) to
# verify the worker is alive. Intentionally simple — return 200 as soon
# as FastAPI accepts requests. We don't gate on DB / RAG / LLM warmup
# because the warmup tasks run in the background and a "warming up"
# instance can still serve cached chats; making /health depend on them
# would cause unnecessary container restarts during the first 1–2s.
@app.get("/health", tags=["health"])
@app.head("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}

# Public routers — chat, speech, widget + sessions (so the embedded widget
# can restore its history via GET /api/sessions/{id}/messages without an
# API key). Per-route protection inside sessions.py covers the sensitive
# read/write endpoints.
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(speech.router, prefix="/api/speech", tags=["speech"])
app.include_router(widget.router, prefix="/widget", tags=["widget"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])

# Studio-only routers — protected when STUDIO_API_KEY is set in the env.
# Without the env var, the dependency is a no-op (open by default).
_studio_deps = [Depends(require_studio_key)]
app.include_router(config.router,  prefix="/api/config",  tags=["config"],  dependencies=_studio_deps)
app.include_router(rag.router,     prefix="/api/rag",     tags=["rag"],     dependencies=_studio_deps)
app.include_router(safety.router,  prefix="/api/safety",  tags=["safety"],  dependencies=_studio_deps)
app.include_router(quality.router, prefix="/api/quality", tags=["quality"], dependencies=_studio_deps)
app.include_router(routing_rules.router, prefix="/api/routing-rules", tags=["routing-rules"], dependencies=_studio_deps)
# Eval router brings its own /api/eval prefix and per-endpoint Studio guards
app.include_router(eval_router.router)


# ── Static assets ────────────────────────────────────────────────
# Public assets (logos, icons) served from app/static/. Cached via standard
# Cache-Control. Used by the embeddable widget — when bundled in third-party
# pages, the widget needs a stable absolute URL for its avatar/logo.
#   /api/static/boerdi.svg   → blue Boerdi owl logo (master asset)
from pathlib import Path as _Path
from fastapi.staticfiles import StaticFiles as _StaticFiles
_STATIC_DIR = _Path(__file__).parent / "static"
if _STATIC_DIR.exists():
    app.mount(
        "/api/static",
        _StaticFiles(directory=str(_STATIC_DIR), check_dir=False),
        name="static",
    )


@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/api/health")


@app.api_route("/api/health", methods=["GET", "HEAD"])
async def health():
    from app.services.llm_provider import (
        get_chat_model, get_embed_model, get_provider,
        supports_gpt5_params, get_verbosity, get_reasoning_effort,
    )
    model = get_chat_model()
    info: dict = {
        "status": "ok",
        "provider": get_provider(),
        "chat_model": model,
        "embed_model": get_embed_model(),
        "gpt5_params_active": supports_gpt5_params(model),
    }
    if info["gpt5_params_active"]:
        info["verbosity"] = get_verbosity()
        info["reasoning_effort"] = get_reasoning_effort()
    return info


@app.get("/api/debug/mcp-test", dependencies=[Depends(require_studio_key)])
async def mcp_test():
    """Test MCP connection directly."""
    from app.services.mcp_client import call_mcp_tool, parse_wlo_cards, resolve_discipline_labels, _session_id, _initialized
    try:
        result = await call_mcp_tool("search_wlo_collections", {"query": "Mathematik"})
        cards = parse_wlo_cards(result)
        await resolve_discipline_labels(cards)
        return {
            "status": "ok",
            "session_id": _session_id,
            "initialized": _initialized,
            "result_length": len(result),
            "result_preview": result[:300],
            "cards_count": len(cards),
            "cards": cards[:2],
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "session_id": _session_id, "initialized": _initialized}
