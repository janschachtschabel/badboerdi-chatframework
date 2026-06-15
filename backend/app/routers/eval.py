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
from app.services.config_loader import load_gold_flows
from app.services.database import DB_PATH
from app.services.eval_service import (
    estimate_cost,
    execute_golden_run,
    execute_run,
    list_personas_and_intents,
)

router = APIRouter(prefix="/api/eval", tags=["eval"])

_studio = [Depends(require_studio_key)]

# B4 (2026-06-10): starke Referenzen auf laufende Eval-Tasks — der Loop
# hält nur Weak-Refs, ein nacktes create_task kann mitten im Run GC'd
# werden. Dazu Exception-Retrieval, damit Fehler nicht als "Task
# exception was never retrieved" enden (execute_* loggen selbst).
_EVAL_TASKS: set[asyncio.Task] = set()


def _spawn_eval_task(coro: Any) -> None:
    t = asyncio.create_task(coro)
    _EVAL_TASKS.add(t)

    def _done(task: asyncio.Task) -> None:
        _EVAL_TASKS.discard(task)
        try:
            task.exception()
        except (asyncio.CancelledError, asyncio.InvalidStateError):
            pass

    t.add_done_callback(_done)


async def _ensure_no_running_run() -> None:
    """B4: Parallel-Guard — zwei gleichzeitige Runs teilen sich Tool-Cache
    (clear_tool_cache löscht global!) und SQLite-Writes; Ergebnis wäre
    vermischt. Stale 'running'-Leichen (Backend-Crash) älter als 2h werden
    dabei automatisch auf failed gesetzt, damit sie nicht ewig blockieren."""
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE eval_runs SET status='failed', "
            "error_message='stale running-Run beim Start-Check abgeräumt' "
            "WHERE status='running' AND created_at < ?",
            (cutoff,),
        )
        await db.commit()
        cur = await db.execute(
            "SELECT id FROM eval_runs WHERE status='running' LIMIT 1"
        )
        row = await cur.fetchone()
    if row:
        raise HTTPException(
            409,
            f"Eval-Run {row[0]} läuft bereits — bitte abwarten oder löschen. "
            "Parallele Runs teilen sich Tool-Cache und DB und würden sich "
            "gegenseitig verfälschen.",
        )


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

    await _ensure_no_running_run()
    run_id = f"eval-{uuid.uuid4().hex[:12]}"
    # Background task mit starker Referenz (B4)
    _spawn_eval_task(execute_run(
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


# ── Golden-Flow Eval (deterministische, geprüfte Multi-Turn-Abläufe) ──

@router.get("/gold-flows", dependencies=_studio)
async def get_gold_flows() -> dict[str, Any]:
    """Return the parsed Gold-Standard flow specs (eval/gold-flows.yaml).

    Light payload — the Studio uses this to list flows, show their per-turn
    expectations, and let the user pick which flows to run.
    """
    flows = load_gold_flows()
    return {"flows": flows, "count": len(flows)}


class GoldenRunRequest(BaseModel):
    flow_ids: list[str] = Field(default_factory=list, description="empty = all flows")
    judge: bool = Field(True, description="run the LLM judge for soft quality dims")
    config_slug: str = ""


@router.post("/runs/golden", dependencies=_studio)
async def start_golden_run(req: GoldenRunRequest) -> dict[str, Any]:
    """Start a deterministic Gold-Flow run in the background. Inputs are
    fixed (gold-flows.yaml), so the run is reproducible and A/B-comparable.
    """
    all_flows = load_gold_flows()
    if not all_flows:
        raise HTTPException(
            400, "Keine Gold-Flows konfiguriert (eval/gold-flows.yaml fehlt oder leer)."
        )
    flows = all_flows
    warnings: list[str] = []
    if req.flow_ids:
        requested = set(req.flow_ids)
        known = {str(f.get("id")) for f in all_flows}
        unknown = sorted(requested - known)
        if unknown:
            warnings.append(f"Unbekannte Flow-IDs ignoriert: {unknown}")
        flows = [f for f in all_flows if str(f.get("id")) in requested]
    if not flows:
        raise HTTPException(
            400,
            "Keine Flows matchten den Filter. Verfügbar: "
            f"{sorted({str(f.get('id')) for f in all_flows})}",
        )

    await _ensure_no_running_run()
    run_id = f"eval-{uuid.uuid4().hex[:12]}"
    _spawn_eval_task(execute_golden_run(
        run_id=run_id, flows=flows,
        judge_enabled=req.judge, config_slug=req.config_slug,
    ))
    return {
        "run_id": run_id,
        "status": "running",
        "mode": "golden",
        "flows_used": [str(f.get("id")) for f in flows],
        "turns_total": sum(len(f.get("turns") or []) for f in flows),
        "judge": req.judge,
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


@router.get("/trends", dependencies=_studio)
async def get_trends(
    limit: int = Query(10, ge=2, le=100,
        description="Number of most-recent completed runs to compare"),
) -> dict[str, Any]:
    """Cross-run trend metrics (Bonus 3).

    Reads the last ``limit`` completed eval runs and assembles time-series
    for the metrics that matter for regression detection:
      * tool_compliance_per_pattern  → pattern × run rate matrix
      * cache_hit_rate
      * llm_engine_match_rate
      * persona_correct_rate / intent_correct_rate

    Welle E v4 (2026-05-25): tie_breaker_trend entfernt — der Hint-
    Primary-Pfad braucht keinen Tie-Breaker mehr (Phase 2 läuft nicht).

    The Studio UI can render these as sparklines per pattern + run-over-run
    deltas without each turn fetching the full conversation transcripts.
    Light payload — only summaries are read, conversations_json stays untouched.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT id, created_at, completed_at, mode, config_slug,
                      total_turns, avg_score, summary_json
               FROM eval_runs
               WHERE status = 'done'
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        )
        rows = await cur.fetchall()

    runs_meta: list[dict[str, Any]] = []
    pattern_trend: dict[str, list[dict[str, Any]]] = {}
    cache_hit_trend: list[dict[str, Any]] = []
    match_rate_trend: list[dict[str, Any]] = []
    persona_rate_trend: list[dict[str, Any]] = []
    intent_rate_trend: list[dict[str, Any]] = []

    # Reverse so the timeline is oldest → newest (UI-friendly)
    for r in reversed(rows):
        try:
            summary = json.loads(r["summary_json"] or "{}")
        except Exception:
            summary = {}
        cm = summary.get("classification_metrics") or {}

        run_id = r["id"]
        created_at = r["created_at"]
        runs_meta.append({
            "id": run_id,
            "created_at": created_at,
            "completed_at": r["completed_at"],
            "mode": r["mode"],
            "config_slug": r["config_slug"],
            "total_turns": r["total_turns"],
            "avg_score": r["avg_score"],
        })

        # Tool-compliance per pattern
        per_pattern = cm.get("tool_compliance_per_pattern") or {}
        for pid, stats in per_pattern.items():
            if not isinstance(stats, dict):
                continue
            ok = int(stats.get("ok") or 0)
            total = int(stats.get("total") or 0)
            rate = round(ok / total, 3) if total else 0.0
            pattern_trend.setdefault(pid, []).append({
                "run_id": run_id,
                "created_at": created_at,
                "ok": ok,
                "total": total,
                "rate": rate,
            })

        # Scalar trends
        cache_hit_trend.append({
            "run_id": run_id, "created_at": created_at,
            "value": (cm.get("token_usage_aggregate") or {}).get("cache_hit_rate", 0.0),
            "prompt_tokens": (cm.get("token_usage_aggregate") or {}).get("prompt_tokens", 0),
            "cached_tokens": (cm.get("token_usage_aggregate") or {}).get("cached_tokens", 0),
        })
        match_rate_trend.append({
            "run_id": run_id, "created_at": created_at,
            "value": cm.get("llm_engine_match_rate", 0.0),
            "judged": cm.get("llm_hint_present_count", 0),
        })
        persona_rate_trend.append({
            "run_id": run_id, "created_at": created_at,
            "value": cm.get("persona_correct_rate", 0.0),
            "total": cm.get("persona_total_judged", 0),
        })
        intent_rate_trend.append({
            "run_id": run_id, "created_at": created_at,
            "value": cm.get("intent_correct_rate", 0.0),
            "total": cm.get("intent_total_judged", 0),
        })
        # Welle E v4: tie_breaker_trend entfernt.

    # Pad pattern trend with implicit zeros so each series spans every run
    # — keeps line charts honest about coverage.
    run_ids_in_order = [m["id"] for m in runs_meta]
    for pid, series in pattern_trend.items():
        present_runs = {entry["run_id"] for entry in series}
        for rid in run_ids_in_order:
            if rid not in present_runs:
                series.append({
                    "run_id": rid,
                    "created_at": next(
                        (m["created_at"] for m in runs_meta if m["id"] == rid),
                        "",
                    ),
                    "ok": 0,
                    "total": 0,
                    "rate": 0.0,
                })
        # Sort by run order
        order_index = {rid: i for i, rid in enumerate(run_ids_in_order)}
        series.sort(key=lambda e: order_index.get(e["run_id"], 0))

    return {
        "runs": runs_meta,
        "pattern_trend": pattern_trend,
        "cache_hit_trend": cache_hit_trend,
        "llm_engine_match_trend": match_rate_trend,
        "persona_correct_trend": persona_rate_trend,
        "intent_correct_trend": intent_rate_trend,
    }


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
    mode_filter: str | None = Query(None, alias="mode",
        description="Optional: 'golden' | 'generative' (= mode != golden) | exact mode value"),
    confirm: bool = Query(False, description="Must be true for unrestricted bulk delete"),
) -> dict[str, Any]:
    """Bulk-delete eval runs, optionally restricted by status and/or mode
    (combinable). ``mode=golden`` deletes only Golden-Flow runs; ``mode=generative``
    deletes only the generative Persona-Dialog runs (mode != 'golden'); any other
    value is matched exactly. Safety: a wholly unrestricted delete (no status AND
    no mode) still requires ?confirm=true to avoid accidental wipes.
    """
    where: list[str] = []
    params: list[Any] = []
    if status_filter:
        where.append("status = ?")
        params.append(status_filter)
    if mode_filter == "golden":
        where.append("mode = 'golden'")
    elif mode_filter == "generative":
        where.append("mode != 'golden'")
    elif mode_filter:
        where.append("mode = ?")
        params.append(mode_filter)

    if not where and not confirm:
        raise HTTPException(
            400,
            "Bulk delete without any filter requires ?confirm=true to prevent accidents.",
        )
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(f"SELECT COUNT(*) FROM eval_runs {where_sql}", params)
        count = (await cur.fetchone())[0]
        await db.execute(f"DELETE FROM eval_runs {where_sql}", params)
        await db.commit()
    return {"deleted": count, "filter": {"status": status_filter, "mode": mode_filter}}


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
