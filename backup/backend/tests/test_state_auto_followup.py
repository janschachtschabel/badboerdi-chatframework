"""Test the state-6 auto-followup trigger (Welle C Sprint 6).

In state-6 (Ergebnis-Kuratierung) the bot deterministically appends a
"Hat das geholfen?" quick-reply if results were shown and none of the
LLM-generated QRs already asks for pass-quality. This sits outside the
LLM-QR generator so it's robust against LLM drift.
"""
import pytest

from app.routers.chat import _apply_state_auto_followup


def test_state6_with_cards_appends_followup():
    """state-6 + cards present + no pass-QR: appends 'Hat das geholfen?'."""
    out = _apply_state_auto_followup(
        state_id="state-6",
        quick_replies=["Mehr davon", "Andere Stufe"],
        has_cards=True,
    )
    assert "Hat das geholfen?" in out
    assert len(out) == 3


def test_state6_no_cards_no_followup():
    """No cards → no auto-followup (nothing to evaluate)."""
    out = _apply_state_auto_followup(
        state_id="state-6",
        quick_replies=["Mehr davon"],
        has_cards=False,
    )
    assert "Hat das geholfen?" not in out
    assert out == ["Mehr davon"]


def test_other_state_no_followup():
    """Auto-followup is state-6-only (other states untouched)."""
    for state in ["state-1", "state-2", "state-5", "state-9", "state-12"]:
        out = _apply_state_auto_followup(
            state_id=state,
            quick_replies=["X", "Y"],
            has_cards=True,
        )
        assert "Hat das geholfen?" not in out, \
            f"state {state} should not auto-append"


def test_duplicate_prevention_geholfen():
    """If LLM already asked 'Hat es geholfen?' don't duplicate."""
    qrs = ["Andere Stufe", "Hat dir das geholfen?"]
    out = _apply_state_auto_followup(
        state_id="state-6", quick_replies=qrs, has_cards=True,
    )
    # Idempotent: still 2 entries, no duplicate
    assert len(out) == 2
    assert sum(1 for q in out if "geholfen" in q.lower()) == 1


def test_duplicate_prevention_gepasst():
    """Various spellings of 'pass quality' all prevent duplication."""
    qrs = ["Hat das gepasst?"]
    out = _apply_state_auto_followup(
        state_id="state-6", quick_replies=qrs, has_cards=True,
    )
    assert len(out) == 1


def test_qr_list_capped_at_4():
    """If 4 QRs are already there, replace the last instead of growing the list."""
    qrs = ["A", "B", "C", "D"]
    out = _apply_state_auto_followup(
        state_id="state-6", quick_replies=qrs, has_cards=True,
    )
    assert len(out) == 4
    assert out[-1] == "Hat das geholfen?"
    assert out[:-1] == ["A", "B", "C"]


def test_empty_quick_replies_get_followup():
    """Empty QR list → just the auto-followup."""
    out = _apply_state_auto_followup(
        state_id="state-6", quick_replies=[], has_cards=True,
    )
    assert out == ["Hat das geholfen?"]
