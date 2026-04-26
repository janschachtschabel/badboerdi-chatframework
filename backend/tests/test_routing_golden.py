"""Golden tests: feed real-world inputs through the live YAML rules
and assert the engine reaches the expected decision.

These tests are how we catch regressions in the YAML rules themselves —
unit tests cover the engine mechanics, golden tests cover the rule
authorship.
"""
from __future__ import annotations

import pytest

from app.services.rule_engine import get_rule_engine


@pytest.fixture(scope="module")
def engine():
    # force_reload guarantees a fresh load even if a prior test mutated
    # global state; the live YAML is parsed once per test module.
    return get_rule_engine(force_reload=True)


GOLDEN_CASES = [
    # ── R-2 Canvas-Edit ──────────────────────────────────────────
    dict(
        name="canvas_edit_clear_intent",
        ctx=dict(
            intent="INT-W-12",
            state="state-12",
            persona="P-W-LK",
            entities={},
            message="mach es kürzer",
            canvas_state={"markdown": "# Vorhandener Text"},
        ),
        expect_fired=["rule_canvas_edit"],
        expect_action="canvas_edit",
    ),
    dict(
        name="canvas_edit_via_verb_only",
        ctx=dict(
            intent="INT-W-03b",
            state="state-12",
            persona="P-W-LK",
            entities={},
            message="bitte verständlicher formulieren",
            canvas_state={"markdown": "# Text\nInhalt"},
        ),
        expect_fired_contains="rule_canvas_edit",
        expect_action="canvas_edit",
    ),
    dict(
        name="canvas_edit_blocked_by_new_create",
        ctx=dict(
            intent="INT-W-12",
            state="state-12",
            persona="P-W-LK",
            entities={},
            message="erstelle ein neues arbeitsblatt zum thema X",
            canvas_state={"markdown": "# Text"},
        ),
        expect_fired_not_contains="rule_canvas_edit",
    ),
    dict(
        name="canvas_edit_no_markdown_no_route",
        ctx=dict(
            intent="INT-W-12",
            state="state-12",
            persona="P-W-LK",
            entities={},
            message="mach es kürzer",
            canvas_state={},
        ),
        expect_fired_not_contains="rule_canvas_edit",
    ),

    # ── R-3 Materialzusammenstellung → INT-W-10 ──────────────────
    dict(
        name="lp_compilation_text",
        ctx=dict(
            intent="INT-W-11",
            state="state-5",
            persona="P-W-LK",
            entities={"thema": "Umweltschutz", "fach": "Biologie"},
            message="könnten sie mir bitte eine strukturierte materialzusammenstellung erstellen",
        ),
        expect_intent_override="INT-W-10",
    ),
    dict(
        name="lp_compilation_state12_corrected",
        ctx=dict(
            intent="INT-W-11",
            state="state-12",
            persona="P-W-LK",
            entities={"thema": "X", "material_typ": "struktur"},
            message="erstelle eine materialsammlung zu X",
        ),
        # both R-3 and R-3b should fire
        expect_intent_override="INT-W-10",
        expect_state_override="state-5",
    ),

    # ── R-4 state-12 guard ───────────────────────────────────────
    dict(
        name="state12_dropped_for_search_intent",
        ctx=dict(
            intent="INT-W-03b",
            state="state-12",
            persona="P-W-LK",
            entities={"thema": "Mathe"},
            message="zeig mir material",
            canvas_state={},
        ),
        expect_state_override="state-5",
    ),
    dict(
        name="state12_kept_for_canvas_intent",
        ctx=dict(
            intent="INT-W-11",
            state="state-12",
            persona="P-W-LK",
            entities={"thema": "X"},
            message="erstelle ein arbeitsblatt zu X",
            canvas_state={"markdown": "# Existing"},
        ),
        expect_fired_not_contains="rule_state12_guard",
    ),

    # ── R-5 soft-create override ─────────────────────────────────
    dict(
        name="soft_create_with_material_typ",
        ctx=dict(
            intent="INT-W-03b",
            state="state-5",
            persona="P-W-LK",
            entities={"material_typ": "arbeitsblatt", "thema": "Photosynthese"},
            message="erstelle ein arbeitsblatt zur photosynthese",
        ),
        expect_intent_override="INT-W-11",
    ),
    dict(
        name="soft_create_protected_for_INT_W_07",
        ctx=dict(
            intent="INT-W-07",
            state="state-5",
            persona="P-W-LK",
            entities={"material_typ": "arbeitsblatt"},
            message="erstelle bitte ein download des arbeitsblatts",
        ),
        expect_intent_override=None,  # should NOT override INT-W-07
    ),

    # ── R-6 vague search → orientation ───────────────────────────
    dict(
        name="vague_search_no_topic",
        ctx=dict(
            intent="INT-W-03b",
            state="state-5",
            persona="P-W-SL",
            entities={"fach": "Mathematik"},
            message="ich brauche hilfe bei mathe",
        ),
        expect_pattern="PAT-20",
    ),
    dict(
        name="vague_search_with_topic_no_route",
        ctx=dict(
            intent="INT-W-03b",
            state="state-5",
            persona="P-W-SL",
            entities={"thema": "Photosynthese"},
            message="material zur photosynthese",
        ),
        expect_fired_not_contains="rule_vague_search",
    ),
    # Meta-question must NOT route to PAT-20 (Phase-1 disagreement #4)
    dict(
        name="vague_search_meta_question_excluded",
        ctx=dict(
            intent="INT-W-03c",
            state="state-8",
            persona="P-W-SL",
            entities={},
            message="kannst du mir schritt für schritt erklären, wie ich materialien finde?",
        ),
        expect_fired_not_contains="rule_vague_search",
    ),

    # ── R-7 Low intent confidence → PAT-02 ───────────────────────
    dict(
        name="low_confidence_routes_to_clarify",
        ctx=dict(
            intent="INT-W-03b",
            state="state-5",
            persona="P-AND",
            entities={"thema": "Photosynthese"},
            intent_confidence=0.4,
            message="irgendwas mit photosynthese",
        ),
        expect_pattern="PAT-02",
        expect_fired_contains="rule_low_intent_confidence",
    ),
    dict(
        name="high_confidence_no_clarify(self)",
        ctx=dict(
            intent="INT-W-03b",
            state="state-5",
            persona="P-AND",
            entities={"thema": "Photosynthese"},
            intent_confidence=0.9,
            message="material zur photosynthese",
        ),
        expect_fired_not_contains="rule_low_intent_confidence",
    ),

    # ── R-8 PAT-01/02 race fires in SHADOW (R-6 catches first) ────
    dict(
        name="tight_race_pat01_pat02_shadow_only",
        ctx=dict(
            intent="INT-W-03b",
            state="state-5",
            persona="P-W-LK",
            entities={"fach": "Mathematik"},
            intent_confidence=0.8,
            message="materialien für mathematik",
            pattern_winner="PAT-01",
            pattern_runner_up="PAT-02",
            pattern_score_gap=0.005,
        ),
        # R-6 vague_search wins the live decision (PAT-20).
        # R-8 also fires in shadow — both record into trace, R-6 effect first.
        expect_pattern="PAT-20",
        expect_fired_contains="rule_tiebreak_pat01_vs_pat02",
    ),
    dict(
        name="tight_race_pat01_pat02_with_thema_no_route",
        ctx=dict(
            intent="INT-W-03b",
            state="state-5",
            persona="P-W-LK",
            entities={"fach": "Mathematik", "thema": "Bruchrechnung"},
            intent_confidence=0.8,
            message="materialien zur bruchrechnung",
            pattern_winner="PAT-01",
            pattern_runner_up="PAT-02",
            pattern_score_gap=0.005,
        ),
        # With thema present, R-8 must NOT fire any longer
        expect_fired_not_contains="rule_tiebreak_pat01_vs_pat02",
    ),
    dict(
        name="tight_race_pat01_pat02_wide_gap_no_route",
        ctx=dict(
            intent="INT-W-03b",
            state="state-5",
            persona="P-W-LK",
            entities={"thema": "Photosynthese"},
            message="...",
            pattern_winner="PAT-01",
            pattern_runner_up="PAT-02",
            pattern_score_gap=0.15,  # wide gap
        ),
        expect_fired_not_contains="rule_tiebreak_pat01_vs_pat02",
    ),

    # ── R-9 INT-W-09 race → PAT-03 (nur P-VER/POL/PRESSE/BER) ────
    dict(
        name="int_w_09_pat10_pver_to_pat03",
        ctx=dict(
            intent="INT-W-09",
            state="state-9",
            persona="P-VER",
            entities={},
            message="übersicht der kennzahlen",
            pattern_winner="PAT-10",
            pattern_runner_up="PAT-01",
            pattern_score_gap=0.002,
        ),
        expect_pattern="PAT-03",
    ),
    dict(
        name="int_w_09_p_w_lk_no_route",
        ctx=dict(
            intent="INT-W-09",
            state="state-9",
            persona="P-W-LK",
            entities={},
            message="übersicht der kennzahlen",
            pattern_winner="PAT-10",
            pattern_runner_up="PAT-01",
            pattern_score_gap=0.002,
        ),
        # P-W-LK is NOT in the analytical persona scope
        expect_fired_not_contains="rule_tiebreak_int_w_09",
    ),

    # ── R-11 Canvas-Edit dominant ───────────────────────────────
    dict(
        name="canvas_edit_overrides_pat06",
        ctx=dict(
            intent="INT-W-12",
            state="state-12",
            persona="P-W-LK",
            entities={"thema": "Nachhaltigkeit"},
            message="kürzer machen",
            canvas_state={"markdown": "# X"},
            pattern_winner="PAT-06",
            pattern_runner_up="PAT-25",
            pattern_score_gap=0.02,
        ),
        expect_pattern="PAT-25",
    ),
]


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=[c["name"] for c in GOLDEN_CASES])
def test_golden(engine, case):
    decision = engine.evaluate(case["ctx"])
    fired_ids = [h.rule_id for h in decision.fired_rules]

    if "expect_fired" in case:
        assert fired_ids == case["expect_fired"], (
            f"fired={fired_ids} expected={case['expect_fired']}"
        )
    if "expect_fired_contains" in case:
        assert case["expect_fired_contains"] in fired_ids, (
            f"expected {case['expect_fired_contains']} in {fired_ids}"
        )
    if "expect_fired_not_contains" in case:
        assert case["expect_fired_not_contains"] not in fired_ids, (
            f"unexpected rule {case['expect_fired_not_contains']} fired ({fired_ids})"
        )
    if "expect_action" in case:
        assert decision.direct_action == case["expect_action"]
    if "expect_intent_override" in case:
        assert decision.intent_override == case["expect_intent_override"]
    if "expect_state_override" in case:
        assert decision.state_override == case["expect_state_override"]
    if "expect_pattern" in case:
        assert decision.enforced_pattern_id == case["expect_pattern"]
