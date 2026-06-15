"""Quick test for the LLM-based vocabulary fallback in mcp_client.

Calls _resolve_filter_uris with values that ARE handled by the heuristic
(canonical labels, substrings) and values that REQUIRE the LLM
(language-shifted, paraphrased). Logs which path resolved each.

Run:
  cd backend && python scripts/test_llm_vocab_match.py
"""
from __future__ import annotations

import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)


CASES = [
    # (vocab key on MCP input, raw value, expected behavior)
    ("discipline",         "Mathematik",        "exact"),
    ("discipline",         "Mathe",             "fuzzy alias"),
    ("discipline",         "biology",           "fuzzy alias (eng)"),
    ("discipline",         "sciences",          "LLM expected (no alias)"),
    ("discipline",         "Naturwiss",         "fuzzy substring -> naturwissenschaften"),
    ("learningResourceType", "Worksheet",       "fuzzy alias 'worksheet' -> arbeitsblatt"),
    ("learningResourceType", "Quiz",            "exact"),
    ("learningResourceType", "Lückentext",      "LLM expected (probably maps to Übung/Arbeitsblatt)"),
    ("educationalContext", "Sek I",             "fuzzy alias"),
    ("educationalContext", "high school",       "LLM expected (English; ambiguous -> maybe Sek II)"),
    ("userRole",           "students",          "fuzzy alias"),
    ("userRole",           "Pädagoginnen",      "LLM expected -> teacher"),
]


async def main() -> None:
    from app.services.mcp_client import _resolve_filter_uris, _ensure_label_cache

    # Pre-warm caches so the heuristic has all aliases loaded
    for v in ("discipline", "lrt", "educationalContext", "userRole"):
        await _ensure_label_cache(v)

    print(f"\n{'='*80}\nLLM-Vocab-Mapping Test\n{'='*80}")
    for key, value, note in CASES:
        out = await _resolve_filter_uris({key: value})
        resolved = out.get(key)
        print(f"  [{note:38s}] {key}={value!r:25s} -> {resolved}")


if __name__ == "__main__":
    asyncio.run(main())
