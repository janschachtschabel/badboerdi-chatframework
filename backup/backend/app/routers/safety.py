"""Safety router — exposes safety logs and rate-limit status to the Studio."""

from __future__ import annotations

from fastapi import APIRouter

from app.services.database import get_safety_logs

router = APIRouter()


@router.get("/logs")
async def list_safety_logs(
    limit: int = 100,
    risk_min: str = "",
    session_id: str = "",
):
    """Return recent safety log entries.

    Query params:
      limit: max rows (default 100)
      risk_min: '' | 'medium' | 'high'  — filter by minimum risk level
      session_id: filter to a single session
    """
    rows = await get_safety_logs(
        limit=limit, risk_min=risk_min, session_id=session_id,
    )
    return {"count": len(rows), "logs": rows}


@router.get("/stats")
async def safety_stats():
    """Aggregate counts for the dashboard."""
    rows = await get_safety_logs(limit=1000)
    stats = {
        "total": len(rows),
        "by_risk": {"low": 0, "medium": 0, "high": 0},
        "by_legal": {},
        "rate_limited": 0,
        "escalated": 0,
    }
    for r in rows:
        rl = r.get("risk_level", "low")
        stats["by_risk"][rl] = stats["by_risk"].get(rl, 0) + 1
        if r.get("rate_limited"):
            stats["rate_limited"] += 1
        if r.get("escalated"):
            stats["escalated"] += 1
        for lf in r.get("legal_flags", []) or []:
            stats["by_legal"][lf] = stats["by_legal"].get(lf, 0) + 1
    return stats
