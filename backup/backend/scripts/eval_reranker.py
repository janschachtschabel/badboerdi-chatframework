"""Evaluate rerank quality via LLM-as-Judge.

For each test query, fetch top-5 chunks from two variants:
  A) Baseline (embedding-only ranking)
  B) Rerank (cross-encoder reordering)

Ask an LLM judge which ranking better answers the query. To mitigate
position bias, run each pairing in both orderings — only count a win
when both orderings agree. Ties otherwise.

Exit code 0 always; this is a measurement tool, not a gate.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Allow running as `python scripts/eval_reranker.py` from backend/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Test queries — realistic user questions against the seeded WLO KB.
# Mix of factual, comparative, and exploratory to stress-test rerank.
TEST_QUERIES: list[str] = [
    "Was ist WissenLebtOnline?",
    "Wer betreibt WLO?",
    "Wie viele OER gibt es in Deutschland?",
    "Was macht die Redaktion?",
    "Welche Lizenzen haben die Materialien?",
    "Was ist der Unterschied zwischen OER und freien Inhalten?",
    "Wie kann ich als Lehrkraft eigene Materialien einreichen?",
    "Welche Rolle spielt edu-sharing fuer WLO?",
    "Was macht die GWDG bei diesem Projekt?",
    "Gibt es Materialien fuer Grundschule?",
]

AREAS = [
    "WissenLebtOnline", "WirLernenOnline", "FAQ",
    "OER-Wissen", "Edu-Sharing-Network", "Edu-Sharing-Metaventis",
]

ONNX_INT8_DIR = (
    "C:/Users/jan/staging/Windsurf/wlo-suche/badboerdi/backend/"
    "models/cross-encoder__mmarco-mMiniLMv2-L12-H384-v1-int8"
)


def _format_ranking(results: list[dict], label: str) -> str:
    lines = [f"Ranking {label}:"]
    for i, r in enumerate(results, 1):
        src = r.get("title") or r.get("source", "?")
        chunk = (r.get("chunk") or "").replace("\n", " ")[:400]
        lines.append(f"  {i}. [{src}] {chunk}")
    return "\n".join(lines)


JUDGE_PROMPT = """Du bist ein unparteiischer Gutachter fuer Retrieval-Qualitaet.

FRAGE: {query}

Zwei Rankings aus einer Wissensdatenbank. Welches beantwortet die Frage besser?
Bewerte nach: (a) enthaelt das Top-1 die direkte Antwort? (b) sind die oberen
Treffer thematisch relevanter? Ignoriere Reihenfolge, wenn beide Top-5 denselben
Pool haben aber anders sortiert sind — dann zaehlt nur Top-1/Top-2.

{ranking_a}

{ranking_b}

Antworte NUR mit einem JSON-Objekt:
{{"winner": "A" | "B" | "TIE", "reason": "<ein Satz>"}}"""


async def judge_pair(query: str, ranking_a: list[dict], ranking_b: list[dict],
                     label_a: str, label_b: str) -> dict:
    """Call LLM judge on one ordering. Returns {winner, reason}."""
    from app.services.llm_provider import get_client
    client = get_client()
    prompt = JUDGE_PROMPT.format(
        query=query,
        ranking_a=_format_ranking(ranking_a, label_a),
        ranking_b=_format_ranking(ranking_b, label_b),
    )
    # Use a capable model; gpt-4o-mini is cheap and reliable enough for judging.
    model = os.getenv("EVAL_JUDGE_MODEL", "gpt-4o-mini")
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content or "{}"
    try:
        return json.loads(raw)
    except Exception:
        return {"winner": "TIE", "reason": f"parse error: {raw[:100]}"}


async def fetch_top(query: str, top_k: int, rerank: bool) -> list[dict]:
    """Get the actual top-k result dicts (not formatted context)."""
    import app.services.rag_service as rs
    # query per-area, merge, apply the same logic as get_rag_context
    all_results = []
    for area in AREAS:
        res = await rs.query_rag(query, area, top_k=15)
        all_results.extend(res)
    all_results.sort(key=lambda x: x["score"], reverse=True)
    plausible = [r for r in all_results if r["score"] >= 0.25]
    if rerank and plausible:
        return rs.rerank_results(query, plausible[:25], top_k)
    return plausible[:top_k]


async def evaluate(queries: list[str]) -> dict:
    import app.services.rag_service as rs
    # reset caches + env
    rs._reranker = None
    rs._reranker_loaded = False
    os.environ["RAG_RERANK"] = "on"
    os.environ["RAG_RERANK_BACKEND"] = "onnx"
    os.environ["RAG_RERANK_MODEL_DIR"] = ONNX_INT8_DIR

    results_summary = []
    wins_rerank = wins_baseline = ties = 0

    for q in queries:
        print(f"\n>>> {q}")
        baseline = await fetch_top(q, top_k=5, rerank=False)
        reranked = await fetch_top(q, top_k=5, rerank=True)

        if not baseline:
            print("   (no baseline results, skipping)")
            continue

        # Judge both orderings (bias mitigation)
        j1 = await judge_pair(q, baseline, reranked, "A (Baseline)", "B (Rerank)")
        j2 = await judge_pair(q, reranked, baseline, "A (Rerank)", "B (Baseline)")

        # Consensus: rerank wins only if j1 picks B and j2 picks A
        w1 = j1.get("winner", "TIE").upper()
        w2 = j2.get("winner", "TIE").upper()
        if w1 == "B" and w2 == "A":
            verdict = "RERANK"
            wins_rerank += 1
        elif w1 == "A" and w2 == "B":
            verdict = "BASELINE"
            wins_baseline += 1
        else:
            verdict = "TIE"
            ties += 1

        top_b = (baseline[0].get("title") or baseline[0].get("source", "?"))
        top_r = (reranked[0].get("title") or reranked[0].get("source", "?"))
        print(f"   baseline top: {top_b}")
        print(f"   rerank   top: {top_r}")
        print(f"   verdict: {verdict}  (j1={w1}, j2={w2})")
        print(f"   reasons: {j1.get('reason','')[:80]} / {j2.get('reason','')[:80]}")
        results_summary.append({
            "query": q, "verdict": verdict,
            "top_baseline": top_b, "top_rerank": top_r,
            "j1": j1, "j2": j2,
        })

    total = wins_rerank + wins_baseline + ties
    print("\n" + "=" * 60)
    print(f"Total queries judged: {total}")
    print(f"  RERANK wins:   {wins_rerank}/{total}")
    print(f"  BASELINE wins: {wins_baseline}/{total}")
    print(f"  TIES:          {ties}/{total}")
    return {
        "total": total,
        "rerank_wins": wins_rerank,
        "baseline_wins": wins_baseline,
        "ties": ties,
        "per_query": results_summary,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="Optional JSON output path")
    args = ap.parse_args()

    t0 = time.perf_counter()
    summary = asyncio.run(evaluate(TEST_QUERIES))
    dt = time.perf_counter() - t0
    print(f"\nElapsed: {dt:.1f}s")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"Saved: {args.out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
