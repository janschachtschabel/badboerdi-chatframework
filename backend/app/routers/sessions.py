"""Sessions router — manage user sessions, history, and memory."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from app.services.auth import require_studio_key
from app.services.database import (
    get_or_create_session, get_messages, get_memory, save_memory,
    delete_session as db_delete_session,
    delete_messages_for_session as db_delete_messages,
    purge_all as db_purge_all,
)

router = APIRouter()

# Routes that should require an API key when STUDIO_API_KEY is set.
# Note: GET /{session_id}/messages is intentionally LEFT OPEN — the embedded
# chat widget calls it on every page load to restore conversation history.
_studio = [Depends(require_studio_key)]


# ── STATIC routes FIRST ───────────────────────────────────────────
# These must be registered BEFORE the /{session_id}-dynamic routes,
# otherwise FastAPI/Starlette matches them as session_id="purge" (etc.)
# and returns 405 because the dynamic route doesn't support the method.

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


@router.post("/purge", dependencies=_studio)
async def purge_sessions(
    messages: bool = True,
    memory: bool = True,
    quality_logs: bool = True,
    safety_logs: bool = False,
    sessions: bool = False,
    confirm: bool = False,
):
    """Bulk-delete chat-related rows across ALL sessions.

    Query params (all default to a sensible subset):
      messages:     drop every row in `messages` (default true)
      memory:       drop every row in `memory` (default true)
      quality_logs: drop every row in `quality_logs` (default true)
      safety_logs:  ALSO drop safety logs (default false — kept for audit)
      sessions:     ALSO drop session rows (default false — keeps personas,
                    state_id, entities so ongoing users aren't disconnected)
      confirm:      must be ``true`` to actually run. Prevents accidental
                    calls from dev tooling or misconfigured scripts.

    Returns row counts per table.
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail=(
                "Purge verlangt ?confirm=true als Schutz gegen versehentliche "
                "Nukes. Das Studio schickt den Parameter nach der "
                "Doppel-Bestaetigung automatisch."
            ),
        )
    counts = await db_purge_all(
        messages=messages, memory=memory, quality_logs=quality_logs,
        safety_logs=safety_logs, sessions=sessions,
    )
    return {"status": "purged", "deleted": counts}


# ── Dynamic routes ────────────────────────────────────────────────

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
    """Save a memory entry.

    Honors 01-base/privacy-config.yaml: when ``logging.memory`` is false,
    the write is silently dropped (HTTP 200 with ``persisted=false``).
    """
    try:
        from app.services.config_loader import load_privacy_config
        if not load_privacy_config().get("memory", True):
            return {
                "status": "skipped",
                "persisted": False,
                "key": key,
                "reason": "memory logging disabled in privacy-config",
            }
    except Exception:
        pass
    await save_memory(session_id, key, value, memory_type)
    return {"status": "saved", "persisted": True, "key": key, "memory_type": memory_type}


@router.delete("/{session_id}", dependencies=_studio)
async def delete_session_endpoint(session_id: str):
    """Fully delete a session: messages, memory, quality logs, safety logs,
    and the session row itself. Returns per-table row counts."""
    counts = await db_delete_session(session_id)
    return {"status": "deleted", "session_id": session_id, "deleted": counts}


@router.delete("/{session_id}/messages", dependencies=_studio)
async def delete_session_messages_endpoint(session_id: str):
    """Delete only the chat messages (keep session + memory + logs).
    Useful to reset a conversation while preserving analytics."""
    n = await db_delete_messages(session_id)
    return {"status": "cleared", "session_id": session_id, "deleted_messages": n}
