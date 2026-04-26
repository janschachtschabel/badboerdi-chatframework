"""Shadow-mode integration for the generic rule engine.

Shadow mode: the engine evaluates each turn alongside the live router,
logs its decision, and never affects the actual response. Comparing the
shadow log to the live router's decisions over many turns tells us
whether the engine can replace the hardcoded overrides safely.

Two failure modes the shadow layer must NEVER cause:
  1. Make the request fail. Any exception inside the shadow is caught
     and logged — never re-raised.
  2. Slow down the request meaningfully. The engine is sub-millisecond
     for the rule counts we expect; we still wrap with a timer to
     surface regressions.

Disable via env var ``BOERDI_SHADOW_ROUTER=0``.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.rule_engine import LiveDecision, RuleDecision, get_rule_engine

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────

def _shadow_enabled() -> bool:
    val = os.environ.get("BOERDI_SHADOW_ROUTER", "1").strip().lower()
    return val not in ("0", "false", "no", "off", "")


def _log_dir() -> Path:
    p = Path(os.environ.get("BOERDI_SHADOW_LOG_DIR", "logs"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _log_file_for_today() -> Path:
    return _log_dir() / f"shadow_router_{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"


_lock = threading.Lock()


# ──────────────────────────────────────────────────────────────────────
# Context builder
# ──────────────────────────────────────────────────────────────────────

def build_context(
    *,
    message: str,
    classification: Any,
    session_state: dict,
    canvas_state: dict | None,
    safety: Any,
    pattern_winner: str | None = None,
    pattern_runner_up: str | None = None,
    pattern_score_gap: float | None = None,
    pattern_scores: dict | None = None,
) -> dict:
    """Flatten the relevant per-turn information into a plain dict that
    matches the dotted paths used by the YAML rules.

    The engine itself is dict-based and Pydantic-agnostic, so we copy
    the few fields we care about. Anything extra is harmless — the path
    resolver only reads what the rules ask for.
    """
    cls_intent = getattr(classification, "intent_id", None)
    cls_state = getattr(classification, "next_state", None)
    cls_persona = getattr(classification, "persona_id", None)
    cls_entities = getattr(classification, "entities", None) or {}
    cls_signals = getattr(classification, "signals", None) or []
    cls_intent_conf = getattr(classification, "intent_confidence", None)
    cls_persona_conf = getattr(classification, "persona_confidence", None)

    safety_dict: dict = {}
    if safety is not None:
        for f in ("risk_level", "enforced_pattern", "blocked_tools"):
            v = getattr(safety, f, None)
            if v is not None:
                safety_dict[f] = v

    return {
        "message": (message or "").lower(),
        "intent": cls_intent,
        "state": cls_state,
        "persona": cls_persona,
        "entities": dict(cls_entities) if isinstance(cls_entities, dict) else {},
        "signals": list(cls_signals) if isinstance(cls_signals, list) else [],
        "session_state": session_state or {},
        "canvas_state": canvas_state or {},
        "safety": safety_dict,
        # Classifier confidences (for low_confidence rules)
        "intent_confidence": cls_intent_conf,
        "persona_confidence": cls_persona_conf,
        # Pattern-selection results (only set in post-route phase)
        "pattern_winner": pattern_winner,
        "pattern_runner_up": pattern_runner_up,
        "pattern_score_gap": pattern_score_gap,
        "pattern_scores": pattern_scores or {},
    }


# ──────────────────────────────────────────────────────────────────────
# Comparison + log writer
# ──────────────────────────────────────────────────────────────────────

def _to_jsonable(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(o) for o in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    return obj


def compare(actual: dict, shadow: RuleDecision) -> dict:
    """Compute agreement flags between the live decision (``actual``)
    and the shadow engine's decision.

    ``actual`` is a plain dict the integration layer fills with what the
    live router actually decided this turn. Keys it should provide:
      - intent_final, state_final, pattern_id, direct_action

    Missing keys in ``actual`` are treated as ``None``.
    """
    intent_final = actual.get("intent_final")
    state_final = actual.get("state_final")
    pattern_id = actual.get("pattern_id")
    action = actual.get("direct_action")

    intent_match = (
        shadow.intent_override is None or shadow.intent_override == intent_final
    )
    state_match = (
        shadow.state_override is None or shadow.state_override == state_final
    )
    pattern_match = (
        shadow.enforced_pattern_id is None
        or shadow.enforced_pattern_id == "__from_safety__"
        or shadow.enforced_pattern_id == pattern_id
    )
    action_match = (
        shadow.direct_action is None or shadow.direct_action == action
    )

    return {
        "intent_match": bool(intent_match),
        "state_match": bool(state_match),
        "pattern_match": bool(pattern_match),
        "action_match": bool(action_match),
        "overall": bool(intent_match and state_match and pattern_match and action_match),
    }


def _write_record(rec: dict) -> None:
    try:
        path = _log_file_for_today()
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        with _lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)
    except Exception as e:  # never let logging kill a request
        logger.warning("shadow log write failed: %s", e)


# ──────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────

def run_shadow(
    *,
    session_id: str,
    turn: int,
    message: str,
    classification: Any,
    session_state: dict,
    canvas_state: dict | None,
    safety: Any,
    actual: dict,
    pattern_winner: str | None = None,
    pattern_runner_up: str | None = None,
    pattern_score_gap: float | None = None,
    pattern_scores: dict | None = None,
    phase: str = "pre",
) -> tuple[RuleDecision, LiveDecision] | None:
    """Evaluate the rule engine and return both the full shadow decision
    and the live-applicable subset (rules with ``live: true``).

    ``phase``: "pre" before pattern-selection (only intent/state/etc.
    available), "post" after (pattern_winner etc. populated). Phase is
    just a label written into the log record for filtering.

    Returns ``(shadow, live)`` tuple, or ``None`` if shadow disabled or on
    error. The ``live`` decision is safe to apply by the caller — it only
    contains effects from rules explicitly marked live.
    """
    if not _shadow_enabled():
        return None

    try:
        engine = get_rule_engine()
    except Exception as e:
        logger.warning("rule engine unavailable: %s", e)
        return None

    try:
        ctx = build_context(
            message=message,
            classification=classification,
            session_state=session_state,
            canvas_state=canvas_state,
            safety=safety,
            pattern_winner=pattern_winner,
            pattern_runner_up=pattern_runner_up,
            pattern_score_gap=pattern_score_gap,
            pattern_scores=pattern_scores,
        )
    except Exception as e:
        logger.warning("shadow context build failed: %s", e)
        return None

    t0 = time.perf_counter()
    try:
        decision = engine.evaluate(ctx)
        live = engine.extract_live(decision)
    except Exception as e:
        logger.warning("shadow engine eval failed: %s", e)
        return None
    dur_ms = round((time.perf_counter() - t0) * 1000, 3)

    # Skip writing when nothing fired — keeps logs lean and signal-rich.
    if decision.is_noop() and not decision.fired_rules:
        # Still record a thin entry so we can compute "% turns where engine had nothing to say"
        thin = True
    else:
        thin = False

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session": session_id,
        "turn": turn,
        "phase": phase,
        "duration_ms": dur_ms,
        "thin": thin,
        "input": {
            "message": message,
            "intent": ctx.get("intent"),
            "state": ctx.get("state"),
            "persona": ctx.get("persona"),
            "entities": ctx.get("entities"),
            "intent_confidence": ctx.get("intent_confidence"),
            "has_canvas_md": bool(ctx.get("canvas_state", {}).get("markdown")),
            "pattern_winner": pattern_winner,
            "pattern_runner_up": pattern_runner_up,
            "pattern_score_gap": pattern_score_gap,
        },
        "actual": actual,
        "shadow": _to_jsonable(decision),
        "live": _to_jsonable(live),
        "agreement": compare(actual, decision),
    }
    _write_record(record)
    return decision, live
