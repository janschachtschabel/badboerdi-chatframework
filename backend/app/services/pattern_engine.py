"""Pattern Selection — Hint-Primary (Welle E v4, 2026-05-25).

Schlanke Engine: der LLM-Klassifikator wählt das Pattern via
``pattern_id_hint``. Phase 1 (Gate) und Phase 2 (Score) wurden entfernt
— sie waren im aktuellen Setup tot, weil der Hint-Shortcut immer
griff. Konkrete Belege für die Entfernung in ``eval-c4c0e552dd30``:

  * ``eliminated_count = 0`` in 48/48 Turns  → Phase 1 lief nie
  * ``phase2_score = 1.0`` einheitlich        → Phase 2 lief nie
  * ``runner_up = ''`` in 48/48 Turns         → kein Score-Race

Was die schlanke Engine kann:

1.  ``enforced_pattern_id``  (Safety + Pre-Route-Rules)        — höchste Prio
2.  ``pattern_id_hint``      (LLM-Klassifikator)               — primärer Pfad
3.  Fallback auf ``M15`` (Orientierung)                        — defensiv

``phase3_modulate`` bleibt erhalten: Persona-Tone-Modifier, Length-Bias,
Formality, Card-Mode, Tool-Listen, Sources, RAG-Areas, Pattern-Body,
Slot-Degradation. Das ist die Stil-/Inhalt-Schicht und wird IMMER
ausgeführt — auch im Safety-Pfad.

Wer das alte 3-Phasen-System wiederhaben will, schaut ins Backup-Repo
(``backup/backend/app/services/pattern_engine.py``).
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PatternDef(BaseModel):
    """Pattern definition loaded from ``03-patterns/*.md`` config files.

    Welle E v4 (2026-05-25): Gate-/Signal-/Page-Bonus-Felder entfernt —
    der LLM-Hint wählt das Pattern, keine deterministische Mathematik
    mehr. ``priority`` bleibt als Listing-Hint für den Klassifikator-
    Prompt (Reihenfolge in der Pattern-Liste).
    """

    id: str
    label: str
    priority: int = 400
    # Slot-Vorbedingung (für Degradation-Flag in phase3_modulate, NICHT
    # für Pattern-Selektion). M09 braucht ``topic``, M10 braucht
    # ``material_type`` + ``topic``.
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
    # tool output (cards) is the actual user-facing payload.
    force_tool_use: bool = False
    # Phase B1 — Multi-Step-Tools: when True, the Reflection-Loop insists
    # that ALL listed tools were called (full coverage), not just one.
    requires_all_tools: bool = False
    # Welle B.5: When True, the post-LLM cards-list is filtered to only
    # contain cards whose URL/node_id/title appears in the response text.
    card_text_link_required: bool = False
    core_rule: str = ""
    forbidden_phrases: list[str] = Field(default_factory=list)
    anti_patterns: list[str] = Field(default_factory=list)
    short_purpose: str = ""
    # Welle E v4+7 (2026-05-26) — strukturierte Pattern-Auswahl-Regeln.
    # Ersetzt die zentralen pattern_disambiguators aus classify-overrides.
    # yaml mit pro-Pattern-Definitionen (Single-Source-of-Truth).
    when_to_use: list[str] = Field(default_factory=list)
    when_not_to_use: list[str] = Field(default_factory=list)
    trigger_phrases: list[str] = Field(default_factory=list)
    # discriminators: Liste von {vs: M-OtherID, rule: "...", example: "..."}
    discriminators: list[dict[str, str]] = Field(default_factory=list)
    # 2026-05-23 — Vollständiger Pattern-Markdown-Body (Anti-Patterns,
    # persona-spezifische Antwort-Schemas, Quick-Reply-Tabellen).
    body_md: str = ""


# ── Config-driven tables (loaded from YAML on each request) ──────────

def _load_config_tables() -> tuple[
    dict[str, dict[str, Any]], list[str], dict[str, int], dict[str, str]
]:
    """Load signal modulations, reduce_items_signals, device_max_items,
    persona_formality from config.

    Welle E v4: weiterhin gebraucht von ``phase3_modulate`` für Signal-
    Tone-Modulationen + Geräte-Limits + Formality-Fallback. Tie-Breaker-
    Tabelle wurde entfernt.
    """
    from app.services.config_loader import load_signal_modulations, load_device_config

    modulations, reduce_items = load_signal_modulations()
    device_cfg = load_device_config()

    device_max = device_cfg.get("device_max_items", {"desktop": 6, "tablet": 4, "mobile": 3})
    formality = device_cfg.get("persona_formality", {"P-AND": "neutral"})

    return modulations, reduce_items, device_max, formality


# ── Pattern loading ──────────────────────────────────────────

def _pattern_from_dict(d: dict[str, Any]) -> PatternDef:
    """Create a PatternDef from a frontmatter dict.

    Welle E v4: deprecated Felder (``gate_personas``, ``gate_states``,
    ``gate_intents``, ``signal_high_fit``, ``signal_medium_fit``,
    ``signal_low_fit``, ``page_bonus``) werden im Loader still ignoriert
    falls noch in MDs vorhanden (Backward-Compat während der Migration).
    """
    # Ensure label falls back to id if missing
    if "label" not in d:
        d = {**d, "label": d["id"]}
    # Backward-Compat: deprecated Felder dropen, falls die MD-Datei sie
    # noch enthält. Pydantic würde sonst extra="ignore" als Default
    # nutzen — wir machen es explizit, damit Logs sauber bleiben.
    legacy_fields = (
        "gate_personas", "gate_states", "gate_intents",
        "signal_high_fit", "signal_medium_fit", "signal_low_fit",
        "page_bonus",
    )
    if any(k in d for k in legacy_fields):
        d = {k: v for k, v in d.items() if k not in legacy_fields}
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


# ── Phase 3 — Modulate (Stil-/Tool-Schicht) ──────────────────────────

_LENGTH_RANK = {"kurz": 0, "mittel": 1, "lang": 2}
_LENGTH_BY_RANK = {0: "kurz", 1: "mittel", 2: "lang"}


def _apply_length_bias(default_length: str, length_bias: float) -> str:
    """Wendet einen Length-Bias [-0.3..+0.3] auf eine Default-Länge an.

    Bias > +0.15 → shift +1 (kurz→mittel→lang)
    Bias < -0.15 → shift -1
    Sonst       → unverändert
    Clamped auf [0..2].
    """
    rank = _LENGTH_RANK.get(default_length, 1)
    if length_bias > 0.15:
        rank += 1
    elif length_bias < -0.15:
        rank -= 1
    rank = max(0, min(2, rank))
    return _LENGTH_BY_RANK[rank]


def phase3_modulate(
    pattern: PatternDef,
    signals: list[str],
    device: str,
    entities: dict[str, Any],
    persona_id: str = "P-AND",
) -> dict[str, Any]:
    """Phase 3: Deterministische Output-Modulation. Returns modulated config.

    Welle E v4 (2026-05-25): Phase 3 ist die einzige verbliebene
    deterministische Schicht. Persona wirkt hier ausschließlich auf
    Stil/Anrede/Länge, nicht auf Pattern-Wahl.
    """
    from app.services.config_loader import get_tone_modifier_for_persona

    modulations, reduce_items, device_max, formality = _load_config_tables()

    # Persona-Tonalitäts-Modifier — Quelle: tone-modifiers.yaml
    tone_mod = get_tone_modifier_for_persona(persona_id)
    _mod_override = bool(tone_mod.get("override", False))
    _pattern_tone_is_default = pattern.default_tone in ("sachlich", "neutral", "")
    _pattern_card_is_default = pattern.card_text_mode in ("minimal", "")

    # Effective tone: Modifier override OR Pattern is at default → Modifier wins
    effective_tone = (
        tone_mod["tone"]
        if (_mod_override or _pattern_tone_is_default)
        else pattern.default_tone
    )

    # Effective length: bias auf pattern.default_length anwenden
    effective_length = _apply_length_bias(pattern.default_length, tone_mod["length_bias"])

    # Effective formality: Modifier siegt (Persona bestimmt Anrede)
    if tone_mod["formality"] == "wie_user":
        # Fallback auf device_config-Formality, falls modifier neutral lässt
        effective_formality = formality.get(persona_id, "neutral")
    else:
        effective_formality = tone_mod["formality"]

    # Effective card_text_mode: Modifier siegt nur bei override OR Pattern-Default
    effective_card_text_mode = (
        tone_mod["card_text_mode"]
        if (_mod_override or _pattern_card_is_default)
        else pattern.card_text_mode
    )

    output = {
        "tone": effective_tone,
        "length": effective_length,
        "detail_level": pattern.default_detail,
        "formality": effective_formality,
        "response_type": pattern.response_type,
        "sources": pattern.sources,
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
        "body_md": pattern.body_md,
        # Welle E v4+7 (2026-05-26): strukturierte Pattern-Auswahl-Regeln
        # durchschleifen, damit Response-Prompt sie als Kontext-Briefing
        # rendern und Eval-Judge sie zur Pattern-Match-Bewertung nutzen
        # kann.
        "when_to_use": list(pattern.when_to_use),
        "when_not_to_use": list(pattern.when_not_to_use),
        "trigger_phrases": list(pattern.trigger_phrases),
        "discriminators": list(pattern.discriminators),
        "forbidden_phrases": list(pattern.forbidden_phrases),
        "anti_patterns": list(pattern.anti_patterns),
        "rag_areas": list(pattern.rag_areas),
        "skip_intro": False,
        "one_option": False,
        "add_sources": False,
        # Trace-Felder: Modifier-Anwendung sichtbar machen für Debug + Studio
        "_tone_modifier_persona": persona_id,
        "_tone_modifier_override": _mod_override,
        "_tone_modifier_pattern_default_tone": pattern.default_tone,
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


# ── Pattern Selection — Hint-Primary ─────────────────────────────────


_FALLBACK_PATTERN_IDS: tuple[str, ...] = ("M15", "M03")


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
) -> tuple[PatternDef, dict[str, Any], dict[str, float], list[str]]:
    """Welle E v4: Hint-driven pattern selection (Safety → Hint → Fallback).

    Reihenfolge:
      1. ``enforced_pattern_id`` (Safety + Pre-Route-Rules)
      2. ``pattern_id_hint`` (Klassifikator-LLM)
      3. Fallback (``M15`` Orientierung, sonst ``M03`` Klärung, sonst
         erstes verfügbares Pattern)

    Rückgabe-Tuple (für Kompatibilität mit chat.py):
      * ``winner``      — PatternDef
      * ``output``      — phase3-modulierter Output-Dict
      * ``scores``      — {winner.id: 1.0} (legacy-Form, einziges Pattern
                          gewinnt mit Score 1.0)
      * ``eliminated``  — [] (Phase 1 läuft nicht mehr; leere Liste
                          erhält Kompatibilität mit Trace-Code)
    """
    patterns = get_patterns()

    if not patterns:
        raise RuntimeError(
            "No patterns loaded — check 03-patterns/*.md files in active config"
        )

    # 1. Safety / Pre-Route enforced
    if enforced_pattern_id:
        enforced = next((p for p in patterns if p.id == enforced_pattern_id), None)
        if enforced is not None:
            output = phase3_modulate(enforced, signals, device, entities, persona_id)
            return enforced, output, {enforced.id: 1.0}, []
        logger.warning(
            "enforced_pattern_id=%r not in loaded patterns — falling through to hint",
            enforced_pattern_id,
        )

    # 2. LLM-Hint primary
    if pattern_id_hint:
        hinted = next((p for p in patterns if p.id == pattern_id_hint), None)
        if hinted is not None:
            output = phase3_modulate(hinted, signals, device, entities, persona_id)
            return hinted, output, {hinted.id: 1.0}, []
        logger.warning(
            "pattern_id_hint=%r unknown (not in 03-patterns/) — using fallback",
            pattern_id_hint,
        )

    # 3. Fallback
    fallback = next(
        (p for p in patterns if p.id in _FALLBACK_PATTERN_IDS),
        patterns[0],
    )
    output = phase3_modulate(fallback, signals, device, entities, persona_id)
    return fallback, output, {fallback.id: 1.0}, []
