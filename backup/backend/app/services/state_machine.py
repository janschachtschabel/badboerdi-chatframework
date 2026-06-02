"""Conversation State Machine validator (Welle C Sprint 6).

Validiert Übergänge zwischen Conversation-States (state-1 ... state-12)
gegen die `next_likely`-Listen aus `04-states/states.yaml`.

Designprinzip:
- States sind **Verlaufs-Phasen**, nicht eine zweite Klassifikations-Achse
  zum Intent. Welche Phase als nächstes kommt, hängt vom aktuellen
  Verlauf ab — z.B. nach state-5 (Suche) folgt typischerweise state-6
  (Ergebnis-Kuratierung), nicht state-3 (Information).
- Der Validator arbeitet primär als **Telemetrie**: er erkennt
  implausible Übergänge und markiert sie, ändert sie aber nicht
  automatisch. Korrekturen passieren über die Routing-Rules-Engine
  (z.B. `rule_state12_guard` korrigiert state-12 → state-5 bei
  Non-Canvas-Intent).

Schnittstelle:
    >>> result = validate_transition(prev="state-5", next_="state-6", intent="INT-W-03")
    >>> result["plausible"]
    True
    >>> result["validated_state"]
    'state-6'

    >>> result = validate_transition(prev="state-12", next_="state-3", intent="INT-W-06")
    >>> result["plausible"]
    False
    >>> result["reason"]
    'state-3 nicht in next_likely von state-12 [state-12, state-9, state-5]'

Aufgerufen aus `chat.py` direkt nach `classification.next_state`-Auslesen,
vor `select_pattern()`.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.config_loader import get_state_directive

logger = logging.getLogger(__name__)


def validate_transition(
    prev: str,
    next_: str,
    intent: str | None = None,
    *,
    auto_correct: bool = False,
) -> dict[str, Any]:
    """Validate a conversation state transition against next_likely.

    Args:
        prev: Vorheriger State (aus session_state["state_id"], leer beim ersten Turn).
        next_: Vom Classifier vorgeschlagener nächster State (classification.next_state).
        intent: Aktuelles Intent (für Fallback-Override-Hint).
        auto_correct: Wenn True, korrigiere implausible Übergänge auf den
            ersten Eintrag in prev.next_likely. Default False = nur
            Telemetrie ohne Verhaltens-Änderung. Welle C Sprint 6 hält
            Korrekturen bewusst zurück, weil die Routing-Rules-Engine
            (rule_state12_guard etc.) den harten Pfad schon abdeckt.

    Returns:
        dict mit:
            validated_state: str — der State, der zurückgegeben wird
                             (= next_ wenn plausibel, sonst je nach
                             auto_correct entweder next_ oder Korrektur)
            plausible: bool — war der Übergang erwartet?
            reason: str — Erklärung wenn nicht plausibel (sonst leer)
            prev_next_likely: list[str] — die next_likely-Liste des
                              prev-States für Diagnose
    """
    # Erster Turn (kein prev): immer plausibel — alles ist ein gültiger Start.
    if not prev:
        return {
            "validated_state": next_,
            "plausible": True,
            "reason": "",
            "prev_next_likely": [],
        }

    # Self-Loop (z.B. state-2 → state-2 weil noch ein Slot fehlt): erlaubt.
    if prev == next_:
        return {
            "validated_state": next_,
            "plausible": True,
            "reason": "",
            "prev_next_likely": [],
        }

    prev_meta = get_state_directive(prev)
    next_likely = prev_meta.get("next_likely", []) if prev_meta else []

    if not next_likely:
        # Kein next_likely-Hint hinterlegt → wir können nichts bewerten.
        # Telemetrie: plausible=None wäre ehrlicher, aber wir signalisieren
        # plausible=True um den Default-Pfad nicht zu blockieren.
        return {
            "validated_state": next_,
            "plausible": True,
            "reason": "",
            "prev_next_likely": [],
        }

    if next_ in next_likely:
        return {
            "validated_state": next_,
            "plausible": True,
            "reason": "",
            "prev_next_likely": next_likely,
        }

    # Implausibler Übergang. Sonderfall: Canvas-Intent (INT-W-11/12)
    # springt nach state-12, das ist immer legitim — falls intent passt,
    # Übergang trotzdem als plausibel werten.
    if next_ == "state-12" and intent in {"INT-W-11", "INT-W-12"}:
        return {
            "validated_state": next_,
            "plausible": True,
            "reason": "canvas-intent override (intent in {INT-W-11, INT-W-12})",
            "prev_next_likely": next_likely,
        }

    reason = (
        f"{next_} nicht in next_likely von {prev} "
        f"[{', '.join(next_likely)}]"
    )

    if auto_correct:
        # Fallback: erster Eintrag in next_likely. Wenn der Classifier
        # weit daneben liegt, ist der "natürlichste" Nachfolger oft
        # näher dran als die ungewöhnliche Wahl.
        corrected = next_likely[0]
        logger.info(
            "state-machine auto-correct: %s -> %s (classifier wollte %s)",
            prev, corrected, next_,
        )
        return {
            "validated_state": corrected,
            "plausible": False,
            "reason": reason + f" → korrigiert zu {corrected}",
            "prev_next_likely": next_likely,
        }

    logger.debug("state-machine warn: %s", reason)
    return {
        "validated_state": next_,  # unverändert übernehmen
        "plausible": False,
        "reason": reason,
        "prev_next_likely": next_likely,
    }
