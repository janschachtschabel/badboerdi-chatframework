"""Generic, data-driven routing rule engine.

This is a thin orchestration layer on top of :mod:`rule_primitives`. It
loads a list of rules from YAML, evaluates them in priority order against
a per-turn context dict, and aggregates the resulting effects into a
single :class:`RuleDecision`.

The engine has zero BadBoerdi-specific knowledge — it does not know what
an "intent", a "pattern", or "P-W-LK" is. All domain semantics live in
the YAML rule file.

Usage::

    engine = get_rule_engine()       # cached load from disk
    decision = engine.evaluate(context)
    decision.fired_rules             # which rule IDs matched
    decision.intent_override         # str | None
    decision.enforced_pattern_id     # str | None
    decision.direct_action           # str | None
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

import yaml

from app.services.rule_primitives import evaluate_condition

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────

@dataclass
class RuleHit:
    """One rule that matched the context. Used for debug/trace output."""
    rule_id: str
    description: str = ""
    effects_applied: dict = field(default_factory=dict)
    live: bool = False  # was this rule's effect actually applied (vs shadow only)


@dataclass
class RuleDecision:
    """Aggregated decision produced by evaluating all matching rules.

    All fields are optional. A "no-op" decision (no rules fired) has
    every field at its default (None / empty list / empty dict) and is
    safe to ignore by callers.
    """
    intent_override: Optional[str] = None
    state_override: Optional[str] = None
    persona_override: Optional[str] = None
    enforced_pattern_id: Optional[str] = None
    direct_action: Optional[str] = None
    direct_action_params: dict = field(default_factory=dict)
    quick_replies: list = field(default_factory=list)
    degradation: Optional[str] = None
    fired_rules: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["fired_rules"] = [asdict(r) for r in self.fired_rules]
        return d

    def is_noop(self) -> bool:
        return (
            self.intent_override is None
            and self.state_override is None
            and self.persona_override is None
            and self.enforced_pattern_id is None
            and self.direct_action is None
            and not self.quick_replies
            and self.degradation is None
        )


@dataclass
class RuleDef:
    """In-memory representation of one parsed YAML rule."""
    id: str
    description: str
    priority: int
    when: dict
    then: dict
    live: bool = False  # if True, this rule's effects are applied to the live request


@dataclass
class LiveDecision:
    """Subset of RuleDecision containing only effects from rules marked
    ``live: true``. This is what the integration layer is allowed to apply.
    """
    intent_override: Optional[str] = None
    state_override: Optional[str] = None
    persona_override: Optional[str] = None
    enforced_pattern_id: Optional[str] = None
    direct_action: Optional[str] = None
    direct_action_params: dict = field(default_factory=dict)
    quick_replies: list = field(default_factory=list)
    degradation: Optional[str] = None
    fired_rules: list = field(default_factory=list)

    def is_noop(self) -> bool:
        return (
            self.intent_override is None
            and self.state_override is None
            and self.persona_override is None
            and self.enforced_pattern_id is None
            and self.direct_action is None
            and not self.quick_replies
            and self.degradation is None
        )


# ──────────────────────────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────────────────────────

# Effect keys the engine knows how to aggregate. Anything not in this set
# is ignored (with a warning) — keeps unknown YAML keys from silently
# corrupting state.
_KNOWN_EFFECTS = {
    "intent_override",
    "state_override",
    "persona_override",
    "enforced_pattern_id",
    "direct_action",
    "direct_action_params",
    "quick_replies",
    "degradation",
}


class RuleEngine:
    """Loads + evaluates routing rules.

    Rules with higher ``priority`` evaluate first. Unless a rule sets
    ``stop_on_match: true`` in its ``then`` block, evaluation continues so
    that multiple non-conflicting effects can layer (e.g. one rule sets
    intent_override, a later rule adds quick_replies).

    Conflict policy: if two rules try to set the same scalar field, the
    *first* (highest priority) one wins. List/dict effects merge.
    """

    def __init__(self, rules: list[RuleDef]):
        # Stable sort, descending priority. Rules at equal priority keep
        # their YAML order — predictable for authors.
        self._rules = sorted(rules, key=lambda r: -r.priority)

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    def evaluate(self, context: dict) -> RuleDecision:
        """Evaluate all rules against ``context`` and return aggregated decision.

        ``context`` should contain at minimum: ``intent``, ``state``,
        ``persona``, ``entities`` (dict), ``message`` (str). Optional:
        ``signals``, ``session_state``, ``canvas_state``, ``safety``.

        Missing keys are tolerated — the path resolver returns ``None``,
        which most comparators treat as "absent".
        """
        decision = RuleDecision()
        for rule in self._rules:
            try:
                matched = evaluate_condition(rule.when, context)
            except Exception as e:  # pragma: no cover — defensive
                logger.warning("rule '%s' raised during eval: %s", rule.id, e)
                continue
            if not matched:
                continue

            applied = self._apply_effects(decision, rule.then)
            decision.fired_rules.append(RuleHit(
                rule_id=rule.id,
                description=rule.description,
                effects_applied=applied,
                live=rule.live,
            ))

            if rule.then.get("stop_on_match") is True:
                break

        return decision

    def extract_live(self, decision: RuleDecision) -> LiveDecision:
        """Build a LiveDecision containing only effects from rules with live=True.

        Re-runs effect aggregation but only over the subset of fired rules
        that were marked live. This way, the same evaluation produces both
        a full shadow record (for logging) and a live-applicable subset.
        """
        live = LiveDecision()
        # Build a {rule_id: live_flag} map from fired_rules
        live_by_id = {h.rule_id: h.live for h in decision.fired_rules}
        # Re-aggregate from rule defs in priority order, but only live ones
        for rule in self._rules:
            if not live_by_id.get(rule.id):
                continue
            for key, val in rule.then.items():
                if key in ("stop_on_match",):
                    continue
                if key not in _KNOWN_EFFECTS:
                    continue
                current = getattr(live, key)
                if key == "quick_replies":
                    if isinstance(val, list):
                        live.quick_replies.extend(val)
                elif key == "direct_action_params":
                    if isinstance(val, dict):
                        live.direct_action_params.update(val)
                else:
                    if current is None:
                        setattr(live, key, val)
            live.fired_rules.append(rule.id)
        return live

    @staticmethod
    def _apply_effects(decision: RuleDecision, effects: dict) -> dict:
        """Merge ``effects`` into ``decision``. Returns the effects that
        actually took effect (for trace output).

        First-write-wins for scalar fields. Lists merge, dicts merge.
        Unknown keys are silently dropped (with debug log).
        """
        applied: dict = {}
        for key, val in effects.items():
            if key == "stop_on_match":
                continue
            if key not in _KNOWN_EFFECTS:
                logger.debug("unknown effect key '%s' ignored", key)
                continue

            current = getattr(decision, key)
            if key == "quick_replies":
                if isinstance(val, list):
                    decision.quick_replies.extend(val)
                    applied[key] = val
            elif key == "direct_action_params":
                if isinstance(val, dict):
                    decision.direct_action_params.update(val)
                    applied[key] = val
            else:
                # Scalar fields: first-write-wins
                if current is None:
                    setattr(decision, key, val)
                    applied[key] = val
        return applied


# ──────────────────────────────────────────────────────────────────────
# Loader (file → engine)
# ──────────────────────────────────────────────────────────────────────

# Cache holds (mtime, RuleEngine) so an edited YAML invalidates itself
# automatically — mirrors ``config_loader._load_yaml`` for consistency.
# ``None`` means "no engine loaded yet".
_ENGINE_CACHE: Optional[tuple[float, RuleEngine]] = None
_DEFAULT_RULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "chatbots" / "wlo" / "v1" / "06-rules" / "routing-rules.yaml"
)


def _expand_lookup_group(group: dict, group_index: int) -> list[RuleDef]:
    """Welle C.1 (2026-05): Expand a single ``lookups``-block into many
    one-shot RuleDefs (one per ``items`` entry).

    The expansion happens at YAML-load time — the RuleEngine itself never
    sees the lookup-group, only the resulting single rules. This keeps
    the engine free of new effect-types while letting the YAML stay short
    and Studio-editable as a table.

    Expected schema for a lookup group::

        lookups:
          - id_prefix: lookup_persona_self_id   # prefix for generated rule IDs
            description: "..."                  # applied to all generated rules
            priority: 70
            live: true
            when_path: message                  # which context field to match
            when_op: regex                      # regex|eq|in|contains|non_empty
            then_field: persona_override        # which then-key to set
            when_extra: { intent: { not_in: ["INT-W-12"] } }   # optional extra when (AND-combined)
            then_extra: { ... }                 # optional extra then fields (constant across items)
            items:
              - { key: lk,   match: "ich bin lehrer", value: "P-W-LK" }
              - { key: sl,   match: "ich bin schüler", value: "P-W-SL" }
              ...

    Result for each item::

        RuleDef(
          id="<id_prefix>__<item.key>",
          when={**when_extra, when_path: {when_op: item.match}},
          then={**then_extra, then_field: item.value},
          ...
        )
    """
    if not isinstance(group, dict):
        raise ValueError(f"lookup #{group_index}: not a mapping")
    prefix = group.get("id_prefix")
    if not isinstance(prefix, str) or not prefix:
        raise ValueError(f"lookup #{group_index}: missing or empty 'id_prefix'")
    items = group.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError(f"lookup '{prefix}': 'items' must be a non-empty list")

    when_path = group.get("when_path")
    when_op = group.get("when_op", "regex")
    then_field = group.get("then_field")
    if not when_path or not then_field:
        raise ValueError(f"lookup '{prefix}': 'when_path' + 'then_field' are required")

    when_extra = dict(group.get("when_extra") or {})
    then_extra = dict(group.get("then_extra") or {})
    description = group.get("description", "")
    priority = int(group.get("priority", 0))
    live = bool(group.get("live", False))

    out: list[RuleDef] = []
    for j, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"lookup '{prefix}' item #{j}: not a mapping")
        key = item.get("key") or f"item{j}"
        match = item.get("match")
        value = item.get("value")
        if match is None or value is None:
            raise ValueError(
                f"lookup '{prefix}' item '{key}': 'match' + 'value' required"
            )

        # Build when-clause: {when_path: {when_op: match}} merged with when_extra.
        # If when_extra also has the same path, AND them via the 'all' operator.
        match_clause = {when_path: {when_op: match}}
        if when_extra:
            when = {"all": [when_extra, match_clause]}
        else:
            when = match_clause

        then = {**then_extra, then_field: value}

        out.append(RuleDef(
            id=f"{prefix}__{key}",
            description=description,
            priority=priority,
            when=when,
            then=then,
            live=live,
        ))
    return out


def parse_rules(raw: dict) -> list[RuleDef]:
    """Parse the top-level YAML dict into RuleDef instances. Raises
    ValueError on malformed structure (missing ``id``, missing ``when``,
    etc.) so boot fails loudly rather than silently producing a broken
    engine.

    Welle C.1: In addition to the manual ``rules:`` list, the YAML may
    also define ``lookups:`` — groups of generated rules that share a
    common pattern (e.g. persona-self-id regexes). Lookup groups are
    expanded into normal rules at load-time so the engine itself doesn't
    need a new effect type. See ``_expand_lookup_group`` for the schema.
    """
    if not isinstance(raw, dict):
        raise ValueError("routing-rules.yaml must be a mapping")
    rules_raw = raw.get("rules")
    lookups_raw = raw.get("lookups") or []
    if not isinstance(rules_raw, list):
        raise ValueError("routing-rules.yaml must have a top-level 'rules' list")
    if not isinstance(lookups_raw, list):
        raise ValueError("routing-rules.yaml 'lookups' must be a list when present")

    out: list[RuleDef] = []
    seen_ids: set[str] = set()
    for i, r in enumerate(rules_raw):
        if not isinstance(r, dict):
            raise ValueError(f"rule #{i}: not a mapping")
        rid = r.get("id")
        if not isinstance(rid, str) or not rid:
            raise ValueError(f"rule #{i}: missing or empty 'id'")
        if rid in seen_ids:
            raise ValueError(f"duplicate rule id: {rid}")
        seen_ids.add(rid)
        when = r.get("when") or {}
        then = r.get("then") or {}
        if not isinstance(when, dict) or not isinstance(then, dict):
            raise ValueError(f"rule '{rid}': 'when' and 'then' must be mappings")
        out.append(RuleDef(
            id=rid,
            description=r.get("description", ""),
            priority=int(r.get("priority", 0)),
            when=when,
            then=then,
            live=bool(r.get("live", False)),
        ))

    # Expand lookup groups into single rules and append.
    for g_idx, group in enumerate(lookups_raw):
        for rd in _expand_lookup_group(group, g_idx):
            if rd.id in seen_ids:
                raise ValueError(
                    f"lookup expansion produced duplicate rule id: {rd.id}"
                )
            seen_ids.add(rd.id)
            out.append(rd)

    return out


def load_rules_from_file(path: Path | str | None = None) -> list[RuleDef]:
    p = Path(path) if path else _DEFAULT_RULE_PATH
    if not p.exists():
        logger.warning("routing-rules.yaml not found at %s — engine empty", p)
        return []
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return parse_rules(raw)


def load_lookup_groups_from_file(path: Path | str | None = None) -> list[dict]:
    """Welle C.1 (2026-05): Return the raw lookup-groups (table form) from
    the YAML, not the expanded RuleDefs. Used by the Studio UI to render
    the lookup tables as editable grids instead of N×expanded individual
    rules. Returns ``[]`` when the YAML has no ``lookups:`` section.
    """
    p = Path(path) if path else _DEFAULT_RULE_PATH
    if not p.exists():
        return []
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return []
    lookups = raw.get("lookups") or []
    return lookups if isinstance(lookups, list) else []


def get_rule_engine(force_reload: bool = False) -> RuleEngine:
    """Return the cached RuleEngine, reloading when ``routing-rules.yaml``
    has been touched since the last load.

    Mirrors the mtime-based caching in ``config_loader._load_yaml`` so
    YAML/MD edits propagate without a full backend restart. The
    in-memory engine itself is reused when the file hasn't changed,
    keeping the per-turn cost at a single ``stat`` call.

    ``force_reload=True`` skips the mtime check (useful in tests).
    """
    global _ENGINE_CACHE
    try:
        mtime = _DEFAULT_RULE_PATH.stat().st_mtime if _DEFAULT_RULE_PATH.exists() else 0.0
    except OSError:
        mtime = 0.0
    cached = _ENGINE_CACHE
    if (
        not force_reload
        and cached is not None
        and cached[0] == mtime
    ):
        return cached[1]
    rules = load_rules_from_file()
    engine = RuleEngine(rules)
    _ENGINE_CACHE = (mtime, engine)
    logger.info(
        "RuleEngine %s with %d rules (mtime=%s)",
        "reloaded" if cached is not None else "loaded",
        engine.rule_count, mtime,
    )
    return engine
