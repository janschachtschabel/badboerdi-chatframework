"""Quality router — exposes quality/analytics logs and stats to the Studio."""

from __future__ import annotations

from fastapi import APIRouter

from app.services.database import get_quality_logs, get_quality_stats

router = APIRouter()


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
