"""Unit-Test für strip_reasoning_markers() (Thinking-Filter).

Prüft den echten Filter aus llm_service gegen:
  * das reale deepseek-r1-distill-<think>…</think>-Beispiel,
  * einen ungeschlossenen <think>-Rest (Token-Limit),
  * No-op auf sauberem mistral-Markdown,
  * legitimes "<" (z.B. "x < 5") darf NICHT zerstört werden,
  * <thinking>/<reasoning>-Blöcke, ◁think▷-Unicode, harmony-Marker.

Aufruf (aus backend/):  python scripts/test_strip_reasoning.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.llm_service import (  # noqa: E402
    strip_reasoning_markers,
    _make_think_safe_on_token,
)

CASES = [
    # (label, input, expected)
    (
        "deepseek <think>…</think> + Antwort",
        "<think>\nZuerst berechne ich den Preis für einen einzelnen Stift, indem "
        "ich 2,40 € durch 3 teile = 0,80 €. Dann mal 7.\n</think>\n\n"
        "**Rechenweg:** 2,40 € ÷ 3 = 0,80 €; × 7 = **5,60 €**",
        "**Rechenweg:** 2,40 € ÷ 3 = 0,80 €; × 7 = **5,60 €**",
    ),
    (
        "ungeschlossener <think> (Token-Limit) → alles ab Tag weg",
        "<think>\nIch denke noch nach und wurde abgeschnitten...",
        "",
    ),
    (
        "Lead-Text + ungeschlossener <think>",
        "Kurz vorab:\n<think>geheimes Denken das abbricht",
        "Kurz vorab:",
    ),
    (
        "sauberes mistral-Markdown → unverändert",
        "**Rechenweg:**\n1. Preis pro Stift: 2,40 € ÷ 3 = **0,80 €**\n2. × 7 = **5,60 €**",
        "**Rechenweg:**\n1. Preis pro Stift: 2,40 € ÷ 3 = **0,80 €**\n2. × 7 = **5,60 €**",
    ),
    (
        "legitimes '<' (Mathe) darf bleiben",
        "Wenn x < 5 ist, dann gilt die Ungleichung.",
        "Wenn x < 5 ist, dann gilt die Ungleichung.",
    ),
    (
        "<thinking>…</thinking>-Block",
        "<thinking>internes Zeug</thinking>Die Antwort ist 42.",
        "Die Antwort ist 42.",
    ),
    (
        "<reasoning>…</reasoning>-Block (mit Attribut)",
        '<reasoning type="cot">Schritt 1...</reasoning>Ergebnis: fertig.',
        "Ergebnis: fertig.",
    ),
    (
        "Unicode ◁think▷…◁/think▷",
        "◁think▷ verstecktes Denken ◁/think▷Sichtbare Antwort.",
        "Sichtbare Antwort.",
    ),
    (
        "harmony-Marker werden entfernt",
        "Antwort Teil 1.<|channel|>final<|message|> Teil 2.",
        "Antwort Teil 1.final Teil 2.",
    ),
    (
        "leerer String",
        "",
        "",
    ),
    (
        "case-insensitive </THINK>",
        "<think>geheim</THINK>Klartext",
        "Klartext",
    ),
]


# ── Streaming-Fälle: char-/chunk-weise Zufuhr, Tags über Chunk-Grenzen ──
# Verifiziert _ThinkSafeStreamer: Live-Stream darf KEIN <think>/Teil-Tag und
# keinen Denk-Inhalt durchlassen; nach flush() == Batch-Filter.
STREAM_CASES = [
    ("stream: sauberer Text",
     "Hallo Welt, das ist die finale Antwort.",
     "Hallo Welt, das ist die finale Antwort."),
    ("stream: <think>…</think> + Antwort",
     "<think>geheimes Denken Schritt 1 Schritt 2</think>Antwort: 42.",
     "Antwort: 42."),
    ("stream: Lead + think + Antwort",
     "Lead-Satz.\n<think>verborgen</think>\nEnde-Satz.",
     "Lead-Satz.\n\nEnde-Satz."),
    ("stream: ungeschlossener <think>",
     "<think>denke ohne Ende und werde abgeschnitten...",
     ""),
    ("stream: harmony-Marker",
     "Teil1<|channel|>final<|message|>Teil2",
     "Teil1finalTeil2"),
]
# Substrings, die im Live-Stream NIEMALS auftauchen dürfen (Denk-Leak).
FORBIDDEN_IN_STREAM = ["<think", "geheim", "verborgen", "denke ohne", "<|channel|>", "<|message|>"]


def _run_stream(full: str, chunk_size: int) -> str:
    out: list[str] = []
    streamer = _make_think_safe_on_token(lambda t: out.append(t))
    for i in range(0, len(full), chunk_size):
        streamer(full[i:i + chunk_size])
    streamer.flush()
    return "".join(out)


def main() -> int:
    passed = 0
    failed = 0

    print("── Batch-Filter ──")
    for label, inp, expected in CASES:
        got = strip_reasoning_markers(inp)
        if got == expected:
            passed += 1
            print(f"  [PASS] {label}")
        else:
            failed += 1
            print(f"  [FAIL] {label}")
            print(f"         erwartet : {expected!r}")
            print(f"         erhalten : {got!r}")

    print("\n── Live-Streaming-Filter (chunk=1 / 3 / ganz) ──")
    for label, full, expected in STREAM_CASES:
        for cs in (1, 3, len(full) or 1):
            got = _run_stream(full, cs)
            leaked = [s for s in FORBIDDEN_IN_STREAM if s in got]
            if got == expected and not leaked:
                passed += 1
                print(f"  [PASS] {label}  (chunk={cs})")
            else:
                failed += 1
                print(f"  [FAIL] {label}  (chunk={cs})")
                print(f"         erwartet : {expected!r}")
                print(f"         erhalten : {got!r}")
                if leaked:
                    print(f"         LEAK     : {leaked}")

    print(f"\n  {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
