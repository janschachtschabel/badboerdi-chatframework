"""LLM-as-Judge: bewertet die Antworten aus dem 5-Modelle-Bench.

Liest die letzte ``bench_results/5models-schueler-*.json``, läßt jedes
Antwort-Snippet von ``gpt-5.4-mini`` auf 4 Achsen bewerten (1-5 Sterne):

  relevance  — passt die Antwort zur Schüler-Anfrage?
  ton        — duzt, schülergerecht, freundlich, kein Edu-Jargon?
  concrete   — verwertbar (Material/Schritte/Antwort) statt ausweichend?
  brevity    — angemessen kurz für Chat-Widget (2-4 Sätze)?

Schreibt eine Markdown-Tabelle mit Mittelwerten + Beispiel-Auszügen.
"""
from __future__ import annotations

import asyncio
import glob
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

from openai import AsyncOpenAI

# Use native OpenAI for the judge (GPT-5.4-mini works well for ratings)
# OPENAI_API_KEY must be in env.
JUDGE_MODEL = "gpt-5.4-mini"
CONCURRENCY = 4

JUDGE_SYSTEM = """Du bist ein strenger, fairer Bewertungs-Richter für Schüler-Chatbot-Antworten.

Bewerte die Antwort eines LLM auf eine Schüler-Anfrage auf 4 Achsen,
JEWEILS auf einer Skala 1-5 (1=schlecht, 5=exzellent):

* relevance:  Adressiert die Antwort die konkrete Anfrage des Schülers?
* ton:        Duzt das Modell? Klingt es freundlich, kindgerecht, ohne EdTech-/
              Lehrer-Jargon? (Wörter wie "Lernende", "Bildungsstufe" ⇒ Punktabzug)
* concrete:   Liefert die Antwort konkrete Hilfe (Material, Schritte, Fakten),
              statt nur Allgemeinplätze oder Rückfragen?
* brevity:    Ist die Länge angemessen für ein Chat-Widget (2-4 Sätze, max
              5-6 Sätze)? Lange Walls-of-Text ⇒ Punktabzug.

Antworte AUSSCHLIESSLICH mit gültigem JSON nach diesem Schema:
{"relevance": <1-5>, "ton": <1-5>, "concrete": <1-5>, "brevity": <1-5>,
 "comment": "kurze Begründung in 1 Satz"}
"""


async def _judge(client: AsyncOpenAI, intent_id: str, intent_label: str,
                 user_msg: str, model_name: str, response: str) -> dict:
    if not response or len(response) < 5:
        return {"relevance": 1, "ton": 1, "concrete": 1, "brevity": 1,
                "comment": "Leere Antwort (Reasoning hat Budget gefressen)"}
    try:
        r = await client.chat.completions.create(
            model=JUDGE_MODEL,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": (
                    f"Intent: {intent_id} ({intent_label})\n"
                    f"Schüler-Anfrage: {user_msg!r}\n"
                    f"Modell: {model_name}\n"
                    f"Antwort des Modells:\n---\n{response[:1500]}\n---\n\n"
                    f"Bewerte die Antwort. Nur JSON."
                )},
            ],
            response_format={"type": "json_object"},
            verbosity="low",
        )
        content = r.choices[0].message.content or "{}"
        scores = json.loads(content)
        for k in ("relevance", "ton", "concrete", "brevity"):
            scores[k] = max(1, min(5, int(scores.get(k, 3))))
        return scores
    except Exception as e:
        return {"relevance": 0, "ton": 0, "concrete": 0, "brevity": 0,
                "comment": f"Judge failed: {type(e).__name__}: {e}"}


async def main() -> None:
    files = sorted(glob.glob("scripts/bench_results/5models-schueler-*.json"))
    if not files:
        print("ERROR: No bench results to judge.")
        sys.exit(1)
    fp = files[-1]
    print(f"Judging: {fp}")
    data = json.loads(Path(fp).read_text(encoding="utf-8"))
    results = data["results"]
    intents_by_id = {i["id"]: i for i in data["intents"]}

    client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)

    async def _one(r: dict) -> dict:
        async with sem:
            if not r.get("ok"):
                scores = {"relevance": 1, "ton": 1, "concrete": 1, "brevity": 1,
                          "comment": f"Call failed: {r.get('error','?')[:80]}"}
            else:
                scores = await _judge(
                    client,
                    r["intent_id"], r["intent_label"],
                    r["user_msg"], r["model"],
                    r.get("content_preview", ""),
                )
            print(f"  judged {r['model']:42s} {r['intent_id']:8s} → "
                  f"R={scores['relevance']} T={scores['ton']} "
                  f"C={scores['concrete']} B={scores['brevity']}", flush=True)
            return {**r, "judge": scores}

    judged = await asyncio.gather(*[_one(r) for r in results])

    # Aggregate per model
    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in judged:
        by_model[r["model"]].append(r["judge"])

    print()
    print("=" * 100)
    print("QUALITÄTS-BEWERTUNG (GPT-5.4-mini Judge, 1-5 Sterne)")
    print("=" * 100)
    h = (
        f"{'Modell':40s} | {'rel':>4s} | {'ton':>4s} | {'conc':>4s} | "
        f"{'brev':>4s} | {'⌀ gesamt':>9s}"
    )
    print(h)
    print("-" * len(h))
    summary = {}
    for m, scores in by_model.items():
        rel  = mean(s["relevance"] for s in scores)
        ton  = mean(s["ton"] for s in scores)
        conc = mean(s["concrete"] for s in scores)
        brev = mean(s["brevity"] for s in scores)
        ovr  = mean([rel, ton, conc, brev])
        summary[m] = {"relevance": rel, "ton": ton, "concrete": conc,
                      "brevity": brev, "overall": ovr}
        print(f"{m:40s} | {rel:>4.2f} | {ton:>4.2f} | {conc:>4.2f} | "
              f"{brev:>4.2f} | {ovr:>9.2f}")
    print()

    # Save judged results
    out = {**data, "judged": judged, "judge_summary": summary,
           "judge_model": JUDGE_MODEL}
    out_fp = Path(fp).with_name(Path(fp).stem + "-judged.json")
    out_fp.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Detail-JSON: {out_fp}")


if __name__ == "__main__":
    asyncio.run(main())
