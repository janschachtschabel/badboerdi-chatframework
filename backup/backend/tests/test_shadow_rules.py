"""Welle E (2026-05-17): Tie-Breaker + Persona-Loosening entfernt.

Diese Test-Datei testete Welle-D-Shadow-Mechaniken, die mit der Welle-E-
Vereinfachung der Pattern-Engine obsolet geworden sind:

* Tie-Breaker:        Pattern-Wahl läuft jetzt über LLM-Hint direkt.
                      Kein Score-Gleichstand mehr, kein Override-Bedarf.
* Persona-Loosening:  Persona ist vom Routing entkoppelt, Trait-Signals
                      wirken nicht mehr im Score (Score gibt es nicht mehr).

Die ganze Datei wird übersprungen.  Sie bleibt im Repo nur als
historischer Anker — wer sie reaktivieren will, müsste erst die alte
3-Phasen-Engine wiederherstellen.
"""
import pytest

pytestmark = pytest.mark.skip(
    reason="Welle E: Tie-Breaker und Persona-Loosening sind entfernt — "
           "Pattern-Wahl läuft jetzt direkt über LLM-Hint.",
)


def test_shadow_rules_obsolete():
    """Placeholder so pytest erkennt die Datei als gültig."""
    pass
