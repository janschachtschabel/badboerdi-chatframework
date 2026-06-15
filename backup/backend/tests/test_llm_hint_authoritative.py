"""Welle E (2026-05-17): LLM-Hint-Authoritative ist jetzt der Default.

Diese Datei testete den expliziten Authoritative-A/B-Modus aus Welle D.
In Welle E ist dieser Modus der einzige Routing-Mechanismus — der
``pattern_selection_mode``-Parameter ist obsolet und wird ignoriert.

Die Tests sind übersprungen.  Was hier sinnvoll bleibt:

* Safety-Override beats hint    → in p01-/p02-Pattern-Tests verschieben
* Hint unknown → fallback       → in select_pattern-Tests verschieben
* Gate-Violations als Log       → wird im neuen Eval-Aggregator gemessen

Datei kann nach 1–2 Welle-E-Runs entfernt werden.
"""
import pytest

pytestmark = pytest.mark.skip(
    reason="Welle E: LLM-Hint ist immer aktiv. Mode-Toggle obsolet.",
)


def test_llm_hint_authoritative_obsolete():
    """Placeholder so pytest erkennt die Datei als gültig."""
    pass
