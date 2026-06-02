"""Unit tests for the Persona-Marker quality gate in eval_service.

This gate filters LLM-generated scenarios that drifted to generic phrasing
without persona-specific anchors. Without anchors, the classifier can't
distinguish the intended persona from P-AND — turning the eval into noise.

The tests cover:
1. Each persona's positive markers actually trigger a True result
2. Anchor-less text correctly fails for non-P-AND personas
3. P-AND accepts truly anonymous text but rejects text with leaked markers
"""
import pytest

from app.services.eval_service import _has_persona_marker, _PERSONA_MARKERS


# ── Positive cases: each persona has a clear marker in the text ────


@pytest.mark.parametrize("persona_id,text", [
    ("P-W-LK", "Ich plane einen Stundenentwurf zu Bruchrechnung fuer meine Klasse."),
    ("P-W-LK", "Als Lehrkraft suche ich Material fuer Sek I."),
    ("P-W-SL", "Ich kapier Bruchrechnung nicht, gibt's ein Video?"),
    ("P-W-SL", "Fuer meine Klausur brauche ich Uebungen zur Kurvendiskussion."),
    ("P-ELT", "Mein Sohn braucht Hilfe in Mathe."),
    ("P-ELT", "Hausaufgaben meines Kindes in Klasse 7 — wo finde ich Erklaerungen?"),
    ("P-W-RED", "Ich kuratiere eine Sammlung zum Klimawandel."),
    ("P-W-RED", "Als Redakteurin moechte ich Inhalte einstellen."),
    ("P-W-PRESSE", "Als Journalistin recherchiere ich fuer einen Artikel ueber OER."),
    ("P-W-PRESSE", "Brauche das fuer meine Leser zum Bildungssystem."),
    # Welle E (2026-05): Politik in P-VER gemerged.
    ("P-VER", "Fuer meinen Wahlkreis brauche ich Zahlen zur Digitalisierung."),
    ("P-VER", "Als Politikerin moechte ich eine parlamentarische Anfrage stellen."),
    ("P-VER", "Fuer unsere Verwaltung sind die Nutzungs-KPI relevant."),
    ("P-VER", "Als Schulamt brauche ich amtliche Daten."),
    ("P-BER", "Als Beraterin begleite ich eine Schulentwicklung."),
    ("P-BER", "Fuer unsere Schule evaluieren wir die Materialnutzung."),
])
def test_marker_present(persona_id, text):
    """Each persona has clear positive-marker hits."""
    assert _has_persona_marker(text, persona_id), \
        f"Expected '{text!r}' to contain {persona_id} marker"


# ── Negative cases: missing markers → False ────────────────────────


@pytest.mark.parametrize("persona_id,text", [
    ("P-W-LK", "Gibt es Mathe-Material?"),
    ("P-W-LK", "Was bietet ihr fuer Biologie?"),
    ("P-W-SL", "Hi, was kann ich hier machen?"),
    ("P-W-SL", "Mathe-Aufgaben?"),
    ("P-ELT", "Suche Lernvideos."),
    ("P-W-RED", "Hat WLO Material zu Geschichte?"),
    ("P-W-PRESSE", "Wie funktioniert OER?"),
    # P-W-POL test gestrichen (Welle E: in P-VER gemerged, Test in der
    # nächsten Zeile deckt es ab).
    ("P-VER", "Verfuegbarkeit von Material?"),
    ("P-BER", "Gibt es Beratungsmaterial?"),
])
def test_marker_missing(persona_id, text):
    """Anchor-less text must fail for non-P-AND personas."""
    assert not _has_persona_marker(text, persona_id), \
        f"Expected '{text!r}' to lack {persona_id} marker"


# ── P-AND special case ─────────────────────────────────────────────


def test_p_and_accepts_anonymous():
    """P-AND is correct when text genuinely has no persona-anchors."""
    assert _has_persona_marker("Was kann ich hier machen?", "P-AND")
    assert _has_persona_marker("Ich gucke mal interessehalber.", "P-AND")
    assert _has_persona_marker("Mathe-Material?", "P-AND")


def test_p_and_rejects_leaked_markers():
    """P-AND must reject text where another persona's marker leaked in."""
    # LK marker leaks
    assert not _has_persona_marker(
        "Als Lehrkraft brauche ich Materialien", "P-AND")
    # SL marker leaks
    assert not _has_persona_marker(
        "Fuer meine Klausur brauche ich Vektor-Uebungen", "P-AND")
    # ELT marker leaks
    assert not _has_persona_marker(
        "Mein Sohn braucht Mathe-Hilfe", "P-AND")


# ── Marker-dictionary structural invariants ────────────────────────


def test_all_personas_present():
    """Every persona we care about is in the marker dict."""
    # Welle E (2026-05): 8 statt 9 Personas (P-W-POL in P-VER gemerged).
    expected = {
        "P-W-LK", "P-W-SL", "P-ELT", "P-W-RED",
        "P-W-PRESSE", "P-VER", "P-BER", "P-AND",
    }
    assert set(_PERSONA_MARKERS.keys()) == expected


def test_markers_lower_cased():
    """Markers must be lower-cased — comparison is case-insensitive."""
    for persona_id, markers in _PERSONA_MARKERS.items():
        for m in markers:
            assert m == m.lower(), \
                f"Marker {m!r} for {persona_id} is not lower-cased"


def test_p_and_has_no_positive_markers():
    """P-AND is detected by ABSENCE of other markers, not by its own."""
    assert _PERSONA_MARKERS["P-AND"] == []
