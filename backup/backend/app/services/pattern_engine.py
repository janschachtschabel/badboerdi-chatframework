"""LLM-Hint-driven Pattern Selection (Welle E refactor, 2026-05-17).

Drastisch vereinfacht gegenüber der historischen 3-Phasen-Engine.  Die
Pattern-Wahl ist jetzt:

1.  ``enforced_pattern_id`` (Safety-Layer)             — höchste Prio
2.  ``pattern_id_hint`` (LLM-Klassifikator)            — Standardpfad
3.  Fallback auf das Klärungs-Pattern (``P13``)        — wenn weder
                                                         enforced noch hint
                                                         verwertbar

Was wir bewusst weggelassen haben (alles im Backup-Repo nachschlagbar):

* ``phase1_gate``  — Persona/State/Intent-Gates sind nur noch Telemetrie.
                     Pattern-Wahl wird nicht mehr durch sie blockiert.
* ``phase2_score`` — Scoring-Gewichtung entfällt komplett.  Der LLM-Hint
                     ersetzt das deterministische Ranking.
* ``tie_breaker``  — Welle D Mechanik obsolet, weil der LLM-Hint direkt
                     das Ziel-Pattern liefert.
* ``persona_loosening`` — Persona-Traits sind nicht mehr im Routing
                     (siehe Tone-Modifier in phase3_modulate).

Was erhalten bleibt:

* ``phase3_modulate`` — wandelt die Pattern-Definition in das Output-
                        Config (Tools, Sources, Tone via Persona-
                        Modifier, max_items je Device, …).
* ``PatternDef``      — Frontmatter-Schema; ``gate_*``-Felder bleiben
                        als optionale Telemetrie-Markierung.

Wer das alte Verhalten wiederhaben will, schaltet das Backup-Repo zurück.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Pattern definition ──────────────────────────────────────────────


class PatternDef(BaseModel):
    """Pattern definition loaded from ``03-patterns/*.md`` config files.

    Felder, die für die Welle-E-Engine wirklich gebraucht werden:

    * ``id``, ``label``, ``short_purpose``, ``core_rule``
    * ``sources``, ``tools``, ``rag_areas``
    * ``response_type``, ``format_primary``, ``format_follow_up``
    * ``default_tone``, ``default_length``, ``default_detail``
    * ``precondition_slots``, ``card_text_mode``
    * ``force_tool_use``, ``requires_all_tools``, ``card_text_link_required``

    Felder, die nur noch **Telemetrie** sind (LLM-Hint kann sie ignorieren,
    aber der Eval-Aggregator zeigt Gate-Verletzungen für Auswertung):

    * ``gate_personas``, ``gate_states``, ``gate_intents``

    Felder, die im Welle-E-Modell nicht mehr eingesetzt werden, aber im
    Modell bestehen bleiben damit alte YAMLs ohne Fehler laden:

    * ``priority`` (Phase-2-Scoring ist weg)
    * ``signal_high_fit`` / ``signal_medium_fit`` / ``signal_low_fit``
    * ``page_bonus``
    """
    id: str
    label: str
    short_purpose: str = ""
    core_rule: str = ""

    # Engine-Konfiguration (aktiv genutzt)
    sources: list[str] = Field(default_factory=lambda: ["mcp"])
    tools: list[str] = Field(default_factory=list)
    rag_areas: list[str] = Field(default_factory=list)
    response_type: str = "answer"
    format_primary: str = "text"
    format_follow_up: str = "quick_replies"
    default_tone: str = "sachlich"
    default_length: str = "mittel"
    default_detail: str = "standard"
    precondition_slots: list[str] = Field(default_factory=list)
    card_text_mode: str = "minimal"  # minimal | reference | highlight
    force_tool_use: bool = False
    requires_all_tools: bool = False
    card_text_link_required: bool = False

    # Telemetrie-Felder (Gate-Verletzungen für Eval-Auswertung; nicht
    # routing-aktiv)
    gate_personas: list[str] = Field(default_factory=lambda: ["*"])
    gate_states: list[str] = Field(default_factory=lambda: ["*"])
    gate_intents: list[str] = Field(default_factory=lambda: ["*"])

    # Deprecated / nur für Backwards-Kompat zum alten YAML-Schema:
    priority: int = 400
    signal_high_fit: list[str] = Field(default_factory=list)
    signal_medium_fit: list[str] = Field(default_factory=list)
    signal_low_fit: list[str] = Field(default_factory=list)
    page_bonus: list[str] = Field(default_factory=list)


# ── Pattern loading ──────────────────────────────────────────


def _pattern_from_dict(d: dict[str, Any]) -> PatternDef:
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


def get_patterns() -> list[PatternDef]:
    """Get current pattern list, reloading from config files each time."""
    return load_patterns()


# ── Config-driven output-modulation tables ────────────────────────


def _load_config_tables() -> tuple[dict[str, dict[str, Any]], list[str], dict[str, int], dict[str, str]]:
    """Lädt signal_modulations, reduce_items_signals, device_max_items, persona_formality."""
    from app.services.config_loader import load_signal_modulations, load_device_config

    modulations, reduce_items = load_signal_modulations()
    device_cfg = load_device_config()
    device_max = device_cfg.get("device_max_items", {"desktop": 6, "tablet": 4, "mobile": 3})
    formality = device_cfg.get("persona_formality", {"P-AND": "neutral"})
    return modulations, reduce_items, device_max, formality


_LENGTH_RANK = {"kurz": 0, "mittel": 1, "lang": 2}
_LENGTH_BY_RANK = {0: "kurz", 1: "mittel", 2: "lang"}


def _apply_length_bias(default_length: str, length_bias: float) -> str:
    """Wendet einen Length-Bias [-0.3..+0.3] auf eine Default-Länge an."""
    rank = _LENGTH_RANK.get(default_length, 1)
    if length_bias > 0.15:
        rank += 1
    elif length_bias < -0.15:
        rank -= 1
    rank = max(0, min(2, rank))
    return _LENGTH_BY_RANK[rank]


# ── Phase 3: Output modulation ────────────────────────────────────


def phase3_modulate(
    pattern: PatternDef,
    signals: list[str],
    device: str,
    entities: dict[str, Any],
    persona_id: str = "P-AND",
) -> dict[str, Any]:
    """Wandelt eine Pattern-Definition in das Output-Config-Dict um.

    Welle E (2026-05): Persona steuert hier ausschließlich Tone/Length/
    Formality/card_text_mode — nicht mehr die Pattern-Auswahl.  Die
    Pattern-Wahl ist bereits in select_pattern abgeschlossen, hier wird
    nur noch das Output-Format konfiguriert.
    """
    from app.services.config_loader import get_tone_modifier_for_persona

    modulations, reduce_items, device_max, formality = _load_config_tables()

    # Persona-Tonalitäts-Modifier (tone-modifiers.yaml)
    tone_mod = get_tone_modifier_for_persona(persona_id)
    _mod_override = bool(tone_mod.get("override", False))
    _pattern_tone_is_default = pattern.default_tone in ("sachlich", "neutral", "")
    _pattern_card_is_default = pattern.card_text_mode in ("minimal", "")

    effective_tone = (
        tone_mod["tone"]
        if (_mod_override or _pattern_tone_is_default)
        else pattern.default_tone
    )
    effective_length = _apply_length_bias(pattern.default_length, tone_mod["length_bias"])
    if tone_mod["formality"] == "wie_user":
        effective_formality = formality.get(persona_id, "neutral")
    else:
        effective_formality = tone_mod["formality"]
    effective_card_text_mode = (
        tone_mod["card_text_mode"]
        if (_mod_override or _pattern_card_is_default)
        else pattern.card_text_mode
    )

    output: dict[str, Any] = {
        "tone": effective_tone,
        "length": effective_length,
        "detail_level": pattern.default_detail,
        "formality": effective_formality,
        "response_type": pattern.response_type,
        "sources": list(pattern.sources),
        "format_primary": pattern.format_primary,
        "format_follow_up": pattern.format_follow_up,
        "card_text_mode": effective_card_text_mode,
        "max_items": device_max.get(device, 6),
        "tools": list(pattern.tools),
        "force_tool_use": pattern.force_tool_use,
        "requires_all_tools": pattern.requires_all_tools,
        "card_text_link_required": pattern.card_text_link_required,
        "core_rule": pattern.core_rule,
        "short_purpose": pattern.short_purpose,
        "rag_areas": list(pattern.rag_areas),
        "skip_intro": False,
        "one_option": False,
        "add_sources": False,
        # Trace-Felder
        "_tone_modifier_persona": persona_id,
        "_tone_modifier_override": _mod_override,
        "_tone_modifier_pattern_default_tone": pattern.default_tone,
    }

    # Automatic helper-tool enforcement: search → vocab + node_details
    SEARCH_TOOLS = {"search_wlo_collections", "search_wlo_content", "get_collection_contents"}
    HELPER_TOOLS = ["lookup_wlo_vocabulary", "get_node_details"]
    tools = output["tools"]
    if any(t in SEARCH_TOOLS for t in tools):
        for h in HELPER_TOOLS:
            if h not in tools:
                tools.append(h)

    # Signal-driven output modulation (deterministic IF-THEN aus YAML)
    for signal in signals:
        mods = modulations.get(signal, {})
        for key, val in mods.items():
            output[key] = val
    if any(s in signals for s in reduce_items):
        output["max_items"] = min(output["max_items"], 3)

    # Precondition-Slots als Output-Telemetrie (Slot-Klärung-Indikator).
    # Die echte Klärung passiert über Pattern P13 (Slot-Klärung), wenn der
    # LLM-Hint darauf zeigt; hier markieren wir nur, damit der LLM weiß,
    # welche Slots fehlen.
    if pattern.precondition_slots:
        missing = [s for s in pattern.precondition_slots if not entities.get(s)]
        if missing:
            output["degradation"] = True
            output["missing_slots"] = missing

    return output


# ── Gate-Telemetrie (informativ, nicht routing-aktiv) ──────────────


def _gate_violations(
    p: PatternDef,
    persona_id: str,
    state_id: str,
    intent_id: str,
    entities: dict[str, Any] | None,
) -> list[str]:
    """Welche der nominal definierten Gates würde das Pattern verletzen?

    Liste bleibt im Output stehen, beeinflusst aber NICHT mehr die
    Pattern-Wahl. Der Eval-Aggregator zählt Gate-Verletzungen, um zu
    sehen, ob der LLM-Hint sich systematisch über Gates hinwegsetzt.
    """
    violations: list[str] = []
    _ents = entities or {}
    if "*" not in p.gate_personas and persona_id not in p.gate_personas:
        violations.append(f"persona({persona_id} not in {p.gate_personas})")
    if "*" not in p.gate_states and state_id not in p.gate_states:
        violations.append(f"state({state_id} not in {p.gate_states})")
    if "*" not in p.gate_intents and intent_id not in p.gate_intents:
        violations.append(f"intent({intent_id} not in {p.gate_intents})")
    if p.precondition_slots:
        missing = [s for s in p.precondition_slots if not _ents.get(s)]
        if missing:
            violations.append(f"precondition_slots(missing: {missing})")
    return violations


# ── Pattern selection — Welle E LLM-Hint primary ──────────────────


# Fallback-Reihenfolge: erstes vorhandenes Pattern aus dieser Liste wird
# gewählt, wenn weder enforced_pattern_id noch pattern_id_hint verwertbar
# sind.  P13 = Slot-Klärung, sonst irgendein verfügbares Pattern.
_FALLBACK_ORDER: tuple[str, ...] = ("P13", "PAT-02", "PAT-20")


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
    pattern_id_hint: str | None = None,
    selection_mode: str | None = None,  # legacy parameter, ignored
) -> tuple[PatternDef, dict[str, Any], dict[str, float], list[str]]:
    """Welle E: LLM-Hint-driven pattern selection.

    Returns ``(winner, modulated_output, scores, eliminated)``.
    ``scores`` ist nur noch ``{winner_id: 1.0}`` — Phase-2 ist weg.
    ``eliminated`` ist immer leer — Phase-1 ist weg.

    ``selection_mode`` ist nur noch ein Argument für Backwards-Kompat
    (z.B. wenn der Eval-Runner es noch durchreicht); es hat keinen
    Effekt mehr.
    """
    patterns = get_patterns()
    if not patterns:
        raise RuntimeError(
            "No patterns loaded — backend configuration broken. "
            "Check chatbots/wlo/v1/03-patterns/.",
        )

    # 1. Safety-Override (immer Vorrang)
    if enforced_pattern_id:
        enforced = next((p for p in patterns if p.id == enforced_pattern_id), None)
        if enforced is not None:
            output = phase3_modulate(enforced, signals, device, entities, persona_id)
            output["selection_mode"] = "enforced"
            return enforced, output, {enforced.id: 1.0}, []
        logger.warning(
            "enforced_pattern_id '%s' unknown — falling back to LLM-Hint.",
            enforced_pattern_id,
        )

    # 2. LLM-Hint (Standardpfad)
    if pattern_id_hint:
        hinted = next((p for p in patterns if p.id == pattern_id_hint), None)
        if hinted is not None:
            violations = _gate_violations(hinted, persona_id, state_id, intent_id, entities)
            output = phase3_modulate(hinted, signals, device, entities, persona_id)
            output["selection_mode"] = "llm_hint"
            output["gate_violations"] = violations
            output["gate_violation_count"] = len(violations)
            return hinted, output, {hinted.id: 1.0}, []
        logger.warning(
            "pattern_id_hint '%s' unknown — falling back to %s.",
            pattern_id_hint, _FALLBACK_ORDER[0],
        )

    # 3. Fallback (kein Hint vom Klassifikator, z.B. weil LLM-Call failed)
    fallback = None
    for fb_id in _FALLBACK_ORDER:
        fallback = next((p for p in patterns if p.id == fb_id), None)
        if fallback is not None:
            break
    if fallback is None:
        fallback = patterns[0]
    output = phase3_modulate(fallback, signals, device, entities, persona_id)
    output["selection_mode"] = "fallback"
    return fallback, output, {fallback.id: 1.0}, []


# ── Legacy compat: Stubs für Code, der noch phase1_gate / phase2_score importiert ──


def phase1_gate(*args: Any, **kwargs: Any) -> tuple[list[PatternDef], list[str]]:
    """Welle E: Phase-1-Gate entfernt. Stub für Backwards-Kompat.

    Gibt alle Patterns als Kandidaten zurück, niemandem werden mehr
    eliminiert.  Nur noch von Tests aufgerufen, die das alte Verhalten
    erwarten — gibt einen leichten Hinweis im Log, dass die Funktion
    obsolet ist.
    """
    logger.debug("phase1_gate is a no-op since Welle E — returning all patterns")
    patterns = get_patterns()
    return patterns, []


def phase2_score(*args: Any, **kwargs: Any) -> dict[str, float]:
    """Welle E: Phase-2-Scoring entfernt. Stub für Backwards-Kompat."""
    logger.debug("phase2_score is a no-op since Welle E — returning empty score map")
    return {}
