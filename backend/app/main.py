"""BadBoerdi Backend — FastAPI application."""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.services.auth import require_studio_key
from app.services.database import init_db
from app.routers import chat, config, rag, speech, sessions, safety, widget

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    import logging

    await init_db()

    # Background: generate embeddings for seed chunks (non-blocking)
    async def _embed_seed_chunks():
        try:
            from app.routers.rag import embed_missing
            result = await embed_missing()
            if result.get("embedded", 0) > 0:
                logging.getLogger("startup").info(
                    "Generated embeddings for %d seed chunks", result["embedded"]
                )
        except Exception as e:
            logging.getLogger("startup").warning("Seed embedding skipped: %s", e)

    asyncio.create_task(_embed_seed_chunks())
    yield


app = FastAPI(
    title="BadBoerdi API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
app.include_router(config.router, prefix="/api/config", tags=["config"], dependencies=_studio_deps)
app.include_router(rag.router,    prefix="/api/rag",    tags=["rag"],    dependencies=_studio_deps)
app.include_router(safety.router, prefix="/api/safety", tags=["safety"], dependencies=_studio_deps)


@app.get("/api/health")
async def health():
    from app.services.llm_provider import get_chat_model, get_embed_model, get_provider
    return {
        "status": "ok",
        "provider": get_provider(),
        "chat_model": get_chat_model(),
        "embed_model": get_embed_model(),
    }


@app.get("/api/debug/mcp-test")
async def mcp_test():
    """Test MCP connection directly."""
    from app.services.mcp_client import call_mcp_tool, parse_wlo_cards, _session_id, _initialized
    try:
        result = await call_mcp_tool("search_wlo_collections", {"query": "Mathematik"})
        cards = parse_wlo_cards(result)
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
