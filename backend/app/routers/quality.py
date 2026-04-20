"""Quality router — exposes quality/analytics logs and stats to the Studio."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.services.auth import require_studio_key
from app.services.database import (
    get_quality_logs, get_quality_stats,
    delete_quality_log, clear_quality_logs,
)

router = APIRouter()

_studio = [Depends(require_studio_key)]


@router.get("/logs")
async def list_quality_logs(
    limit: int = 100,
    session_id: str = "",
    pattern_id: str = "",
    intent_id: str = "",
):
    """Return recent quality log entries.

    Query params:
      limit: max rows (default 100)
      session_id: filter to a single session
      pattern_id: filter by pattern (prefix match, e.g. "PAT-10")
      intent_id: filter by intent (prefix match, e.g. "INT-W-06")
    """
    rows = await get_quality_logs(
        limit=limit, session_id=session_id,
        pattern_id=pattern_id, intent_id=intent_id,
    )
    return {"count": len(rows), "logs": rows}


@router.delete("/logs/{log_id}", dependencies=_studio)
async def delete_quality_log_endpoint(log_id: int):
    """Delete a single quality log entry by id."""
    n = await delete_quality_log(log_id)
    if n == 0:
        raise HTTPException(status_code=404, detail="log not found")
    return {"status": "deleted", "id": log_id}


@router.post("/logs/clear", dependencies=_studio)
async def clear_quality_logs_endpoint(
    session_id: str = "",
    pattern_id: str = "",
    intent_id: str = "",
    confirm: bool = False,
):
    """Bulk-delete quality logs by filter.

    Without any filter this deletes ALL logs — require explicit confirm=true
    in that case to avoid accidental nukes from dev tooling.
    """
    if not any([session_id, pattern_id, intent_id]) and not confirm:
        raise HTTPException(
            status_code=400,
            detail=(
                "Bulk-delete ohne Filter verlangt ?confirm=true — "
                "das wuerde ALLE Quality-Logs loeschen."
            ),
        )
    n = await clear_quality_logs(
        session_id=session_id, pattern_id=pattern_id, intent_id=intent_id,
    )
    return {
        "status": "cleared",
        "deleted": n,
        "filter": {
            "session_id": session_id, "pattern_id": pattern_id,
            "intent_id": intent_id,
        },
    }


@router.get("/stats")
async def quality_stats():
    """Aggregate quality metrics for offline analysis.

    Returns:
      - total_turns: number of logged turns
      - pattern_distribution: {pattern_id: count}
      - intent_distribution: {intent_id: count}
      - avg_confidence: average final confidence
      - avg_score_gap: average gap between winner and runner-up
      - degradation_rate: fraction of turns with degradation
      - tight_races: turns where score_gap < 0.02
      - empty_entity_rate: fraction of turns with no entities
      - avg_response_length: average response character count
    """
    return await get_quality_stats()
