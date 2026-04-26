"""Unit tests for rule_engine — loader + evaluator + effect aggregator."""
from __future__ import annotations

import pytest

from app.services.rule_engine import (
    RuleDef,
    RuleEngine,
    RuleDecision,
    parse_rules,
)


def _rule(rid: str, when: dict, then: dict, priority: int = 50) -> RuleDef:
    return RuleDef(id=rid, description="", priority=priority, when=when, then=then)


class TestEngineEvaluation:
    def test_no_rules_yields_noop(self):
        eng = RuleEngine([])
        d = eng.evaluate({"intent": "X"})
        assert d.is_noop()
        assert d.fired_rules == []

    def test_single_rule_fires(self):
        eng = RuleEngine([
            _rule("r1", {"intent": {"eq": "X"}}, {"intent_override": "Y"}),
        ])
        d = eng.evaluate({"intent": "X"})
        assert d.intent_override == "Y"
        assert len(d.fired_rules) == 1
        assert d.fired_rules[0].rule_id == "r1"

    def test_rule_does_not_fire(self):
        eng = RuleEngine([
            _rule("r1", {"intent": {"eq": "X"}}, {"intent_override": "Y"}),
        ])
        d = eng.evaluate({"intent": "Z"})
        assert d.is_noop()

    def test_priority_order_first_write_wins(self):
        eng = RuleEngine([
            _rule("low", {"intent": {"eq": "X"}}, {"intent_override": "LOW"}, priority=10),
            _rule("high", {"intent": {"eq": "X"}}, {"intent_override": "HIGH"}, priority=90),
        ])
        d = eng.evaluate({"intent": "X"})
        assert d.intent_override == "HIGH"
        # both fired, but only the higher-priority value stuck
        assert {h.rule_id for h in d.fired_rules} == {"high", "low"}

    def test_stop_on_match(self):
        eng = RuleEngine([
            _rule("first", {"intent": {"eq": "X"}}, {
                "intent_override": "Y", "stop_on_match": True
            }, priority=90),
            _rule("second", {"intent": {"eq": "X"}}, {
                "intent_override": "Z"
            }, priority=80),
        ])
        d = eng.evaluate({"intent": "X"})
        assert d.intent_override == "Y"
        assert [h.rule_id for h in d.fired_rules] == ["first"]

    def test_quick_replies_merge(self):
        eng = RuleEngine([
            _rule("a", {"intent": {"eq": "X"}}, {"quick_replies": ["q1"]}, priority=90),
            _rule("b", {"intent": {"eq": "X"}}, {"quick_replies": ["q2"]}, priority=80),
        ])
        d = eng.evaluate({"intent": "X"})
        assert d.quick_replies == ["q1", "q2"]

    def test_unknown_effect_ignored(self):
        eng = RuleEngine([
            _rule("r1", {"intent": {"eq": "X"}}, {"madeup_effect": "Y"}),
        ])
        d = eng.evaluate({"intent": "X"})
        assert d.is_noop()
        # rule still fired (matched), but applied no effects
        assert len(d.fired_rules) == 1
        assert d.fired_rules[0].effects_applied == {}

    def test_rule_with_exception_skipped(self):
        # A malformed condition should not crash the engine
        eng = RuleEngine([
            _rule("bad", {"intent": "not-a-dict"}, {"intent_override": "X"}),
            _rule("good", {"intent": {"eq": "X"}}, {"intent_override": "OK"}),
        ])
        d = eng.evaluate({"intent": "X"})
        assert d.intent_override == "OK"

    def test_decision_to_dict_serializable(self):
        eng = RuleEngine([
            _rule("r1", {"intent": {"eq": "X"}}, {"intent_override": "Y"}),
        ])
        d = eng.evaluate({"intent": "X"})
        out = d.to_dict()
        assert out["intent_override"] == "Y"
        assert isinstance(out["fired_rules"], list)
        assert out["fired_rules"][0]["rule_id"] == "r1"


class TestParser:
    def test_minimal_valid(self):
        raw = {"rules": [
            {"id": "r1", "priority": 5, "when": {}, "then": {"intent_override": "X"}},
        ]}
        rules = parse_rules(raw)
        assert len(rules) == 1
        assert rules[0].id == "r1"

    def test_no_top_level_rules_raises(self):
        with pytest.raises(ValueError):
            parse_rules({})

    def test_rule_without_id_raises(self):
        with pytest.raises(ValueError):
            parse_rules({"rules": [{"priority": 1, "when": {}, "then": {}}]})

    def test_duplicate_id_raises(self):
        with pytest.raises(ValueError):
            parse_rules({"rules": [
                {"id": "x", "when": {}, "then": {}},
                {"id": "x", "when": {}, "then": {}},
            ]})

    def test_when_must_be_mapping(self):
        with pytest.raises(ValueError):
            parse_rules({"rules": [
                {"id": "x", "when": "not a dict", "then": {}}
            ]})


class TestLiveExtraction:
    def test_live_only_extracts_live_rules(self):
        eng = RuleEngine([
            RuleDef(id="shadow_only", description="", priority=90,
                    when={"intent": {"eq": "X"}},
                    then={"intent_override": "SHADOW"},
                    live=False),
            RuleDef(id="live_one", description="", priority=80,
                    when={"intent": {"eq": "X"}},
                    then={"enforced_pattern_id": "PAT-LIVE"},
                    live=True),
        ])
        decision = eng.evaluate({"intent": "X"})
        # Both fire in shadow
        assert decision.intent_override == "SHADOW"
        assert decision.enforced_pattern_id == "PAT-LIVE"

        live = eng.extract_live(decision)
        # Only the live one applies
        assert live.intent_override is None
        assert live.enforced_pattern_id == "PAT-LIVE"
        assert live.fired_rules == ["live_one"]

    def test_live_first_write_wins(self):
        eng = RuleEngine([
            RuleDef(id="r_high", description="", priority=90,
                    when={"intent": {"eq": "X"}},
                    then={"enforced_pattern_id": "HIGH"},
                    live=True),
            RuleDef(id="r_low", description="", priority=10,
                    when={"intent": {"eq": "X"}},
                    then={"enforced_pattern_id": "LOW"},
                    live=True),
        ])
        decision = eng.evaluate({"intent": "X"})
        live = eng.extract_live(decision)
        assert live.enforced_pattern_id == "HIGH"

    def test_no_live_rules_yields_noop_live(self):
        eng = RuleEngine([
            RuleDef(id="shadow", description="", priority=50,
                    when={"intent": {"eq": "X"}},
                    then={"intent_override": "Y"},
                    live=False),
        ])
        decision = eng.evaluate({"intent": "X"})
        live = eng.extract_live(decision)
        assert live.is_noop()


class TestEndToEnd:
    """A miniature end-to-end test using a realistic rule mix."""

    def setup_method(self):
        self.eng = RuleEngine([
            _rule("vague_search",
                  {"all": [
                      {"intent": {"in": ["INT-W-03a", "INT-W-03b"]}},
                      {"entity.thema": {"empty": True}},
                  ]},
                  {"enforced_pattern_id": "PAT-20"},
                  priority=50),
            _rule("canvas_edit",
                  {"all": [
                      {"canvas_state.markdown": {"non_empty": True}},
                      {"intent": {"eq": "INT-W-12"}},
                  ]},
                  {"direct_action": "canvas_edit", "intent_override": "INT-W-12"},
                  priority=90),
        ])

    def test_vague_math_routes_to_orientation(self):
        ctx = {
            "intent": "INT-W-03b",
            "state": "state-5",
            "persona": "P-W-SL",
            "entities": {"fach": "Mathematik"},
            "message": "ich brauche hilfe bei mathe",
        }
        d = self.eng.evaluate(ctx)
        assert d.enforced_pattern_id == "PAT-20"
        assert d.fired_rules[0].rule_id == "vague_search"

    def test_concrete_topic_does_not_route_to_orientation(self):
        ctx = {
            "intent": "INT-W-03b",
            "state": "state-5",
            "persona": "P-W-SL",
            "entities": {"thema": "Photosynthese"},
            "message": "arbeitsblatt zur photosynthese",
        }
        d = self.eng.evaluate(ctx)
        assert d.is_noop()

    def test_canvas_edit_path(self):
        ctx = {
            "intent": "INT-W-12",
            "state": "state-12",
            "persona": "P-W-LK",
            "entities": {},
            "message": "mach es kürzer",
            "canvas_state": {"markdown": "# Bestehender Text\nLorem ipsum"},
        }
        d = self.eng.evaluate(ctx)
        assert d.direct_action == "canvas_edit"
        assert d.intent_override == "INT-W-12"
