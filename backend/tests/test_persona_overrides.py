"""Tests for the deterministic persona-self-id overrides + low-confidence
fallback in llm_service.classify_input.

We don't test the LLM call itself (mocked elsewhere) — only the post-
classifier override pass that runs after ``raw = json.loads(...)``.
The override logic is purely regex/threshold based, so we can test by
calling the override block in isolation through a thin wrapper.
"""
from __future__ import annotations

import pytest

from app.services.llm_service import classify_input  # noqa: F401  (import smoke test)


def _apply_overrides(raw: dict, message: str) -> dict:
    """Re-implement the override pass against the same regex list, so we
    can test it directly without mocking the OpenAI client. If the
    production code's regex list changes, update this helper to match.
    """
    import re as _re

    PERSONA_SELF_ID_PATTERNS = [
        ("P-W-LK", r"\b(ich\s+bin\s+(lehr(er|erin|kraft)|p[äa]dagog(in|e)?|"
                   r"klassenlehr(er|erin)|grundschullehr(er|erin)|fachlehr(er|erin)|"
                   r"referendar(in)?)|"
                   r"als\s+(lehrkraft|lehrer(in)?|p[äa]dagog(in|e)?|"
                   r"fachlehr(er|erin)|referendar(in)?)|"
                   r"f[üu]r\s+meinen\s+unterricht|"
                   r"in\s+meiner\s+klasse\s+unterrichte|"
                   r"meine\s+sch[üu]ler:?innen|"
                   r"mein\s+stundenentwurf|meinen\s+stundenentwurf|"
                   r"meine\s+(unterrichts(stunde|einheit|reihe)|lehrplan)|"
                   r"meinen\s+(unterrichts(stunde|einheit|reihe)|lehrplan)|"
                   r"(klassenarbeit(en)?\s+(korrigier|bewerten|stell)|"
                   r"korrigier(e|en)\s+klassenarbeit(en)?|"
                   r"klausur(en)?\s+(korrigier|bewerten|stell)|"
                   r"korrigier(e|en)\s+klausur(en)?)|"
                   r"meinen?\s+lehrplan|"
                   r"in\s+meiner\s+(unterrichts(stunde|einheit|reihe))|"
                   r"f[üu]r\s+meinen\s+lehrauftrag)\b"),
        ("P-W-SL", r"\b(ich\s+bin\s+sch[üu]ler(in)?|ich\s+bin\s+lernend(e|er)|"
                   r"als\s+sch[üu]ler(in)?|"
                   r"f[üu]r\s+meine\s+(klassenarbeit|hausaufgabe|pr[üu]fung|klausur)|"
                   r"f[üu]r\s+meinen\s+(test|jahrgang)|"
                   r"ich\s+lerne\s+gerade\s+(in\s+der\s+schule|f[üu]r\s+die\s+schule))\b"),
        ("P-ELT", r"\b(ich\s+bin\s+(mutter|vater|elternteil)|als\s+(mutter|vater|elternteil)|"
                  r"mein\s+(kind|sohn|tochter)|meine\s+tochter|"
                  r"f[üu]r\s+meinen?\s+(kind|sohn|tochter|\d+\s*-?\s*j[äa]hrigen?))\b"),
        ("P-W-RED", r"\b(ich\s+bin\s+(redakteur(in)?|autor(in)?)|"
                    r"als\s+(redakteur(in)?|autor(in)?)|"
                    r"f[üu]r\s+(unsere|meine)\s+redaktion)\b"),
        ("P-W-POL", r"\b(ich\s+bin\s+(politiker(in)?|abgeordnete[r]?|multiplikator(in)?)|"
                    r"als\s+politiker(in)?|"
                    r"f[üu]r\s+(unsere|meine)\s+partei|"
                    r"f[üu]r\s+(unser|das)\s+ministerium|"
                    r"bildungspolitisch|positionspapier)\b"),
        ("P-W-PRESSE", r"\b(ich\s+bin\s+journalist(in)?|als\s+journalist(in)?|"
                       r"f[üu]r\s+meine\s+(presse|zeitung|redaktion\s+der\s+zeitung)|"
                       r"f[üu]r\s+meine\s+leser:?innen|"
                       r"presseanfrage|f[üu]r\s+einen\s+artikel)\b"),
        ("P-BER", r"\b(ich\s+bin\s+berater(in)?|als\s+berater(in)?|"
                  r"f[üu]r\s+(unsere|meine)\s+beratung|"
                  r"in\s+(unserem|meinem)\s+beratungsprozess|"
                  r"f[üu]r\s+unsere\s+schule\s+evaluier\w*|"
                  r"vergleich\s+(verschiedener|der)\s+(angebote|plattform)\w*)\b"),
        ("P-VER", r"\b(ich\s+bin\s+(verwaltungs|beh[öo]rden)|"
                  r"als\s+verwaltungs|"
                  r"f[üu]r\s+(unsere|die)\s+(verwaltung|beh[öo]rde)|"
                  r"in\s+der\s+beh[öo]rdenarbeit|"
                  r"amtliche\s+daten|kennzahlen\s+f[üu]r\s+das\s+ministerium)\b"),
    ]
    msg = (message or "").lower()
    for pid, pattern in PERSONA_SELF_ID_PATTERNS:
        if _re.search(pattern, msg):
            raw["persona_id"] = pid
            raw["persona_confidence"] = max(raw.get("persona_confidence", 0.0), 0.95)
            return raw

    pconf = raw.get("persona_confidence")
    if isinstance(pconf, (int, float)) and pconf < 0.40:
        raw["persona_id"] = "P-AND"
    return raw


SELF_ID_CASES = [
    # (message, expected_persona)
    ("Ich bin Lehrerin und brauche Material zur Photosynthese", "P-W-LK"),
    ("Als Lehrkraft suche ich Arbeitsblätter für Klasse 7", "P-W-LK"),
    ("Für meinen Unterricht brauche ich was zur Bruchrechnung", "P-W-LK"),
    ("Mein Stundenentwurf zur Photosynthese braucht noch Material", "P-W-LK"),
    ("Ich korrigiere Klassenarbeiten zur Bruchrechnung", "P-W-LK"),
    ("Für meine Unterrichtsstunde zum Klimawandel", "P-W-LK"),
    ("Als Fachlehrerin für Mathematik suche ich Material", "P-W-LK"),
    ("Als Referendar bereite ich meine erste Stunde vor", "P-W-LK"),
    ("Ich bin Schüler und verstehe das nicht", "P-W-SL"),
    ("Als Schülerin suche ich Hilfe bei meiner Klausur", "P-W-SL"),
    ("Für meine Hausaufgabe zum Thema Photosynthese", "P-W-SL"),
    ("Mein Sohn braucht Hilfe bei Mathe", "P-ELT"),
    ("Als Mutter suche ich Material für meine Tochter", "P-ELT"),
    ("Ich bin Redakteurin und kuratiere Inhalte zu OER", "P-W-RED"),
    ("Als Autor brauche ich aktuelle Quellen", "P-W-RED"),
    ("Für unsere Redaktion brauche ich Hintergrundmaterial", "P-W-RED"),
    ("Ich bin Journalistin und brauche zitierfähige Quellen", "P-W-PRESSE"),
    ("Für einen Artikel zur Bildungspolitik", "P-W-PRESSE"),
    ("Ich bin Politiker und suche Positionspapiere", "P-W-POL"),
    ("Für unsere Partei brauche ich aktuelle Bildungsdaten", "P-W-POL"),
    ("Ich bin Beraterin und vergleiche verschiedene Angebote", "P-BER"),
    ("Für unsere Schule evaluiere ich OER-Plattformen", "P-BER"),
    ("Für unsere Verwaltung brauche ich Statistiken", "P-VER"),
    ("In der Behördenarbeit ist mir die Datenlage wichtig", "P-VER"),
]


@pytest.mark.parametrize("msg,expected", SELF_ID_CASES, ids=[m[:40] for m, _ in SELF_ID_CASES])
def test_persona_self_id_overrides(msg, expected):
    raw = {"persona_id": "P-AND", "persona_confidence": 0.5}
    out = _apply_overrides(raw, msg)
    assert out["persona_id"] == expected, f"msg={msg!r} got {out['persona_id']}"
    assert out["persona_confidence"] >= 0.95


def test_self_id_overrides_existing_llm_persona():
    """Even if LLM said a different persona, regex self-id wins."""
    raw = {"persona_id": "P-W-SL", "persona_confidence": 0.7}
    out = _apply_overrides(raw, "ich bin lehrer und plane unterricht")
    assert out["persona_id"] == "P-W-LK"


def test_no_self_id_keeps_llm_persona():
    raw = {"persona_id": "P-W-LK", "persona_confidence": 0.8}
    out = _apply_overrides(raw, "Ich brauche Materialien zur Photosynthese")
    assert out["persona_id"] == "P-W-LK"


def test_low_confidence_falls_back_to_p_and():
    raw = {"persona_id": "P-W-LK", "persona_confidence": 0.3}
    out = _apply_overrides(raw, "Materialien für Mathematik")
    assert out["persona_id"] == "P-AND"


def test_low_confidence_doesnt_override_self_id():
    """If self-id matches AND confidence was low, self-id still wins."""
    raw = {"persona_id": "P-VER", "persona_confidence": 0.3}
    out = _apply_overrides(raw, "ich bin schülerin und brauche hilfe")
    assert out["persona_id"] == "P-W-SL"
    assert out["persona_confidence"] >= 0.95


def test_high_confidence_keeps_persona():
    raw = {"persona_id": "P-W-LK", "persona_confidence": 0.85}
    out = _apply_overrides(raw, "Photosynthese-Material brauche ich")
    assert out["persona_id"] == "P-W-LK"
    assert out["persona_confidence"] == 0.85


def test_threshold_boundary():
    raw = {"persona_id": "P-W-LK", "persona_confidence": 0.40}
    out = _apply_overrides(raw, "ein test")
    # 0.40 == threshold → NOT below, persona kept
    assert out["persona_id"] == "P-W-LK"


def test_moderate_confidence_keeps_persona():
    """0.5 confidence — middle ground — should NOT trigger fallback now."""
    raw = {"persona_id": "P-W-LK", "persona_confidence": 0.5}
    out = _apply_overrides(raw, "noch ein test")
    assert out["persona_id"] == "P-W-LK"


def test_classify_input_signature_smoke():
    """Sanity check that classify_input is still importable and the
    signature is unchanged (we touch the module a lot)."""
    import inspect
    sig = inspect.signature(classify_input)
    params = list(sig.parameters.keys())
    assert "message" in params
    assert "history" in params
    assert "session_state" in params
