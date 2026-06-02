"""Generic rule primitives — comparators + dotted path resolver.

This module is intentionally kept free of any BadBoerdi domain knowledge.
The primitives only know about:
  - dotted path lookup into a context dict
  - a small, fixed set of comparators (eq, in, regex, empty, ...)
  - boolean combinators (all, any, not)

Everything that is BadBoerdi-specific (intent IDs, persona IDs, pattern IDs,
state names) lives in YAML rules — never here.
"""
from __future__ import annotations

import re
from typing import Any, Iterable


# ──────────────────────────────────────────────────────────────────────
# Path resolution
# ──────────────────────────────────────────────────────────────────────

def resolve_path(context: dict, path: str) -> Any:
    """Resolve a dotted path into ``context``.

    Supports:
      - top-level keys           ``intent``
      - nested dotted paths      ``entities.thema``
      - aliases for convenience: ``entity.X`` is sugar for ``entities.X``
      - missing path             returns ``None`` (never raises)

    The resolver never raises — a missing intermediate key, a None value,
    or a non-dict mid-path all yield ``None``. Callers should treat that
    as "absent" and combine with comparators (``empty``, ``non_empty``).
    """
    if not path:
        return None
    # Normalize aliases: ``entity.X`` → ``entities.X``
    parts = path.split(".")
    if parts[0] == "entity":
        parts[0] = "entities"
    cur: Any = context
    for p in parts:
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return None
        if cur is None:
            return None
    return cur


# ──────────────────────────────────────────────────────────────────────
# Comparator implementations
# ──────────────────────────────────────────────────────────────────────

def _is_empty(value: Any) -> bool:
    """Truthy-style emptiness: None / "" / [] / {} all empty."""
    if value is None:
        return True
    if isinstance(value, (str, list, tuple, dict, set)):
        return len(value) == 0
    return False


def _cmp_eq(value: Any, expected: Any) -> bool:
    return value == expected


def _cmp_neq(value: Any, expected: Any) -> bool:
    return value != expected


def _cmp_in(value: Any, choices: Iterable[Any]) -> bool:
    if choices is None:
        return False
    return value in list(choices)


def _cmp_not_in(value: Any, choices: Iterable[Any]) -> bool:
    return not _cmp_in(value, choices)


def _cmp_regex(value: Any, pattern: str) -> bool:
    if not isinstance(value, str) or not isinstance(pattern, str):
        return False
    try:
        return re.search(pattern, value, flags=re.IGNORECASE) is not None
    except re.error:
        return False


def _cmp_not_regex(value: Any, pattern: str) -> bool:
    return not _cmp_regex(value, pattern)


def _cmp_empty(value: Any, expected: bool = True) -> bool:
    return _is_empty(value) == bool(expected)


def _cmp_non_empty(value: Any, expected: bool = True) -> bool:
    return (not _is_empty(value)) == bool(expected)


def _cmp_exists(value: Any, expected: bool = True) -> bool:
    """Slightly different from non_empty: ``False`` and ``0`` count as existing."""
    return (value is not None) == bool(expected)


def _to_number(value: Any) -> float | None:
    """Coerce a value to float for numeric comparison. Returns None on failure
    so the caller can decide on a default (we treat None as "comparator did
    not apply" → False)."""
    if isinstance(value, bool):
        # bool is a subclass of int; we don't want to accidentally compare
        # ``True < 1`` style. Reject it explicitly.
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _cmp_lt(value: Any, threshold: Any) -> bool:
    a, b = _to_number(value), _to_number(threshold)
    if a is None or b is None:
        return False
    return a < b


def _cmp_gt(value: Any, threshold: Any) -> bool:
    a, b = _to_number(value), _to_number(threshold)
    if a is None or b is None:
        return False
    return a > b


def _cmp_lte(value: Any, threshold: Any) -> bool:
    a, b = _to_number(value), _to_number(threshold)
    if a is None or b is None:
        return False
    return a <= b


def _cmp_gte(value: Any, threshold: Any) -> bool:
    a, b = _to_number(value), _to_number(threshold)
    if a is None or b is None:
        return False
    return a >= b


COMPARATORS = {
    "eq": _cmp_eq,
    "neq": _cmp_neq,
    "in": _cmp_in,
    "not_in": _cmp_not_in,
    "regex": _cmp_regex,
    "not_regex": _cmp_not_regex,
    "empty": _cmp_empty,
    "non_empty": _cmp_non_empty,
    "exists": _cmp_exists,
    "lt": _cmp_lt,
    "gt": _cmp_gt,
    "lte": _cmp_lte,
    "gte": _cmp_gte,
}


def evaluate_atom(value: Any, op_spec: dict) -> bool:
    """Evaluate a single comparator dict like ``{eq: "INT-W-11"}``.

    ``op_spec`` is a dict with exactly one key — the comparator name —
    mapped to its argument. Unknown comparators return ``False`` (defensive
    fallback so a typo in YAML doesn't crash routing).
    """
    if not isinstance(op_spec, dict) or len(op_spec) != 1:
        return False
    op, arg = next(iter(op_spec.items()))
    fn = COMPARATORS.get(op)
    if fn is None:
        return False
    try:
        return bool(fn(value, arg))
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────
# Condition tree evaluator (all / any / not + leaf comparators)
# ──────────────────────────────────────────────────────────────────────

def evaluate_condition(condition: Any, context: dict) -> bool:
    """Recursively evaluate a YAML condition node against the context.

    Supported shapes:
      - ``{all: [<cond>, ...]}``     — every child must be True
      - ``{any: [<cond>, ...]}``     — at least one child must be True
      - ``{not: <cond>}``            — invert
      - ``{<path>: <op_spec>}``      — leaf: resolve path, apply comparator
      - ``{path: x, <op>: ...}``     — alternative leaf form (path explicit)

    Anything malformed evaluates to ``False`` — never raises.
    """
    if condition is None:
        return True  # empty condition = always pass
    if not isinstance(condition, dict):
        return False
    if len(condition) == 0:
        return True  # ``when: {}`` in YAML = always pass

    # Combinator: all
    if "all" in condition:
        children = condition["all"]
        if not isinstance(children, list):
            return False
        return all(evaluate_condition(c, context) for c in children)

    # Combinator: any
    if "any" in condition:
        children = condition["any"]
        if not isinstance(children, list):
            return False
        return any(evaluate_condition(c, context) for c in children)

    # Combinator: not
    if "not" in condition:
        return not evaluate_condition(condition["not"], context)

    # Leaf: exactly one key, its value is the op_spec
    if len(condition) == 1:
        path, op_spec = next(iter(condition.items()))
        if isinstance(op_spec, dict):
            value = resolve_path(context, path)
            return evaluate_atom(value, op_spec)
        return False

    return False
