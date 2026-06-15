"""Lasttest-Router — Studio-Selbsttest für Skalierbarkeit.

Alle Endpoints Studio-geschützt. Runs laufen im Hintergrund
(asyncio.create_task mit starker Referenz); Fortschritt via
GET /api/loadtest/runs/{id} pollen.

ACHTUNG Betrieb: Ein Run feuert ECHTE Chat-Requests durch die komplette
Pipeline (LLM + MCP) — Kosten und Staging-Last. Profile sind hart
gedeckelt (siehe loadtest_service); es läuft maximal ein Run gleichzeitig.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.services.auth import require_studio_key
from app.services.loadtest_service import (
    MIX_TEMPLATES,
    any_run_running,
    delete_run,
    execute_load_test,
    list_runs,
    load_run,
    validate_profile,
)

router = APIRouter(prefix="/api/loadtest", tags=["loadtest"])

_studio = [Depends(require_studio_key)]

# Starke Referenzen wie beim Eval-Router (B4): nackte create_task-Tasks
# kann der Loop sonst mitten im Run einsammeln.
_LT_TASKS: set[asyncio.Task] = set()


def _spawn(coro: Any) -> None:
    t = asyncio.create_task(coro)
    _LT_TASKS.add(t)

    def _done(task: asyncio.Task) -> None:
        _LT_TASKS.discard(task)
        try:
            task.exception()
        except (asyncio.CancelledError, asyncio.InvalidStateError):
            pass

    t.add_done_callback(_done)


class LoadTestProfile(BaseModel):
    stages: list[int] = Field(default=[1, 2, 4], description="Parallelität je Stufe")
    requests_per_stage: int = Field(default=6, description="Requests pro Stufe")
    mix: dict[str, int] = Field(
        default={"wissen": 1, "suche": 1, "orientierung": 1},
        description="Gewichte je Kategorie (wissen/suche/orientierung/lernpfad)",
    )
    p95_threshold_s: float = Field(
        default=20.0, description="p95-Schwelle für 'stabil' im Fazit",
    )


@router.get("/mix-options", dependencies=_studio)
async def mix_options() -> dict:
    """Verfügbare Mix-Kategorien mit Beschreibung (für das Studio-Formular)."""
    return {
        "options": [
            {"key": k, "label": v["label"], "prompt": v["prompt"]}
            for k, v in MIX_TEMPLATES.items()
        ]
    }


@router.post("/runs", dependencies=_studio)
async def start_run(profile: LoadTestProfile) -> dict:
    running = any_run_running()
    if running:
        raise HTTPException(
            409, f"Lasttest {running} läuft bereits — bitte abwarten.",
        )
    try:
        norm = validate_profile(profile.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))
    run_id = f"lt-{uuid.uuid4().hex[:12]}"
    _spawn(execute_load_test(run_id, norm))
    return {"id": run_id, "status": "running", "profile": norm}


@router.get("/runs", dependencies=_studio)
async def get_runs() -> dict:
    return {"runs": list_runs()}


@router.get("/runs/{run_id}", dependencies=_studio)
async def get_run(run_id: str) -> dict:
    run = load_run(run_id)
    if not run:
        raise HTTPException(404, "Run nicht gefunden.")
    return run


@router.delete("/runs/{run_id}", dependencies=_studio)
async def remove_run(run_id: str) -> dict:
    run = load_run(run_id)
    if run and run.get("status") == "running":
        raise HTTPException(409, "Laufender Run kann nicht gelöscht werden.")
    if not delete_run(run_id):
        raise HTTPException(404, "Run nicht gefunden.")
    return {"deleted": run_id}
