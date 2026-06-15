"""Tests for the guide-marker stripper (Welle C Sprint 6 Hotfix).

User bug-report: At "nur videos zeigen" the bot response contained the
raw text ``guide|Zur Themenseite Nachhaltigkeit|https://...``. This is
the ``__guide__|...`` quick-reply marker leaking into the answer body
after Markdown bold-markup eats the leading ``__``.

The stripper sanitises the response text so the marker never reaches
the frontend chat bubble — it's still emitted as a proper quick-reply
button if the lotsen-mode is on.
"""
from app.routers.chat import _strip_guide_markers_from_text


def test_strips_full_marker_with_underscores():
    text = "Hier sind Treffer. __guide__|Themenseite|https://wirlernenonline.de/themen/x__ Hilfreich."
    out = _strip_guide_markers_from_text(text)
    assert "guide|" not in out
    assert "https://" not in out
    assert "Hier sind Treffer" in out
    assert "Hilfreich" in out


def test_strips_markdown_eaten_marker():
    """Markdown bold-pre-processing ate the leading ``__``. Result:
    bare ``guide|Label|URL`` text."""
    text = (
        "Klar, ich hab dir die Videos rausgezogen.\n\n"
        "guide|Zur Themenseite Nachhaltigkeit|https://redaktion.openeduhub.net/edu-sharing/components/topic-pages?collectionId=d0ed50e6"
    )
    out = _strip_guide_markers_from_text(text)
    assert "guide|" not in out.lower() or "guides" in out.lower()  # only false-positive matches
    assert "https://" not in out
    assert "Klar, ich hab dir die Videos rausgezogen" in out


def test_idempotent_on_clean_text():
    text = "Normale Bot-Antwort ohne Marker."
    assert _strip_guide_markers_from_text(text) == text


def test_handles_empty_input():
    assert _strip_guide_markers_from_text("") == ""
    assert _strip_guide_markers_from_text(None) == ""


def test_strips_multiple_markers():
    text = (
        "Hier zwei Wege:\n"
        "guide|Themenseite|https://x.de/a\n"
        "guide|Sammlung|https://x.de/b\n"
        "Schau dir das an."
    )
    out = _strip_guide_markers_from_text(text)
    assert "guide|" not in out.lower() or out.lower().count("guide") == 0
    assert "https://" not in out
    assert "Schau dir das an" in out


def test_case_insensitive_match():
    text = "Test: GUIDE|Label|https://x.de"
    out = _strip_guide_markers_from_text(text)
    assert "https://" not in out
    assert "Test:" in out


def test_word_guide_in_normal_sentence_preserved():
    """The word 'guide' in a normal sentence (no pipe) is NOT stripped."""
    text = "Dies ist ein guter Guide zum Lernen."
    out = _strip_guide_markers_from_text(text)
    assert "Guide zum Lernen" in out
