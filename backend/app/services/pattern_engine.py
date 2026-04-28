"""3-Phase Pattern Engine: Gate → Score → Modulate.

Implements the full WLO chatbot pattern model as described in the reference documents.
Patterns are loaded from config files (03-patterns/*.md) and refreshed on each call.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PatternDef(BaseModel):
    """Pattern definition loaded from 03-patterns/*.md config files."""
    id: str
    label: str
    priority: int = 400
    # Phase 1 gates
    gate_personas: list[str] = Field(default_factory=lambda: ["*"])
    gate_states: list[str] = Field(default_factory=lambda: ["*"])
    gate_intents: list[str] = Field(default_factory=lambda: ["*"])
    # Phase 2 scoring
    signal_high_fit: list[str] = Field(default_factory=list)
    signal_medium_fit: list[str] = Field(default_factory=list)
    signal_low_fit: list[str] = Field(default_factory=list)
    page_bonus: list[str] = Field(default_factory=list)
    precondition_slots: list[str] = Field(default_factory=list)
    # Phase 3 defaults
    default_tone: str = "sachlich"
    default_length: str = "mittel"
    default_detail: str = "standard"
    response_type: str = "answer"
    sources: list[str] = Field(default_factory=lambda: ["mcp"])
    rag_areas: list[str] = Field(default_factory=list)
    format_primary: str = "text"
    format_follow_up: str = "quick_replies"
    card_text_mode: str = "minimal"  # minimal | reference | highlight
    tools: list[str] = Field(default_factory=list)
    # When True, the LLM MUST call a tool on the first iteration even if RAG
    # context was prefetched. Use for discovery/listing patterns where the
    # tool output (cards) is the actual user-facing payload, and a textual
    # RAG-only answer would be a regression. WLO-MCP calls are cheap so the
    # extra round-trip is acceptable.
    force_tool_use: bool = False
    core_rule: str = ""


# ── Config-driven tables (loaded from YAML on each request) ──────────

def _load_config_tables() -> tuple[dict[str, dict[str, Any]], list[str], dict[str, int], dict[str, str]]:
    """Load signal modulations, reduce_items_signals, device_max_items, persona_formality from config."""
    from app.services.config_loader import load_signal_modulations, load_device_config

    modulations, reduce_items = load_signal_modulations()
    device_cfg = load_device_config()

    device_max = device_cfg.get("device_max_items", {"desktop": 6, "tablet": 4, "mobile": 3})
    formality = device_cfg.get("persona_formality", {"P-AND": "neutral"})

    return modulations, reduce_items, device_max, formality


# ── Pattern loading ──────────────────────────────────────────

def _pattern_from_dict(d: dict[str, Any]) -> PatternDef:
    """Create a PatternDef from a frontmatter dict.

    Uses Pydantic's model_validate which applies defaults for missing fields
    and validates types automatically.
    """
    # Ensure label falls back to id if missing
    if "label" not in d:
        d = {**d, "label": d["id"]}
    return PatternDef.model_validate(d)


def load_patterns() -> list[PatternDef]:
    """Load patterns from config files. Called on each request for live-reload."""
    from app.services.config_loader import load_pattern_definitions

    defs = load_pattern_definitions()
    if not defs:
        logger.warning("No pattern files found in 03-patterns/, using empty list")
        return []

    return [_pattern_from_dict(d) for d in defs]


# Module-level cache (refreshed via get_patterns())
_cached_patterns: list[PatternDef] | None = None


def get_patterns() -> list[PatternDef]:
    """Get current pattern list, reloading from config files each time."""
    return load_patterns()


def phase1_gate(
    patterns: list[PatternDef],
    persona_id: str,
    state_id: str,
    intent_id: str,
    entities: dict[str, Any] | None = None,
) -> tuple[list[PatternDef], list[str]]:
    """Phase 1: Binary elimination. Returns (candidates, eliminated_ids).

    Patterns are eliminated when:
    - persona/state/intent gates don't match, OR
    - precondition_slots are defined but NOT ALL filled (hard gate).
      This prevents patterns like PAT-19 (needs fach+stufe+thema) from
      firing when only fach+stufe are known — the fallback (PAT-18 or
      PAT-06) will catch the request instead.
    """
    _ents = entities or {}
    candidates = []
    eliminated = []
    for p in patterns:
        persona_ok = "*" in p.gate_personas or persona_id in p.gate_personas
        state_ok = "*" in p.gate_states or state_id in p.gate_states
        intent_ok = "*" in p.gate_intents or intent_id in p.gate_intents
        # Hard gate: all precondition_slots must be filled
        precond_ok = True
        if p.precondition_slots:
            precond_ok = all(_ents.get(s) for s in p.precondition_slots)
        if persona_ok and state_ok and intent_ok and precond_ok:
            candidates.append(p)
        else:
            eliminated.append(p.id)
    return candidates, eliminated


def phase2_score(
    candidates: list[PatternDef],
    signals: list[str],
    page: str,
    entities: dict[str, Any],
    intent_confidence: float = 0.8,
) -> dict[str, float]:
    """Phase 2: Weighted ranking among candidates. Returns {pattern_id: score}."""
    scores: dict[str, float] = {}
    for p in candidates:
        # Signal fit (weight 0.30)
        signal_score = 0.0
        for s in signals:
            if s in p.signal_high_fit:
                signal_score += 1.0
            elif s in p.signal_medium_fit:
                signal_score += 0.5
            elif s in p.signal_low_fit:
                signal_score += 0.2
        if signals:
            signal_score = min(signal_score / max(len(signals), 1), 1.0)

        # Context match (weight 0.20)
        context_score = 0.3  # neutral default
        for bonus_page in p.page_bonus:
            if bonus_page == page or (bonus_page.endswith("*") and page.startswith(bonus_page[:-1])):
                context_score = 1.0
                break

        # Precondition completeness (weight 0.30)
        if p.precondition_slots:
            filled = sum(1 for s in p.precondition_slots if entities.get(s))
            pc_ratio = filled / len(p.precondition_slots)
            if pc_ratio >= 1.0:
                pc_score = 1.0
            elif pc_ratio > 0:
                pc_score = 0.6
            else:
                pc_score = 0.2
        else:
            pc_score = 0.8  # no preconditions = mostly fine

        # Intent confidence (weight 0.20)
        conf_score = intent_confidence

        total = (signal_score * 0.30 + context_score * 0.20 +
                 pc_score * 0.30 + conf_score * 0.20)

        # Priority bonus (normalized)
        total += p.priority / 10000.0

        # ── Specificity-Bonus ──────────────────────────────────────
        # Patterns mit konkreten Gate-Listen (z.B. gate_intents=[INT-W-13])
        # sollten gegenüber Wildcard-Patterns (gate_intents=["*"]) gewinnen,
        # wenn beide passen. Sonst bleibt PAT-01 (alle "*") immer am Tisch
        # und beerbt jeden konkreten Pattern, der sich nicht extra hochsetzt.
        #
        # Bonus pro nicht-Wildcard-Gate: 0.01 (3 Gates → max +0.03).
        # Damit kann ein 3-fach spezifischer Pattern selbst gegen einen
        # Wildcard-Pattern mit ~30 Punkten höherer priority bestehen,
        # ein 1-fach spezifischer (z.B. PAT-26 mit gate_intents=[INT-W-13])
        # gegen einen mit ~10 Punkten höherer priority.
        #
        # Hinweis (Kalibrierung 2026-04-28): Vorherige 0.02 hat PAT-08
        # (priority 380, gate_intents=Such-Intents) systematisch über
        # PAT-01 (priority 500, alle Wildcards) gehoben — bei 5+ Tight-
        # Races im Eval-Sample mit gap=0.008 und PAT-08-Misfire bei
        # erfolgreichen Suchen. Mit 0.01 kompensiert der Spec-Bonus
        # nicht mehr den 120-Priority-Diff, PAT-08 verliert sauber, aber
        # PAT-19/21/26/27 (alle nahe priority=470-480) gewinnen weiter
        # gegen PAT-01, weil deren Priority-Diff zu PAT-01 nur ~20-30
        # Punkte (= 0.002-0.003) beträgt — der Bonus überdeckt das.
        spec_bonus = 0.0
        if "*" not in p.gate_intents:
            spec_bonus += 0.01
        if "*" not in p.gate_states:
            spec_bonus += 0.01
        if "*" not in p.gate_personas:
            spec_bonus += 0.01
        total += spec_bonus

        scores[p.id] = round(total, 4)

    return scores


def phase3_modulate(
    pattern: PatternDef,
    signals: list[str],
    device: str,
    entities: dict[str, Any],
    persona_id: str = "P-AND",
) -> dict[str, Any]:
    """Phase 3: Deterministic output adjustment. Returns modulated output config."""
    modulations, reduce_items, device_max, formality = _load_config_tables()

    output = {
        "tone": pattern.default_tone,
        "length": pattern.default_length,
        "detail_level": pattern.default_detail,
        "formality": formality.get(persona_id, "neutral"),
        "response_type": pattern.response_type,
        "sources": pattern.sources,
        "format_primary": pattern.format_primary,
        "format_follow_up": pattern.format_follow_up,
        "card_text_mode": pattern.card_text_mode,
        "max_items": device_max.get(device, 6),
        "tools": list(pattern.tools),
        "force_tool_use": pattern.force_tool_use,
        "core_rule": pattern.core_rule,
        "rag_areas": list(pattern.rag_areas),
        "skip_intro": False,
        "one_option": False,
        "add_sources": False,
    }

    # ── Automatic tool-dependency enforcement ──────────────────
    # Helper tools are always required when search tools are active
    SEARCH_TOOLS = {"search_wlo_collections", "search_wlo_content", "get_collection_contents"}
    HELPER_TOOLS = ["lookup_wlo_vocabulary", "get_node_details"]
    tools = output["tools"]
    if any(t in SEARCH_TOOLS for t in tools):
        for h in HELPER_TOOLS:
            if h not in tools:
                tools.append(h)

    # Apply signal modulations (deterministic IF-THEN)
    for signal in signals:
        mods = modulations.get(signal, {})
        for key, val in mods.items():
            output[key] = val

    # Signal override for max_items
    if any(s in signals for s in reduce_items):
        output["max_items"] = min(output["max_items"], 3)

    # Degradation: if preconditions incomplete, activate parallel soft probe
    if pattern.precondition_slots:
        missing = [s for s in pattern.precondition_slots if not entities.get(s)]
        if missing:
            output["degradation"] = True
            output["missing_slots"] = missing

    return output


def select_pattern(
    persona_id: str,
    state_id: str,
    intent_id: str,
    signals: list[str],
    page: str,
    device: str,
    entities: dict[str, Any],
    intent_confidence: float = 0.8,
    enforced_pattern_id: str | None = None,
) -> tuple[PatternDef, dict[str, Any], dict[str, float], list[str]]:
    """Run all 3 phases and return (winner, modulated_output, scores, eliminated).

    If ``enforced_pattern_id`` is given (e.g. from the Safety layer), that
    pattern is loaded directly and the normal Gate→Score phases are skipped.
    Its ``core_rule`` and ``tools``/``sources`` are honoured so the LLM gets
    a proper instruction (instead of just having tone/length overridden on
    whatever pattern happened to win the scoring phase).
    """
    patterns = get_patterns()

    # ── Safety override: skip gating/scoring, load the enforced pattern ──
    if enforced_pattern_id:
        enforced = next((p for p in patterns if p.id == enforced_pattern_id), None)
        if enforced is not None:
            output = phase3_modulate(enforced, signals, device, entities, persona_id)
            return enforced, output, {enforced.id: 1.0}, []

    candidates, eliminated = phase1_gate(patterns, persona_id, state_id, intent_id, entities)

    if not candidates:
        # Fallback: use PAT-17 (Sanfter Einstieg)
        fallback = next((p for p in patterns if p.id == "PAT-17"), patterns[0])
        output = phase3_modulate(fallback, signals, device, entities, persona_id)
        return fallback, output, {}, eliminated

    scores = phase2_score(candidates, signals, page, entities, intent_confidence)

    winner_id = max(scores, key=scores.get)
    winner = next(p for p in candidates if p.id == winner_id)

    output = phase3_modulate(winner, signals, device, entities, persona_id)

    # Propagate missing-slot info from patterns with precondition_slots,
    # but ONLY when the user's intent actually targets complex tasks
    # (learning paths, lesson plans). Normal search intents should not
    # trigger degradation just because PAT-18/19 have preconditions.
    _COMPLEX_INTENTS = {"INT-W-10"}  # Unterrichtsplanung / Lernpfad
    _ents = entities or {}
    if intent_id in _COMPLEX_INTENTS:
        for p in patterns:
            if p.precondition_slots:
                missing = [s for s in p.precondition_slots if not _ents.get(s)]
                if missing:
                    output.setdefault("degradation", True)
                    prev = output.get("missing_slots", [])
                    output["missing_slots"] = list(set(prev + missing))
                    output.setdefault("blocked_patterns", [])
                    output["blocked_patterns"].append(
                        {"id": p.id, "label": p.label, "missing": missing}
                    )

    return winner, output, scores, eliminated
