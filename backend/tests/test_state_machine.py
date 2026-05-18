"""Tests for the Conversation State Machine validator (Welle C Sprint 6).

Verifies that validate_transition correctly identifies plausible vs
implausible state transitions based on next_likely from 04-states/states.yaml.

The validator is telemetry-only by default (auto_correct=False) — it
detects implausible transitions but doesn't change them. Harder
corrections happen via the routing-rules engine (rule_state12_guard etc.).
"""
import pytest

from app.services.state_machine import validate_transition


# ── Plausible transitions ───────────────────────────────────────────


@pytest.mark.parametrize("prev, next_", [
    ("state-1", "state-2"),   # Orientierung → Slot-Erfassung
    ("state-1", "state-5"),   # Orientierung → Suche (direkt mit vollen Slots)
    ("state-2", "state-5"),   # Slot-Erfassung → Suche
    ("state-5", "state-6"),   # Suche → Ergebnis-Kuratierung
    ("state-6", "state-7"),   # Ergebnis-Kuratierung → Verfeinerung
    ("state-6", "state-9"),   # Ergebnis-Kuratierung → Feedback
    ("state-7", "state-6"),   # Verfeinerung → erneut Ergebnisse
    ("state-8", "state-12"),  # Lernen & Arbeiten → Canvas-Arbeit
    ("state-9", "state-7"),   # Feedback → Verfeinerung
    ("state-12", "state-12"), # Canvas-Self-Loop (mehrere Edits)
])
def test_plausible_transition(prev, next_):
    """Transitions in next_likely should be reported as plausible."""
    result = validate_transition(prev, next_)
    assert result["plausible"] is True, \
        f"Expected {prev}→{next_} to be plausible, got reason: {result.get('reason')}"
    assert result["validated_state"] == next_
    assert result["reason"] == ""


# ── Implausible transitions (telemetry-only, no correction) ─────────


@pytest.mark.parametrize("prev, next_, expected_in_reason", [
    ("state-12", "state-3", "next_likely"),   # Canvas → Information ohne Reset
    ("state-12", "state-4", "next_likely"),   # Canvas → Erkundung ohne Reset
    ("state-6", "state-1", "next_likely"),    # Ergebnisse → Orientierung zurück
    # state-9 → state-12 ist seit Sprint 6 plausibel (next_likely erweitert,
    # User wechselt aus Feedback in Canvas-Erstellung). Test entfernt.
])
def test_implausible_transition_telemetry(prev, next_, expected_in_reason):
    """Transitions NOT in next_likely should flag as implausible but stay."""
    result = validate_transition(prev, next_, auto_correct=False)
    assert result["plausible"] is False
    assert expected_in_reason in result["reason"]
    # auto_correct=False keeps the original next_state
    assert result["validated_state"] == next_


# ── Canvas-intent override ─────────────────────────────────────────


def test_canvas_intent_override_plausible():
    """INT-W-11/12 → state-12 is always plausible, regardless of prev."""
    result = validate_transition(prev="state-3", next_="state-12", intent="INT-W-11")
    assert result["plausible"] is True
    assert "canvas-intent override" in result["reason"]


def test_canvas_intent_override_only_for_canvas_intents():
    """Other intents don't get the state-12 override."""
    result = validate_transition(prev="state-3", next_="state-12", intent="INT-W-06")
    assert result["plausible"] is False


# ── Edge cases ──────────────────────────────────────────────────────


def test_empty_prev_always_plausible():
    """First turn (no prev): any next_state is plausible."""
    result = validate_transition(prev="", next_="state-5")
    assert result["plausible"] is True


def test_self_loop_plausible():
    """state-X → state-X always allowed (e.g. another slot in state-2)."""
    result = validate_transition(prev="state-2", next_="state-2")
    assert result["plausible"] is True


def test_unknown_prev_state_treated_permissively():
    """If prev-state has no next_likely (unknown id), default to plausible."""
    result = validate_transition(prev="state-999", next_="state-1")
    # Permissive: avoid breaking the conversation on unknown states.
    assert result["plausible"] is True


# ── Auto-correct mode ──────────────────────────────────────────────


def test_auto_correct_falls_back_to_first_next_likely():
    """With auto_correct=True, implausible transition snaps to first next_likely."""
    result = validate_transition(
        prev="state-12", next_="state-3", auto_correct=True,
    )
    assert result["plausible"] is False
    # state-12's next_likely starts with state-12 (self-loop) — first entry
    assert result["validated_state"] in {"state-12", "state-9", "state-5"}
    assert "korrigiert" in result["reason"]
