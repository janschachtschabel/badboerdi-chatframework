"""Context layer (T-04/05 from Triple-Schema v2).

Builds a formalised ContextSnapshot from raw inputs (env, session, history,
classification). Centralises what was previously scattered in chat.py.
"""

from __future__ import annotations

from typing import Any

from app.models.schemas import ContextSnapshot


def build_context(
    env: dict[str, Any],
    session_state: dict[str, Any],
    classification: Any | None = None,
    memories: list[dict] | None = None,
) -> ContextSnapshot:
    """Aggregate request inputs into a single ContextSnapshot."""
    snap = ContextSnapshot(
        page=env.get("page", "/"),
        device=env.get("device", "desktop"),
        locale=env.get("locale", "de-DE"),
        session_duration=int(env.get("session_duration", 0) or 0),
        turn_count=int(session_state.get("turn_count", 0) or 0),
        entities={
            k: v for k, v in (session_state.get("entities") or {}).items()
            if not k.startswith("_")  # hide internal scratchpad keys
        },
        recent_signals=list((session_state.get("signal_history") or [])[-10:]),
        memory_keys=[m.get("key", "") for m in (memories or [])][:10],
    )
    if classification is not None:
        snap.last_intent = getattr(classification, "intent_id", "") or ""
        snap.last_state = getattr(classification, "next_state", "") or ""
    return snap
