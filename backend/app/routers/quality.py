"""Quality router — exposes quality/analytics logs and stats to the Studio."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.auth import require_studio_key
from app.services.database import (
    get_quality_logs, get_quality_stats,
    get_tight_races_breakdown,
    get_degradation_breakdown,
    get_empty_entities_breakdown,
    get_low_confidence_turns,
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
    scope: str = Query("all", description="'all' | 'production' | 'eval'"),
):
    """Return recent quality log entries.

    Query params:
      limit: max rows (default 100)
      session_id: filter to a single session
      pattern_id: filter by pattern (prefix match, e.g. "PAT-10")
      intent_id: filter by intent (prefix match, e.g. "INT-W-06")
      scope: 'all' / 'production' / 'eval' — excludes eval-* sessions from
             production view and vice versa
    """
    rows = await get_quality_logs(
        limit=limit, session_id=session_id,
        pattern_id=pattern_id, intent_id=intent_id,
        scope=scope,
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
    scope: str = Query("all", description="'all' | 'production' | 'eval'"),
    confirm: bool = False,
):
    """Bulk-delete quality logs by filter.

    Without any filter AND scope='all' this deletes ALL logs — require explicit
    confirm=true in that case to avoid accidental nukes from dev tooling.
    With scope='eval' or 'production', deletes within that scope without confirm.
    """
    has_filter = any([session_id, pattern_id, intent_id, scope != "all"])
    if not has_filter and not confirm:
        raise HTTPException(
            status_code=400,
            detail=(
                "Bulk-delete ohne Filter und ohne Scope verlangt ?confirm=true — "
                "das wuerde ALLE Quality-Logs loeschen."
            ),
        )
    n = await clear_quality_logs(
        session_id=session_id, pattern_id=pattern_id, intent_id=intent_id,
        scope=scope,
    )
    return {
        "status": "cleared",
        "deleted": n,
        "filter": {
            "session_id": session_id, "pattern_id": pattern_id,
            "intent_id": intent_id, "scope": scope,
        },
    }


@router.get("/stats")
async def quality_stats(
    scope: str = Query("all", description="'all' | 'production' | 'eval'"),
):
    """Aggregate quality metrics for offline analysis.

    Returns:
      - scope: echoes the applied scope filter
      - total_turns: number of logged turns in scope
      - pattern_distribution: {pattern_id: count}
      - intent_distribution: {intent_id: count}
      - avg_confidence: average final confidence
      - avg_score_gap: average gap between winner and runner-up
      - degradation_rate: fraction of turns with degradation
      - tight_races: turns where score_gap < 0.02
      - empty_entity_rate: fraction of turns with no entities
      - avg_response_length: average response character count
    """
    return await get_quality_stats(scope=scope)


@router.get("/tight-races")
async def tight_races(
    scope: str = Query("all", description="'all' | 'production' | 'eval'"),
    threshold: float = Query(0.02, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=500),
):
    """Actionable tight-race diagnostics — which pattern pairs keep colliding.

    Returns a list of (winner, runner_up) pairs ordered by collision count,
    each with an example message so admins can see WHERE the ambiguity occurs.
    """
    return await get_tight_races_breakdown(
        scope=scope, threshold=threshold, limit=limit,
    )


@router.get("/degradations")
async def degradations(
    scope: str = Query("all", description="'all' | 'production' | 'eval'"),
    limit: int = Query(50, ge=1, le=500),
):
    """Degradation-Diagnostics — which (pattern × missing-slot)-Kombinationen
    lösen am häufigsten den Fallback auf eine einfachere Antwort aus.

    Zeigt für jede Gruppe die Anzahl + Beispielnachricht.
    """
    return await get_degradation_breakdown(scope=scope, limit=limit)


@router.get("/empty-entities")
async def empty_entities(
    scope: str = Query("all", description="'all' | 'production' | 'eval'"),
    limit: int = Query(50, ge=1, le=500),
):
    """Empty-Entity-Diagnostics — bei welchen Intents schlägt die Entity-
    Extraktion konsistent fehl. Normal für Smalltalk, problematisch für
    content-Intents.
    """
    return await get_empty_entities_breakdown(scope=scope, limit=limit)


@router.get("/low-confidence")
async def low_confidence(
    scope: str = Query("all", description="'all' | 'production' | 'eval'"),
    max_confidence: float = Query(0.60, ge=0.0, le=1.0),
    limit: int = Query(30, ge=1, le=200),
):
    """Turns below a confidence threshold, sorted worst-first. Zeigt
    konkrete Nachrichten, bei denen der Classifier unsicher war — hilft,
    Input-Muster zu erkennen, die zu schärfen sind.
    """
    return await get_low_confidence_turns(
        scope=scope, max_confidence=max_confidence, limit=limit,
    )
