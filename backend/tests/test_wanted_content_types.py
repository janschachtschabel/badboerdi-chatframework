"""Tests for the medientyp filter persistence (Welle C Sprint 6 Hotfix).

User-Report: After an initial "Material zu Klimawandel" query (Bot
shows collections + topic pages + content), the user says "nur Videos
zeigen" — but collections still appear. The fix wires
``_resolve_wanted_content_types`` to also pull ``entities.medientyp``
from session_state and classification, not just from the current
user-message string.
"""
import pytest

from app.routers.chat import (
    _extract_wanted_content_types,
    _resolve_wanted_content_types,
)


# ── Baseline: message-only extractor still works ─────────────────────


def test_extract_from_message_video_keyword():
    assert "video" in _extract_wanted_content_types("nur videos zeigen")


def test_extract_from_message_arbeitsblatt():
    assert "arbeitsblatt" in _extract_wanted_content_types(
        "such mir arbeitsblätter zu bruchrechnung"
    )


def test_extract_empty_for_generic_message():
    assert _extract_wanted_content_types("zeig mir was zu mathe") == set()


# ── Resolver: session_state.entities.medientyp persists across turns ──


def test_resolver_picks_up_session_medientyp():
    """User said 'Videos zu Klimawandel' in turn 1; turn 2 message is
    just 'mehr davon' — the filter must remember 'video'."""
    out = _resolve_wanted_content_types(
        "mehr davon",
        session_entities={"thema": "Klimawandel", "medientyp": "Video"},
    )
    assert "video" in out


def test_resolver_picks_up_classification_medientyp():
    """LLM-Classifier put medientyp in classification.entities even
    though the user-message string has no type-keyword."""
    out = _resolve_wanted_content_types(
        "anders bitte",
        classification_entities={"medientyp": "Audio"},
    )
    assert "audio" in out


def test_resolver_combines_all_three_sources():
    """All three sources contribute."""
    out = _resolve_wanted_content_types(
        "auch arbeitsblätter",  # message → arbeitsblatt
        session_entities={"medientyp": "Video"},  # session → video
        classification_entities={"medientyp": "Audio"},  # classification → audio
    )
    assert "arbeitsblatt" in out
    assert "video" in out
    assert "audio" in out


def test_resolver_handles_missing_dicts():
    """None / empty dicts must not raise."""
    out = _resolve_wanted_content_types("nur videos")
    assert "video" in out

    out2 = _resolve_wanted_content_types("nur videos", session_entities=None, classification_entities=None)
    assert "video" in out2

    out3 = _resolve_wanted_content_types("nur videos", session_entities={})
    assert "video" in out3


def test_resolver_no_dup_when_message_and_entities_agree():
    """If both message and session say 'video', no doubles."""
    out = _resolve_wanted_content_types(
        "nur videos",
        session_entities={"medientyp": "Video"},
    )
    # One occurrence (set semantic)
    assert out == {"video"}


def test_resolver_falls_back_to_raw_entity_value():
    """Unknown medientyp values (not in _CONTENT_TYPE_KEYWORDS) are kept
    as raw substring filter — better than dropping the user's intent.
    'Workbook' is an artificial example for a non-canonical value."""
    out = _resolve_wanted_content_types(
        "",
        session_entities={"medientyp": "Workbook"},
    )
    # 'workbook' should appear as raw substring filter
    assert "workbook" in out
