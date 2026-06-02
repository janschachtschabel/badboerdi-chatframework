"""Cross-Encoder (ONNX mmarco) auf alle 3 WLO-Inhaltstypen anwenden.
Vergleicht MCP-Reihenfolge vs. Cross-Encoder-Reihenfolge + zeigt Scores
(Logit / Sigmoid), um zu beurteilen, ob ein CE-basiertes Top-3 + Relevanz-
Gate sinnvoll ist. Aufruf (backend/):  python scripts/test_reranker_3types.py
"""
from __future__ import annotations
import asyncio, math, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()
from app.services.mcp_client import (  # noqa: E402
    call_mcp_tool, parse_wlo_cards, parse_wlo_topic_page_cards,
)
from app.services.rag_service import _get_reranker  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def sig(x: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def doc_text(c: dict) -> str:
    t = (c.get("title") or "").strip()
    d = (c.get("description") or "").strip()
    kw = " ".join(str(k) for k in (c.get("keywords") or []))
    return f"{t}. {d} {kw}".strip()[:450]


async def fetch(query: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    rc = await call_mcp_tool("search_wlo_content", {"query": query, "maxResults": 8, "outputFormat": "json"})
    out["content"] = parse_wlo_cards(rc) or []
    rl = await call_mcp_tool("search_wlo_collections", {"query": query, "maxResults": 8, "outputFormat": "json"})
    out["collection"] = parse_wlo_cards(rl) or []
    rt = await call_mcp_tool("search_wlo_topic_pages", {"query": query, "maxResults": 8, "outputFormat": "json"})
    out["topic"] = parse_wlo_topic_page_cards(rt) or []
    return out


async def main():
    rr = _get_reranker()
    if not rr:
        print("Reranker nicht verfügbar (Modell fehlt / RAG_RERANKER_ENABLED=false).")
        return
    for q in ["Bruchrechnung", "Klimawandel", "Französische Revolution"]:
        cand = await fetch(q)
        print(f"\n################  QUERY: {q!r}  ################")
        for typ in ("content", "collection", "topic"):
            cards = cand.get(typ) or []
            if not cards:
                print(f"  [{typ:10s}] keine Treffer")
                continue
            pairs = [(q, doc_text(c)) for c in cards]
            scores = rr.predict(pairs)
            ranked = sorted(zip(cards, scores), key=lambda x: x[1], reverse=True)
            print(f"\n  === {typ.upper()} ({len(cards)} Treffer) — Cross-Encoder-Reihenfolge ===")
            mcp_top3 = [str(c.get("title") or "")[:34] for c in cards[:3]]
            print(f"    MCP-Top3 : {mcp_top3}")
            for c, s in ranked:
                print(f"      {s:+6.2f} / {sig(s):.2f}   {str(c.get('title') or '')[:60]}")


if __name__ == "__main__":
    asyncio.run(main())
