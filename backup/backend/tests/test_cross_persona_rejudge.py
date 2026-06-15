"""Tests for the Cross-Persona + LLM-Hint Re-Judge addons (Welle D).

These tests don't make real LLM calls — they exercise the data-pipeline
parts:

* ``load_cross_persona_scenarios`` parses the YAML correctly.
* The aggregator splits cross-persona turns out and computes their own
  stats block.
* The aggregator wires up the strategy-showdown counts from
  ``turn["judge_pattern_choice"]``.
* The eval Router accepts the new request flags.
"""
from __future__ import annotations

import pytest

from app.services.config_loader import load_cross_persona_scenarios
from app.services.eval_service import _aggregate_classification_metrics


# ── Cross-Persona config ────────────────────────────────────────────


def test_cross_persona_yaml_parses():
    """The shipped YAML must parse and yield at least 6 combos."""
    cfg = load_cross_persona_scenarios()
    assert "combos" in cfg
    combos = cfg["combos"]
    assert isinstance(combos, list)
    assert len(combos) >= 6, f"Expected ≥6 combos, got {len(combos)}"
    for c in combos:
        assert c["persona_id"].startswith("P-"), f"bad persona_id: {c}"
        # Welle E (Sprint 3, 2026-05-18): Intent-IDs sind INT-WISSEN,
        # INT-SUCHE-MATERIAL, INT-LERNPFAD usw. — kein
        # INT-W-NN-Schema mehr.
        assert c["intent_id"].startswith("INT-"), f"bad intent_id: {c}"
        # description is recommended but not strictly required


# ── Aggregator: Cross-Persona-Split ─────────────────────────────────


def _mk_turn(pattern, persona, intent, pm, hint=None, is_cp=False,
             choice=None, expected_persona="P-W-LK", expected_intent="INT-W-03"):
    """Helper: build a fake conversation+turn dict the aggregator can read."""
    turn = {
        "user": "x",
        "bot": "y",
        "debug": {
            "pattern": pattern,
            "persona": persona,
            "intent": intent,
            "pattern_id_hint": hint or "",
        },
        "judge": {"pattern_match": pm, "total": pm / 2.0},
    }
    if choice is not None:
        turn["judge_pattern_choice"] = choice
    return {
        "persona_id": expected_persona,
        "intent_id": expected_intent,
        "is_cross_persona": is_cp,
        "turns": [turn],
    }


def test_aggregator_separates_cross_persona():
    convs = [
        _mk_turn("PAT-06", "P-W-LK", "INT-W-03", pm=2),           # normal
        _mk_turn("PAT-06", "P-W-LK", "INT-W-03", pm=2),           # normal
        _mk_turn("PAT-02", "P-W-SL", "INT-W-10", pm=1, is_cp=True,
                 expected_persona="P-W-SL", expected_intent="INT-W-10"),
        _mk_turn("PAT-19", "P-W-SL", "INT-W-10", pm=2, is_cp=True,
                 expected_persona="P-W-SL", expected_intent="INT-W-10"),
    ]
    metrics = _aggregate_classification_metrics(convs)
    cp = metrics.get("cross_persona") or {}
    assert cp.get("judged_turns") == 2
    # one of two had pm>=2 → engine_pattern_judge_ok_rate = 0.5
    assert cp.get("engine_pattern_judge_ok_count") == 1
    assert cp.get("engine_pattern_judge_ok_rate") == 0.5
    # Pattern usage shows the two distinct patterns
    pu = cp.get("pattern_usage") or {}
    assert pu.get("PAT-02", 0) >= 1
    assert pu.get("PAT-19", 0) >= 1


def test_aggregator_zero_cross_persona_when_none():
    convs = [_mk_turn("PAT-06", "P-W-LK", "INT-W-03", pm=2)]
    metrics = _aggregate_classification_metrics(convs)
    cp = metrics.get("cross_persona") or {}
    assert cp.get("judged_turns") == 0


# ── Aggregator: Strategy-Showdown ────────────────────────────────────


def test_aggregator_strategy_showdown_counts():
    convs = [
        _mk_turn("PAT-06", "P-W-LK", "INT-W-03", pm=2, hint="PAT-07",
                 choice={"preferred": "A", "engine_pattern_fit": 2,
                         "llm_hint_pattern_fit": 1, "reasoning": "."}),
        _mk_turn("PAT-06", "P-W-LK", "INT-W-03", pm=1, hint="PAT-10",
                 choice={"preferred": "B", "engine_pattern_fit": 1,
                         "llm_hint_pattern_fit": 2, "reasoning": "."}),
        _mk_turn("PAT-06", "P-W-LK", "INT-W-03", pm=2, hint="PAT-10",
                 choice={"preferred": "B", "engine_pattern_fit": 1,
                         "llm_hint_pattern_fit": 2, "reasoning": "."}),
        _mk_turn("PAT-06", "P-W-LK", "INT-W-03", pm=2, hint="PAT-08",
                 choice={"preferred": "tie", "engine_pattern_fit": 2,
                         "llm_hint_pattern_fit": 2, "reasoning": "."}),
    ]
    metrics = _aggregate_classification_metrics(convs)
    ss = metrics.get("strategy_showdown") or {}
    assert ss.get("evaluated_turns") == 4
    assert ss.get("engine_wins") == 1
    assert ss.get("llm_hint_wins") == 2
    assert ss.get("ties") == 1
    # By-pair: PAT-06-vs-PAT-10 has 2 LLM wins
    by_llm = ss.get("llm_hint_wins_by_pair") or {}
    assert by_llm.get("PAT-06-vs-PAT-10") == 2
    # Avg fit: engine 2+1+1+2 = 6/4 = 1.5; llm 1+2+2+2 = 7/4 = 1.75
    assert ss.get("engine_avg_fit") == 1.5
    assert ss.get("llm_hint_avg_fit") == 1.75


def test_aggregator_skips_strategy_showdown_when_no_choice():
    convs = [_mk_turn("PAT-06", "P-W-LK", "INT-W-03", pm=2, hint="PAT-07")]
    metrics = _aggregate_classification_metrics(convs)
    ss = metrics.get("strategy_showdown") or {}
    assert ss.get("evaluated_turns") == 0
    assert ss.get("engine_wins") == 0
    assert ss.get("llm_hint_wins") == 0
