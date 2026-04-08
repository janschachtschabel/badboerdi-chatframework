"""Sessions router — manage user sessions, history, and memory."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends

from app.services.auth import require_studio_key
from app.services.database import (
    get_or_create_session, get_messages, get_memory, save_memory,
)

router = APIRouter()

# Routes that should require an API key when STUDIO_API_KEY is set.
# Note: GET /{session_id}/messages is intentionally LEFT OPEN — the embedded
# chat widget calls it on every page load to restore conversation history.
_studio = [Depends(require_studio_key)]


@router.get("/{session_id}", dependencies=_studio)
async def get_session(session_id: str):
    """Get session state."""
    session = await get_or_create_session(session_id)
    return {
        "session_id": session["session_id"],
        "persona_id": session.get("persona_id", ""),
        "state_id": session.get("state_id", "state-1"),
        "entities": json.loads(session.get("entities", "{}")),
        "signal_history": json.loads(session.get("signal_history", "[]")),
        "turn_count": session.get("turn_count", 0),
    }


@router.get("/{session_id}/messages")
async def get_session_messages(session_id: str, limit: int = 50):
    """Get message history for a session."""
    return await get_messages(session_id, limit)


@router.get("/{session_id}/memory", dependencies=_studio)
async def get_session_memory(session_id: str, memory_type: str | None = None):
    """Get memory entries for a session."""
    return await get_memory(session_id, memory_type)


@router.post("/{session_id}/memory", dependencies=_studio)
async def set_session_memory(session_id: str, key: str, value: str,
                              memory_type: str = "short"):
    """Save a memory entry."""
    await save_memory(session_id, key, value, memory_type)
    return {"status": "saved", "key": key, "memory_type": memory_type}


@router.get("/", dependencies=_studio)
async def list_sessions():
    """List all sessions."""
    import aiosqlite
    from app.services.database import DB_PATH

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT session_id, persona_id, state_id, turn_count, created_at, updated_at "
            "FROM sessions ORDER BY updated_at DESC LIMIT 100"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
