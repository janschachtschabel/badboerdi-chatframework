"""Cross-Encoder Card-Auswahl + Relevanz-Gate (2026-06-01).

Ersetzt das bisherige LLM-``select_top_cards``: deterministische, schnelle
Auswahl der **tatsächlich angezeigten** Karten je Box-Typ über den vorhandenen
ONNX-Cross-Encoder (``rag_service``). Damit
  * sieht das Antwort-LLM GENAU die angezeigten Karten (kein größerer Pool),
  * werden off-topic Treffer (v.a. bei wenigen Themenseiten) per absoluter
    Relevanz-Schwelle weggelassen statt „best-of-schlecht" durchgereicht.

Empirisch kalibriert (siehe ``scripts/test_reranker_3types.py``): der
Cross-Encoder gibt rohe Logits; relevante Sammlungen/Themenseiten liegen klar
> 0, off-topic deutlich < 0 (z.B. Themenseite „Nachhaltigkeit (LTP)" bei
Query „Klimawandel" = −4,02). Einzelinhalte sind verrauschter → milderes Gate.

Schwellen (Logit), per ENV überschreibbar:
  * Sammlungen + Themenseiten : ``CARD_CE_GATE_COLLECTION``  (Default 0.0)
  * Einzelinhalte             : ``CARD_CE_GATE_CONTENT``     (Default −1.5)
Top-N je Box: ``CARD_CE_TOP_N`` (Default 3).

Arbeitet auf dem MCP-Envelope (``{total,count,results}``) — re-serialisiert die
``results`` auf die gerankte, gegatete Top-N-Auswahl; ``total`` (für die
Such-CTA) bleibt unangetastet.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


# Tool-Name → Gate-Schwelle. Sammlungen/Themenseiten streng (saubere CE-Trennung),
# Einzelinhalte mild (kurze Titel → verrauschter).
def threshold_for_tool(tool_name: str) -> float:
    name = (tool_name or "").strip()
    if name in ("search_wlo_collections", "search_wlo_topic_pages"):
        return _env_float("CARD_CE_GATE_COLLECTION", 0.0)
    # search_wlo_content, get_collection_contents, get_node_details, …
    return _env_float("CARD_CE_GATE_CONTENT", -1.5)


def _doc_text(item: dict[str, Any]) -> str:
    """Repräsentativer Text eines MCP-Result-Items für das (query, doc)-Paar."""
    if not isinstance(item, dict):
        return ""
    t = str(item.get("title") or "").strip()
    d = str(item.get("description") or "").strip()
    kw = item.get("keywords") or item.get("general_keyword") or []
    if isinstance(kw, (list, tuple)):
        kw = " ".join(str(k) for k in kw)
    return f"{t}. {d} {kw}".strip()[:450]


def rerank_gate_envelope(
    query: str,
    result_text: str,
    *,
    tool_name: str,
    top_n: int | None = None,
    allow_soft_fallback: bool = True,
) -> tuple[str, dict[str, Any] | None]:
    """CE-rank + gate + Top-N auf einem MCP-Envelope-``result_text``.

    Returns ``(new_result_text, debug)``. Bei fehlendem Reranker / nicht
    parsebarem Envelope / leerer Query → deterministischer Fallback
    (Top-N nach MCP-Reihenfolge) bzw. unverändert.
    """
    if not result_text:
        return result_text, None
    eff_top = top_n if (top_n and top_n > 0) else _env_int("CARD_CE_TOP_N", 3)

    # Envelope parsen (tolerant: trailing _queryMeta etc.).
    env: Any = None
    try:
        env = json.loads(result_text)
    except (ValueError, TypeError):
        try:
            from app.services.mcp_client import _first_json_object
            frag = _first_json_object(result_text)
            env = json.loads(frag) if frag else None
        except (ValueError, TypeError, ImportError):
            env = None
    if not isinstance(env, dict) or not isinstance(env.get("results"), list):
        return result_text, None
    results: list[dict] = [r for r in env["results"] if isinstance(r, dict)]
    if not results:
        return result_text, None

    threshold = threshold_for_tool(tool_name)

    # Vorschlags-/Fallback-Sets (Themenseiten 'global-fallback' bzw.
    # 'query-fallback' aus _topic_pages_with_warmup) NICHT hart auf 0 gaten —
    # ABER nur bei einer echten Browse-Anfrage ("zeige mir alle themenseiten",
    # allow_soft_fallback=True). Dann gibt es kein Thema, zu dem etwas relevant
    # sein müsste, also nur ranken + Top-N statt leeren.
    # Bei einer THEMEN-Anfrage ("Photosynthese", allow_soft_fallback=False)
    # bleibt das harte Gate aktiv: generische Staging-Themenseiten
    # ("Galeriemethode", Score ~ -2.4) sind off-topic und gehoeren NICHT in
    # die Trefferliste. (Regression 2026-06-02 / Folge-Fix.)
    soft_gate = allow_soft_fallback and bool(
        env.get("_global_fallback") or env.get("_query_fallback")
    )

    # Reranker holen (geht im Fallback ohne).
    rr = None
    try:
        from app.services.rag_service import _get_reranker
        rr = _get_reranker()
    except Exception as e:  # pragma: no cover
        logger.warning("card_reranker: reranker import failed: %s", e)

    if rr is None or not query:
        kept = results[:eff_top]
        env["results"] = kept
        env["count"] = len(kept)
        return json.dumps(env, ensure_ascii=False), {
            "tool": tool_name, "mode": "fallback-no-ce",
            "in": len(results), "out": len(kept),
        }

    pairs = [(query, _doc_text(r)) for r in results]
    try:
        scores = rr.predict(pairs)
    except Exception as e:  # pragma: no cover
        logger.warning("card_reranker: CE predict failed: %s", e)
        kept = results[:eff_top]
        env["results"] = kept
        env["count"] = len(kept)
        return json.dumps(env, ensure_ascii=False), {
            "tool": tool_name, "mode": "fallback-ce-error",
            "in": len(results), "out": len(kept),
        }

    scored = sorted(
        zip(results, (float(s) for s in scores)),
        key=lambda x: x[1], reverse=True,
    )
    if soft_gate:
        # Vorschlags-Set: nur ranken (Reihenfolge), nie auf 0 gaten.
        kept = [r for r, _s in scored][:eff_top]
    else:
        kept = [r for r, s in scored if s >= threshold][:eff_top]
    env["results"] = kept
    env["count"] = len(kept)
    debug = {
        "tool": tool_name,
        "threshold": threshold,
        "soft_gate": soft_gate,
        "in": len(results),
        "out": len(kept),
        "top_scores": [round(s, 2) for _, s in scored[:6]],
        "dropped_by_gate": (0 if soft_gate else sum(1 for _, s in scored if s < threshold)),
    }
    logger.info(
        "card_reranker %s: %d→%d (gate=%.1f, dropped=%d) scores=%s",
        tool_name, len(results), len(kept), threshold,
        debug["dropped_by_gate"], debug["top_scores"],
    )
    return json.dumps(env, ensure_ascii=False), debug


__all__ = ["rerank_gate_envelope", "threshold_for_tool"]
