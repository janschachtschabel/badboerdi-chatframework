"""Gezielter Detail-Probe: exaktes Reasoning-Feld + Filter-Target + Token-Schwelle.

Ergänzt scan_thinking_staging.py um drei Präzisionen:
  1) FELD-SPLIT: misst len(reasoning) UND len(reasoning_content) GETRENNT
     (das Scan-Skript hatte beide per Fallback zusammengefasst) — für die
     Modelle, die wirklich Reasoning liefern (gpt-oss + 1 qwen).
  2) FILTER-TARGET: zeigt den exakten content-Kopf von deepseek-r1
     (<think>…</think>), damit klar ist, was ein Filter strippen müsste.
  3) TOKEN-SCHWELLE: Budget-Sweep auf qwen3.5-122b über mehrere max_tokens
     → ab wann kommt sichtbarer Output (vorher frisst Reasoning alles).

Seriell. Key aus B_API_KEY_STAGING. App-B_API_KEY unangetastet.
Aufruf (aus backend/):  python scripts/probe_reasoning_fields.py
"""
from __future__ import annotations

import asyncio
import os
import random
import string
import sys
import time

import httpx

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

AC_BASE = "https://b-api.staging.openeduhub.net/api/v1/llm/academiccloud"
KEY_VAR = "B_API_KEY_STAGING"
SYSTEM = "Du bist ein knapper Lerncoach. Antworte auf Deutsch."
PROMPT = ("Ein Geschäft verkauft 3 Stifte für 2,40 Euro. Wie viel kosten 7 Stifte? "
          "Nenne kurz den Rechenweg und das Ergebnis.")
TIMEOUT_S = 90


def _uniq() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


async def _call(client, key, model, max_tokens):
    body = {"model": model,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": f"{PROMPT} (ID: {_uniq()})"}],
            "max_tokens": max_tokens, "temperature": 0.3}
    t0 = time.perf_counter()
    r = await client.post(f"{AC_BASE}/chat/completions",
                          headers={"X-API-KEY": key, "Content-Type": "application/json"},
                          json=body, timeout=TIMEOUT_S)
    dur = round((time.perf_counter() - t0) * 1000)
    if r.status_code != 200:
        return {"ok": False, "status": r.status_code, "ms": dur, "body": r.text[:120]}
    d = r.json()
    ch = (d.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    usage = d.get("usage") or {}
    return {
        "ok": True, "ms": dur, "finish": ch.get("finish_reason"),
        "ct": usage.get("completion_tokens"), "pt": usage.get("prompt_tokens"),
        "content": msg.get("content") or "",
        "reasoning": msg.get("reasoning") or "",
        "reasoning_content": msg.get("reasoning_content") or "",
        "keys": [k for k in msg.keys() if k not in
                 ("role", "content", "tool_calls", "function_call", "refusal", "annotations")],
    }


async def main():
    key = (os.getenv(KEY_VAR) or "").strip()
    if not key:
        print(f"ERROR: {KEY_VAR} nicht gesetzt."); sys.exit(1)
    print("=" * 80)
    print("  DETAIL-PROBE: Reasoning-Felder + Filter-Target + Token-Schwelle")
    print("=" * 80)

    async with httpx.AsyncClient() as client:
        # 1+2) Feld-Split + Filter-Target
        for model in ("openai-gpt-oss-120b", "deepseek-r1-distill-llama-70b"):
            print(f"\n--- {model} (max_tokens=2500) ---")
            r = await _call(client, key, model, 2500)
            if not r["ok"]:
                print(f"  FEHLER HTTP {r['status']}: {r['body']}"); continue
            print(f"  finish={r['finish']}  ct={r['ct']}  keys={r['keys']}")
            print(f"  len(content)          = {len(r['content'])}")
            print(f"  len(reasoning)        = {len(r['reasoning'])}")
            print(f"  len(reasoning_content)= {len(r['reasoning_content'])}")
            print(f"  content[:200]         = {r['content'][:200]!r}")
            if r["reasoning"]:
                print(f"  reasoning[:160]       = {r['reasoning'][:160]!r}")
            if r["reasoning_content"]:
                print(f"  reasoning_content[:160]= {r['reasoning_content'][:160]!r}")

        # 3) Token-Schwelle auf qwen3.5-122b
        print(f"\n--- TOKEN-SCHWELLE: qwen3.5-122b-a10b über max_tokens ---")
        print(f"  {'max_tokens':>10s} | {'finish':>7s} | {'ct':>5s} | {'content':>7s} | {'reasoning':>9s}")
        print("  " + "-" * 52)
        for mt in (600, 1200, 1800, 2500, 3200):
            r = await _call(client, key, "qwen3.5-122b-a10b", mt)
            if not r["ok"]:
                print(f"  {mt:>10} | FEHLER HTTP {r['status']}")
                continue
            rsn = len(r["reasoning"]) + len(r["reasoning_content"])
            print(f"  {mt:>10} | {r['finish']:>7s} | {r['ct']:>5} | "
                  f"{len(r['content']):>7} | {rsn:>9}")
        print("\n  → 'content'=0 bei finish=length bedeutet: Reasoning hat das ganze")
        print("    Budget gefressen, KEINE sichtbare Antwort. Erst ab genug Budget")
        print("    (Reasoning fertig + Platz für Antwort) erscheint sichtbarer Text.")


if __name__ == "__main__":
    asyncio.run(main())
