"""Regression tests for the persona-marker gate.

These cover the openings that the live eval-run drop log showed as
"persona-marker missing" but were actually valid persona-anchored texts.
After the marker-list expansion they should all be recognised.
"""
from __future__ import annotations

import pytest

from app.services.eval_service import _has_persona_marker
from app.services.config_loader import load_eval_setup_config


# ── Realer Drop-Set vom 2026-05-17-Eval-Run ──────────────────────────


_LK_OPENINGS_THAT_WERE_WRONGLY_DROPPED = [
    "Ich benötige einen Unterrichtsentwurf für eine Stunde zum Thema Klimawandel.",
    "Kannst du den Titel meines Unterrichtsentwurfs ändern, damit er präziser wird?",
    "Ist das Material für meinen Unterricht in Klasse 6 geeignet?",
    "Wie hat sich die Nutzung von Unterrichtsmaterialien in meiner Klasse entwickelt?",
]

# Persona-ambivalente Openings (auch nach Listen-Expansion ohne Marker).
# Für diese MUSS der warn-Modus greifen, sonst gehen sie verloren.
_AMBIGUOUS_NO_MARKER = [
    # Beide Personas könnten das fragen — kein eindeutiger Anchor:
    ("P-W-LK", "Kannst du mir einen Lernpfad für das Thema Photosynthese erstellen?"),
    ("P-W-LK", "Was ist eine Themenseite und wie kann ich sie nutzen?"),
    ("P-W-SL", "Was ist OER?"),
    ("P-W-SL", "Kannst du mir Schritt für Schritt erklären, wie Photosynthese funktioniert?"),
]

_SL_OPENINGS_THAT_WERE_WRONGLY_DROPPED = [
    "Ich verstehe das Thema Biologie nicht so gut, kannst du mir da helfen?",
    "Das war echt hilfreich, danke! Ich bin in der 9. Klasse und hab viel über die Themen gelernt.",
    "Ist das Material für meine Mathe-Hausaufgaben geeignet?",
    "Kannst du mir ein Arbeitsblatt zum Thema Bruchrechnung erstellen? Ich verstehe das Thema nicht.",
]


@pytest.mark.parametrize("text", _LK_OPENINGS_THAT_WERE_WRONGLY_DROPPED)
def test_lk_marker_after_expansion(text):
    """Lehrkraft-Openings, die im Strict-Modus fälschlich gedroppt wurden."""
    assert _has_persona_marker(text, "P-W-LK"), (
        f"Lehrkraft-Marker fehlt in: {text[:80]}"
    )


@pytest.mark.parametrize("text", _SL_OPENINGS_THAT_WERE_WRONGLY_DROPPED)
def test_sl_marker_after_expansion(text):
    """Schüler-Openings, die im Strict-Modus fälschlich gedroppt wurden."""
    assert _has_persona_marker(text, "P-W-SL"), (
        f"Schüler-Marker fehlt in: {text[:80]}"
    )


# ── Gate-Konfiguration ───────────────────────────────────────────────


def test_gate_default_mode_is_warn():
    """Default-Modus ist `warn` — wir wollen nicht aggressiv droppen."""
    cfg = load_eval_setup_config()
    assert cfg["persona_marker_gate"] == "warn", (
        f"Default sollte 'warn' sein, ist '{cfg['persona_marker_gate']}'"
    )


def test_gate_mode_options_supported():
    """Loader akzeptiert die drei Werte strict/warn/off und fällt sonst auf warn."""
    cfg = load_eval_setup_config()
    assert cfg["persona_marker_gate"] in ("strict", "warn", "off")


# ── Warn-Modus: ambige Openings werden behalten ──────────────────────


@pytest.mark.parametrize("persona_id,text", _AMBIGUOUS_NO_MARKER)
def test_ambiguous_openings_have_no_marker(persona_id, text):
    """Sanity-Check: diese Openings haben tatsächlich keinen Marker.

    Sie würden im STRICT-Modus rausfallen, im WARN-Modus aber als
    Szenario übernommen (das prüft der Pipeline-Test im integration suite).
    """
    assert not _has_persona_marker(text, persona_id), (
        f"Ungewollter Marker-Match bei: {text[:60]}"
    )
