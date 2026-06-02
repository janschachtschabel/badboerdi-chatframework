"""Tests for the lotsen-mode external URL rewriter (Welle C Sprint 6 Hotfix).

User-Report: Im Inline-Widget mit Lotsen-Modus zeigten Einzelinhalte
trotz korrekt annotierter ``card.link`` auf externe Anbieter-URLs
(youtube.com etc.). Ursache: Der LLM baute im Antwort-Text Markdown-
Links auf ``card.url`` (extern) statt auf ``card.link`` (Repo-Render).

Der Postprocess-Rewriter ersetzt diese externen URLs durch die
jeweilige Repo-Pendant — aber nur im Lotsen-Modus.
"""
from app.routers.chat import _rewrite_external_urls_to_repo


CARDS_WITH_EXT_AND_REPO = [
    {
        "node_id": "abc",
        "url": "https://www.youtube.com/watch?v=abc123",
        "link": "https://redaktion.openeduhub.net/edu-sharing/components/render/abc",
        "wlo_url": "https://redaktion.openeduhub.net/edu-sharing/components/render/abc",
    },
    {
        "node_id": "def",
        "url": "https://www.lehrer-online.de/unterricht/sek-i/whatever",
        "link": "https://redaktion.openeduhub.net/edu-sharing/components/render/def",
    },
]


def test_rewrites_youtube_to_repo_in_lotsen_mode():
    text = "Hier ist ein Video: [Mathe-Video](https://www.youtube.com/watch?v=abc123) — schau rein."
    out = _rewrite_external_urls_to_repo(text, CARDS_WITH_EXT_AND_REPO, guide_mode=True)
    assert "youtube.com" not in out
    assert "redaktion.openeduhub.net/edu-sharing/components/render/abc" in out
    assert "Mathe-Video" in out  # Label bleibt


def test_rewrites_multiple_urls_in_lotsen_mode():
    text = (
        "- [Video](https://www.youtube.com/watch?v=abc123)\n"
        "- [Lehrer-Online-Seite](https://www.lehrer-online.de/unterricht/sek-i/whatever)\n"
    )
    out = _rewrite_external_urls_to_repo(text, CARDS_WITH_EXT_AND_REPO, guide_mode=True)
    assert "youtube.com" not in out
    assert "lehrer-online.de" not in out
    assert "redaktion.openeduhub.net" in out
    # Beide Cards-Repo-URLs sollten auftauchen
    assert "render/abc" in out
    assert "render/def" in out


def test_does_NOT_rewrite_when_lotsen_off():
    """Im Normal-Modus springt der User absichtlich raus → externe URL bleibt."""
    text = "Schau dir [das Video](https://www.youtube.com/watch?v=abc123) an."
    out = _rewrite_external_urls_to_repo(text, CARDS_WITH_EXT_AND_REPO, guide_mode=False)
    assert "youtube.com" in out
    assert "redaktion.openeduhub.net" not in out


def test_no_op_on_empty_text():
    assert _rewrite_external_urls_to_repo("", CARDS_WITH_EXT_AND_REPO, guide_mode=True) == ""
    assert _rewrite_external_urls_to_repo(None, CARDS_WITH_EXT_AND_REPO, guide_mode=True) == ""


def test_no_op_when_no_cards():
    text = "Bla [link](https://example.com/x)"
    assert _rewrite_external_urls_to_repo(text, [], guide_mode=True) == text


def test_no_op_when_card_has_no_external_url():
    cards = [{"node_id": "abc", "link": "https://redaktion.openeduhub.net/edu-sharing/components/render/abc"}]
    text = "Eine [Card](https://redaktion.openeduhub.net/edu-sharing/components/render/abc)."
    out = _rewrite_external_urls_to_repo(text, cards, guide_mode=True)
    assert out == text  # nichts zu ersetzen


def test_preserves_unrelated_urls():
    """Externe URLs ohne Card-Match bleiben unangetastet (vermutlich
    Markdown aus RAG-Antwort oder Disclaimer-Link)."""
    text = (
        "Allgemeine Info auf [Wikipedia](https://de.wikipedia.org/wiki/Bruch).\n"
        "Video: [Mathe](https://www.youtube.com/watch?v=abc123)"
    )
    out = _rewrite_external_urls_to_repo(text, CARDS_WITH_EXT_AND_REPO, guide_mode=True)
    assert "de.wikipedia.org" in out  # Wikipedia bleibt
    assert "youtube.com" not in out   # YouTube ersetzt
    assert "render/abc" in out


def test_handles_pydantic_model_like_cards():
    """Cards können auch als Pydantic-Model (mit Attr-Zugriff) kommen."""
    class FakeCard:
        url = "https://www.youtube.com/watch?v=xyz"
        link = "https://redaktion.openeduhub.net/edu-sharing/components/render/xyz"
        wlo_url = link
        guide_url = link
    text = "[Video](https://www.youtube.com/watch?v=xyz)"
    out = _rewrite_external_urls_to_repo(text, [FakeCard()], guide_mode=True)
    assert "youtube.com" not in out
    assert "render/xyz" in out
