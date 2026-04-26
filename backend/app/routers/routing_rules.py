"""Studio API for the generic routing rule engine.

Read-only endpoints for the Studio UI to inspect rules + run the engine
in test-bench mode. Editing rules is intentionally NOT exposed via API —
edits go through the YAML file (Git workflow). When/if a UI editor is
needed, that's Phase 2.

Endpoints:
  GET  /api/routing-rules              — list all rules with metadata
  GET  /api/routing-rules/{id}         — single rule detail
  POST /api/routing-rules/test         — dry-run engine against custom context
  GET  /api/routing-rules/stats        — fire counts from shadow log
  POST /api/routing-rules/reload       — force reload YAML (admin only)
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.rule_engine import (
    RuleDef,
    RuleEngine,
    get_rule_engine,
    load_rules_from_file,
)

router = APIRouter()


def _rule_to_dict(r: RuleDef) -> dict:
    return {
        "id": r.id,
        "description": r.description,
        "priority": r.priority,
        "live": r.live,
        "when": r.when,
        "then": r.then,
    }


@router.get("")
async def list_rules() -> dict[str, Any]:
    """Return all rules from the live engine, sorted by priority desc."""
    engine = get_rule_engine()
    return {
        "rules": [_rule_to_dict(r) for r in engine._rules],
        "total": engine.rule_count,
        "live_count": sum(1 for r in engine._rules if r.live),
        "shadow_count": sum(1 for r in engine._rules if not r.live),
    }


@router.get("/stats")
async def fire_stats(
    days: int = Query(7, ge=1, le=90),
) -> dict[str, Any]:
    """Aggregate rule fire counts from the shadow JSONL logs.

    Reads the last ``days`` days of ``shadow_router_*.jsonl`` files and
    returns per-rule statistics:

    * ``fired``               — how often the rule matched the context
    * ``decision_held``       — the rule's effect was applied AND survived
                                until the final response (downstream
                                pipeline did not change it)
    * ``decision_overridden`` — the rule's effect was either not applied
                                (rule is shadow-only) OR overridden by
                                a later rule / pipeline stage

    For ``live: true`` rules, ``decision_overridden`` indicates a rule
    conflict worth investigating.
    For ``live: false`` (shadow) rules, ``decision_overridden`` is the
    expected case — the rule cannot apply its effect by design.
    """
    log_dir = Path(os.environ.get("BOERDI_SHADOW_LOG_DIR", "logs"))
    if not log_dir.exists():
        return {"days": days, "rules": {}, "total_turns": 0}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    fire_counts: Counter = Counter()
    held_counts: Counter = Counter()
    override_examples: dict = {}
    total_turns = 0
    # Build a {rule_id: live} map so the response can mark each row
    # with whether disagreements are expected (shadow) or noteworthy (live).
    engine = get_rule_engine()
    rule_live_map = {r.id: r.live for r in engine._rules}

    for f in sorted(log_dir.glob("shadow_router_*.jsonl")):
        try:
            file_date_str = f.stem.replace("shadow_router_", "")
            file_date = datetime.strptime(file_date_str, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            if file_date < cutoff - timedelta(days=1):  # 1d slack
                continue
        except Exception:
            continue
        try:
            with f.open("r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    total_turns += 1
                    agreement_overall = bool(
                        (rec.get("agreement") or {}).get("overall", True)
                    )
                    for fired in (rec.get("shadow") or {}).get("fired_rules", []) or []:
                        rid = fired.get("rule_id") if isinstance(fired, dict) else None
                        if not rid:
                            continue
                        fire_counts[rid] += 1
                        if agreement_overall:
                            held_counts[rid] += 1
                        elif rid not in override_examples and len(override_examples) < 30:
                            override_examples[rid] = {
                                "session": rec.get("session"),
                                "message": (rec.get("input") or {}).get("message", "")[:120],
                                "actual_pattern": (rec.get("actual") or {}).get("pattern_id"),
                                "shadow_pattern": (rec.get("shadow") or {}).get(
                                    "enforced_pattern_id"
                                ),
                            }
        except Exception:
            continue

    rules_stats = {}
    for rid, n in fire_counts.most_common():
        held = held_counts[rid]
        is_live = rule_live_map.get(rid, False)
        rules_stats[rid] = {
            "fired": n,
            "live": is_live,
            "decision_held": held,
            "decision_overridden": n - held,
            "decision_held_pct": round(held / n * 100, 1) if n else 0.0,
            # Backwards compat (deprecated keys, will remove later)
            "agree": held,
            "disagree": n - held,
            "agreement_pct": round(held / n * 100, 1) if n else 0.0,
            "sample_override": override_examples.get(rid),
            # Backwards-compat alias
            "sample_disagreement": override_examples.get(rid),
            # Hint for the UI: what the override means in context
            "override_meaning": (
                "expected — rule is shadow-only (live: false)"
                if not is_live
                else "rule conflict — investigate"
            ),
        }
    return {
        "days": days,
        "total_turns": total_turns,
        "rules": rules_stats,
    }


@router.get("/{rule_id}")
async def get_rule(rule_id: str) -> dict[str, Any]:
    engine = get_rule_engine()
    for r in engine._rules:
        if r.id == rule_id:
            return _rule_to_dict(r)
    raise HTTPException(404, f"rule not found: {rule_id}")


class TestRequest(BaseModel):
    """Body for /test — caller provides a synthetic context the engine runs against."""
    intent: str | None = None
    state: str | None = None
    persona: str | None = None
    entities: dict | None = None
    message: str = ""
    intent_confidence: float | None = None
    canvas_state: dict | None = None
    pattern_winner: str | None = None
    pattern_runner_up: str | None = None
    pattern_score_gap: float | None = None
    signals: list | None = None


@router.post("/test")
async def test_rules(req: TestRequest) -> dict[str, Any]:
    """Dry-run the rule engine against a hand-crafted context. No LLM call,
    no DB writes — pure rule evaluation, returns ~1ms.

    Use case: an author has just written a new rule and wants to verify it
    fires (or doesn't fire) on a specific input without launching a full
    eval. Also useful for debugging "why did rule X not fire?".
    """
    engine = get_rule_engine()
    ctx = {
        "intent": req.intent,
        "state": req.state,
        "persona": req.persona,
        "entities": req.entities or {},
        "signals": req.signals or [],
        "message": (req.message or "").lower(),
        "intent_confidence": req.intent_confidence,
        "canvas_state": req.canvas_state or {},
        "session_state": {},
        "safety": {},
        "pattern_winner": req.pattern_winner,
        "pattern_runner_up": req.pattern_runner_up,
        "pattern_score_gap": req.pattern_score_gap,
        "pattern_scores": {},
    }
    decision = engine.evaluate(ctx)
    live = engine.extract_live(decision)
    return {
        "context": ctx,
        "decision": decision.to_dict(),
        "live_decision": {
            "intent_override": live.intent_override,
            "state_override": live.state_override,
            "enforced_pattern_id": live.enforced_pattern_id,
            "direct_action": live.direct_action,
            "fired_rules": live.fired_rules,
            "is_noop": live.is_noop(),
        },
    }


@router.post("/reload")
async def reload_rules() -> dict[str, Any]:
    """Force-reload the YAML rules from disk. Useful after editing the
    file without restarting the backend."""
    engine = get_rule_engine(force_reload=True)
    return {
        "reloaded": True,
        "rule_count": engine.rule_count,
        "live_count": sum(1 for r in engine._rules if r.live),
    }


@router.delete("/stats")
async def delete_stats(
    days: int | None = Query(
        None, ge=0, le=365,
        description="Optional: only delete logs older than N days. Omit to clear all.",
    ),
) -> dict[str, Any]:
    """Delete shadow-router log files (the source of /stats data).

    Use case: after a major rule rewrite the historical stats are no
    longer meaningful — the user wants a clean slate before the next
    eval run. Without ``days``, all log files are removed.
    """
    log_dir = Path(os.environ.get("BOERDI_SHADOW_LOG_DIR", "logs"))
    if not log_dir.exists():
        return {"deleted": 0, "kept": 0, "log_dir": str(log_dir)}

    cutoff = None
    if days is not None and days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    deleted = 0
    kept = 0
    for f in sorted(log_dir.glob("shadow_router_*.jsonl")):
        try:
            file_date_str = f.stem.replace("shadow_router_", "")
            file_date = datetime.strptime(file_date_str, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        except Exception:
            # Unknown filename format — leave it alone
            kept += 1
            continue

        if cutoff is None or file_date < cutoff:
            try:
                f.unlink()
                deleted += 1
            except Exception:
                kept += 1
        else:
            kept += 1

    return {
        "deleted": deleted,
        "kept": kept,
        "log_dir": str(log_dir),
        "cutoff_days": days,
    }
