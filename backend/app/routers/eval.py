"""Evaluation router — automated persona/intent conversation testing.

All endpoints are Studio-protected. Runs execute in the background
(asyncio.create_task) so starting a run returns immediately; poll
GET /api/eval/runs/{id} for progress.

Pattern-usage analytics read from the existing ``quality_logs`` table,
which is populated by EVERY /api/chat call (production + eval) — so
the analytics endpoint works even without any eval run.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.auth import require_studio_key
from app.services.database import DB_PATH
from app.services.eval_service import (
    estimate_cost,
    execute_run,
    list_personas_and_intents,
)

router = APIRouter(prefix="/api/eval", tags=["eval"])

_studio = [Depends(require_studio_key)]


# ── Config snapshot ────────────────────────────────────────────────

@router.get("/config", dependencies=_studio)
async def get_config() -> dict[str, Any]:
    """Return current personas + intents from the active chatbot config."""
    return list_personas_and_intents()


# ── Cost estimate (pre-flight) ─────────────────────────────────────

class EstimateRequest(BaseModel):
    mode: str = Field("both", pattern="^(scenarios|conversations|both)$")
    persona_ids: list[str] = Field(default_factory=list)
    intent_ids: list[str] = Field(default_factory=list)
    scenarios_per_combo: int = Field(2, ge=1, le=10)
    turns_per_conv: int = Field(3, ge=1, le=10)


@router.post("/estimate", dependencies=_studio)
async def estimate(req: EstimateRequest) -> dict[str, Any]:
    cfg = list_personas_and_intents()
    n_p = len(req.persona_ids) or len(cfg["personas"])
    n_i = len(req.intent_ids) or len(cfg["intents"])
    return estimate_cost(
        n_personas=n_p, n_intents=n_i,
        scenarios_per_combo=req.scenarios_per_combo,
        mode=req.mode, turns_per_conv=req.turns_per_conv,
    )


# ── Start / list / detail ──────────────────────────────────────────

class StartRequest(BaseModel):
    mode: str = Field("both", pattern="^(scenarios|conversations|both)$")
    persona_ids: list[str] = Field(default_factory=list, description="empty = all")
    intent_ids: list[str] = Field(default_factory=list, description="empty = all")
    scenarios_per_combo: int = Field(2, ge=1, le=10)
    turns_per_conv: int = Field(3, ge=1, le=10)
    config_slug: str = ""


@router.post("/runs", dependencies=_studio)
async def start_run(req: StartRequest) -> dict[str, Any]:
    cfg = list_personas_and_intents()
    all_personas = cfg["personas"]
    all_intents = cfg["intents"]
    known_persona_ids = {p["id"] for p in all_personas}
    known_intent_ids = {i["id"] for i in all_intents}

    personas = all_personas
    intents = all_intents
    warnings: list[str] = []

    if req.persona_ids:
        requested = set(req.persona_ids)
        unknown = sorted(requested - known_persona_ids)
        if unknown:
            warnings.append(f"Unknown persona IDs ignored: {unknown}")
        personas = [p for p in all_personas if p["id"] in requested]

    if req.intent_ids:
        requested = set(req.intent_ids)
        unknown = sorted(requested - known_intent_ids)
        if unknown:
            warnings.append(f"Unknown intent IDs ignored: {unknown}")
        intents = [i for i in all_intents if i["id"] in requested]

    if not personas or not intents:
        raise HTTPException(
            400,
            f"no personas or intents matched the filter. "
            f"Available personas: {sorted(known_persona_ids)}. "
            f"Available intents: {sorted(known_intent_ids)}.",
        )

    run_id = f"eval-{uuid.uuid4().hex[:12]}"
    # Fire-and-forget background task
    asyncio.create_task(execute_run(
        run_id=run_id,
        mode=req.mode,
        personas=personas,
        intents=intents,
        scenarios_per_combo=req.scenarios_per_combo,
        turns_per_conv=req.turns_per_conv,
        config_slug=req.config_slug,
    ))
    return {
        "run_id": run_id,
        "status": "running",
        "personas_used": [p["id"] for p in personas],
        "intents_used": [i["id"] for i in intents],
        "warnings": warnings,
    }


@router.get("/runs", dependencies=_studio)
async def list_runs(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT id, created_at, completed_at, status, mode, config_slug,
                      total_turns, avg_score, personas, intents, error_message,
                      summary_json
               FROM eval_runs
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        )
        rows = await cur.fetchall()
    runs = []
    for r in rows:
        d = dict(r)
        d["personas"] = json.loads(d.get("personas") or "[]")
        d["intents"] = json.loads(d.get("intents") or "[]")
        # Parse summary for target_turns + current_activity — keeps list
        # query fast without requiring a separate detail fetch for progress.
        try:
            summary = json.loads(d.pop("summary_json") or "{}")
        except Exception:
            summary = {}
        d["target_turns"] = summary.get("target_turns", 0)
        d["current_activity"] = summary.get("current_activity", "")
        runs.append(d)
    return {"runs": runs}


@router.get("/runs/{run_id}", dependencies=_studio)
async def get_run(run_id: str) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM eval_runs WHERE id=?", (run_id,))
        row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "run not found")
    d = dict(row)
    d["personas"] = json.loads(d.get("personas") or "[]")
    d["intents"] = json.loads(d.get("intents") or "[]")
    d["summary"] = json.loads(d.get("summary_json") or "{}")
    d["conversations"] = json.loads(d.get("conversations_json") or "[]")
    # Drop heavy raw JSON strings from payload
    d.pop("summary_json", None)
    d.pop("conversations_json", None)
    return d


@router.delete("/runs/{run_id}", dependencies=_studio)
async def delete_run(run_id: str) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM eval_runs WHERE id=?", (run_id,))
        await db.commit()
    return {"deleted": run_id}


@router.delete("/runs", dependencies=_studio)
async def delete_all_runs(
    status_filter: str | None = Query(None, alias="status",
        description="Optional: 'done', 'failed', or 'running' to restrict deletion"),
    confirm: bool = Query(False, description="Must be true for unrestricted bulk delete"),
) -> dict[str, Any]:
    """Bulk-delete eval runs. Safety: without status filter, requires ?confirm=true
    to avoid accidental wipes. With a filter (e.g. only failed), deletes without confirm.
    """
    if not status_filter and not confirm:
        raise HTTPException(
            400,
            "Bulk delete without status filter requires ?confirm=true to prevent accidents.",
        )
    async with aiosqlite.connect(DB_PATH) as db:
        if status_filter:
            cur = await db.execute(
                "SELECT COUNT(*) FROM eval_runs WHERE status=?", (status_filter,),
            )
            count = (await cur.fetchone())[0]
            await db.execute("DELETE FROM eval_runs WHERE status=?", (status_filter,))
        else:
            cur = await db.execute("SELECT COUNT(*) FROM eval_runs")
            count = (await cur.fetchone())[0]
            await db.execute("DELETE FROM eval_runs")
        await db.commit()
    return {"deleted": count, "filter": status_filter or "all"}


@router.delete("/quality-logs", dependencies=_studio)
async def clear_eval_quality_logs() -> dict[str, Any]:
    """Delete all quality_logs rows written by eval runs (session_id LIKE 'eval-%').

    Production chat traffic is preserved. Use this when you want the analytics
    panel to reflect only real user traffic again, e.g. after a series of
    experimental eval runs that polluted the pattern-usage stats.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM quality_logs WHERE session_id LIKE 'eval-%'"
        )
        count = (await cur.fetchone())[0]
        await db.execute(
            "DELETE FROM quality_logs WHERE session_id LIKE 'eval-%'"
        )
        await db.commit()
    return {"deleted_eval_log_rows": count}


# ── Pattern / intent usage analytics (reads quality_logs) ──────────
#
# These work on ALL chat history, not just eval runs. If callers only
# want eval-triggered data, they can filter by session_id LIKE 'eval-%'.

@router.get("/analytics/pattern-usage", dependencies=_studio)
async def pattern_usage(
    since: str | None = Query(None, description="ISO timestamp floor"),
    scope: str = Query(
        "all", description="'all' | 'eval' (session_id LIKE eval-%) | 'production' (not eval-)",
    ),
) -> dict[str, Any]:
    """Pattern × intent × persona counts from quality_logs, scoped.

    scope=all         → every turn (eval + production mixed)
    scope=eval        → only simulated eval turns
    scope=production  → only real user traffic (session_id NOT LIKE 'eval-%')
    """
    where: list[str] = []
    params: list[Any] = []
    if since:
        where.append("created_at >= ?"); params.append(since)
    scope = (scope or "all").lower().strip()
    if scope == "eval":
        where.append("session_id LIKE 'eval-%'")
    elif scope == "production":
        where.append("session_id NOT LIKE 'eval-%'")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            f"""SELECT pattern_id, intent_id, persona_id, COUNT(*) AS count,
                       AVG(final_confidence) AS avg_conf
                FROM quality_logs
                {where_sql}
                GROUP BY pattern_id, intent_id, persona_id
                ORDER BY count DESC""",
            params,
        )
        rows = [dict(r) for r in await cur.fetchall()]

        cur2 = await db.execute(
            f"""SELECT pattern_id, COUNT(*) AS count
                FROM quality_logs
                {where_sql}
                GROUP BY pattern_id
                ORDER BY count DESC""",
            params,
        )
        by_pattern = [dict(r) for r in await cur2.fetchall()]

        cur3 = await db.execute(
            f"""SELECT intent_id, COUNT(*) AS count
                FROM quality_logs
                {where_sql}
                GROUP BY intent_id
                ORDER BY count DESC""",
            params,
        )
        by_intent = [dict(r) for r in await cur3.fetchall()]

    total = sum(r.get("count", 0) for r in rows)
    return {
        "triples": rows,
        "by_pattern": by_pattern,
        "by_intent": by_intent,
        "total": total,
        "scope": scope,
    }
