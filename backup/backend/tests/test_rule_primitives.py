"""Unit tests for rule_primitives — comparators + path resolver."""
from __future__ import annotations

import pytest

from app.services.rule_primitives import (
    resolve_path,
    evaluate_atom,
    evaluate_condition,
)


# ──────────────────────────────────────────────────────────────────────
# Path resolver
# ──────────────────────────────────────────────────────────────────────

class TestResolvePath:
    def test_top_level(self):
        assert resolve_path({"intent": "X"}, "intent") == "X"

    def test_nested(self):
        assert resolve_path({"a": {"b": {"c": 7}}}, "a.b.c") == 7

    def test_missing_path_returns_none(self):
        assert resolve_path({"a": {}}, "a.b.c") is None

    def test_missing_top_returns_none(self):
        assert resolve_path({}, "x.y.z") is None

    def test_entity_alias_maps_to_entities(self):
        ctx = {"entities": {"thema": "Photosynthese"}}
        assert resolve_path(ctx, "entity.thema") == "Photosynthese"

    def test_through_non_dict_returns_none(self):
        ctx = {"a": "string"}
        assert resolve_path(ctx, "a.b") is None

    def test_empty_path(self):
        assert resolve_path({"a": 1}, "") is None


# ──────────────────────────────────────────────────────────────────────
# Comparators
# ──────────────────────────────────────────────────────────────────────

class TestEq:
    def test_match(self):
        assert evaluate_atom("X", {"eq": "X"}) is True

    def test_no_match(self):
        assert evaluate_atom("X", {"eq": "Y"}) is False

    def test_none(self):
        assert evaluate_atom(None, {"eq": None}) is True


class TestIn:
    def test_match(self):
        assert evaluate_atom("a", {"in": ["a", "b"]}) is True

    def test_no_match(self):
        assert evaluate_atom("c", {"in": ["a", "b"]}) is False

    def test_empty_list(self):
        assert evaluate_atom("a", {"in": []}) is False


class TestNotIn:
    def test_match(self):
        assert evaluate_atom("c", {"not_in": ["a", "b"]}) is True

    def test_no_match(self):
        assert evaluate_atom("a", {"not_in": ["a", "b"]}) is False


class TestRegex:
    def test_match_simple(self):
        assert evaluate_atom("hello world", {"regex": "world"}) is True

    def test_match_umlaut(self):
        assert evaluate_atom("kürzer machen", {"regex": "kürzer"}) is True

    def test_match_case_insensitive(self):
        assert evaluate_atom("HELLO", {"regex": "hello"}) is True

    def test_no_match(self):
        assert evaluate_atom("hello", {"regex": "^bye"}) is False

    def test_invalid_regex_returns_false(self):
        assert evaluate_atom("x", {"regex": "[invalid"}) is False

    def test_non_string_value(self):
        assert evaluate_atom(123, {"regex": "1"}) is False


class TestEmpty:
    @pytest.mark.parametrize("v", [None, "", [], {}, set()])
    def test_truly_empty(self, v):
        assert evaluate_atom(v, {"empty": True}) is True

    @pytest.mark.parametrize("v", ["x", [1], {"a": 1}, "  ", 0])
    def test_not_empty(self, v):
        # "  " (whitespace string) and 0 are NOT considered empty
        assert evaluate_atom(v, {"empty": True}) is False

    def test_empty_false_inverts(self):
        assert evaluate_atom("", {"empty": False}) is False
        assert evaluate_atom("x", {"empty": False}) is True


class TestNonEmpty:
    def test_string(self):
        assert evaluate_atom("x", {"non_empty": True}) is True

    def test_empty_string_is_not_non_empty(self):
        assert evaluate_atom("", {"non_empty": True}) is False

    def test_none(self):
        assert evaluate_atom(None, {"non_empty": True}) is False


class TestExists:
    def test_zero_exists(self):
        # 0 is a valid value, only None is missing
        assert evaluate_atom(0, {"exists": True}) is True

    def test_false_exists(self):
        assert evaluate_atom(False, {"exists": True}) is True

    def test_none_does_not_exist(self):
        assert evaluate_atom(None, {"exists": True}) is False


class TestNumericComparators:
    def test_lt_match(self):
        assert evaluate_atom(0.4, {"lt": 0.5}) is True
        assert evaluate_atom("0.4", {"lt": 0.5}) is True  # string→float

    def test_lt_no_match(self):
        assert evaluate_atom(0.6, {"lt": 0.5}) is False
        assert evaluate_atom(0.5, {"lt": 0.5}) is False

    def test_gt_match(self):
        assert evaluate_atom(0.6, {"gt": 0.5}) is True

    def test_gte_match(self):
        assert evaluate_atom(0.5, {"gte": 0.5}) is True

    def test_lte_match(self):
        assert evaluate_atom(0.5, {"lte": 0.5}) is True

    def test_none_value_returns_false(self):
        assert evaluate_atom(None, {"lt": 0.5}) is False
        assert evaluate_atom(None, {"gt": 0.5}) is False

    def test_bool_rejected(self):
        # True == 1 in Python, but we don't want True < 0.5 confusion
        assert evaluate_atom(True, {"lt": 0.5}) is False

    def test_unparseable_string_returns_false(self):
        assert evaluate_atom("nope", {"lt": 0.5}) is False


class TestUnknownComparator:
    def test_returns_false(self):
        assert evaluate_atom("x", {"made_up_op": "y"}) is False

    def test_malformed_spec_returns_false(self):
        assert evaluate_atom("x", {"eq": "x", "in": []}) is False  # multi-key
        assert evaluate_atom("x", "string") is False  # not a dict


# ──────────────────────────────────────────────────────────────────────
# Condition tree (all/any/not + leaves)
# ──────────────────────────────────────────────────────────────────────

class TestConditionTree:
    def test_simple_leaf(self):
        ctx = {"intent": "X"}
        assert evaluate_condition({"intent": {"eq": "X"}}, ctx) is True

    def test_leaf_via_path(self):
        ctx = {"entities": {"thema": "Photo"}}
        assert evaluate_condition({"entity.thema": {"eq": "Photo"}}, ctx) is True

    def test_all_combinator(self):
        ctx = {"a": 1, "b": 2}
        cond = {"all": [{"a": {"eq": 1}}, {"b": {"eq": 2}}]}
        assert evaluate_condition(cond, ctx) is True

    def test_all_one_fails(self):
        ctx = {"a": 1, "b": 9}
        cond = {"all": [{"a": {"eq": 1}}, {"b": {"eq": 2}}]}
        assert evaluate_condition(cond, ctx) is False

    def test_any_combinator(self):
        ctx = {"a": 1}
        cond = {"any": [{"a": {"eq": 9}}, {"a": {"eq": 1}}]}
        assert evaluate_condition(cond, ctx) is True

    def test_any_all_fail(self):
        ctx = {"a": 5}
        cond = {"any": [{"a": {"eq": 9}}, {"a": {"eq": 7}}]}
        assert evaluate_condition(cond, ctx) is False

    def test_not_combinator(self):
        ctx = {"a": 1}
        assert evaluate_condition({"not": {"a": {"eq": 9}}}, ctx) is True
        assert evaluate_condition({"not": {"a": {"eq": 1}}}, ctx) is False

    def test_nested_combinators(self):
        ctx = {"intent": "X", "entities": {"thema": "Y"}}
        cond = {
            "all": [
                {"intent": {"eq": "X"}},
                {"any": [
                    {"entity.thema": {"eq": "Z"}},
                    {"entity.thema": {"eq": "Y"}},
                ]},
            ]
        }
        assert evaluate_condition(cond, ctx) is True

    def test_missing_path_treated_as_none(self):
        ctx = {}
        cond = {"entity.material_typ": {"empty": True}}
        assert evaluate_condition(cond, ctx) is True

    def test_empty_condition_passes(self):
        # ``when: {}`` in YAML → always True. Practical for catch-all rules.
        assert evaluate_condition({}, {}) is True

    def test_none_condition_passes(self):
        assert evaluate_condition(None, {}) is True

    def test_malformed_condition_fails(self):
        # Two keys at leaf level → ambiguous → False
        assert evaluate_condition({"a": "x", "b": "y"}, {}) is False
