"""Probe the STAGING b-api-openai rate limit empirically — gpt-5.4-mini.

Variante des Prod-Probes (``probe_b_api_ratelimit.py``), aber gegen die
Anbindung, die der Chatbot aktuell wirklich nutzt:

* Endpoint:  ``{B_API_BASE_URL}/openai/chat/completions``
             (Default Staging, per Env überschreibbar)
* Modell:    ``gpt-5.4-mini``  (GPT-5-Param-Kontrakt!)
* Key:       ``B_API_KEY_STAGING``

GPT-5-Familie: KEIN ``max_tokens``/``temperature`` — stattdessen
``verbosity`` + ``reasoning_effort`` als Top-Level-Felder (tool-loser
Turn, daher ist ``reasoning_effort`` erlaubt). Spiegelt den Param-Satz,
den ``llm_provider.complete_chat`` für GPT-5 zusammenbaut.

Strategie wie beim Original: Burst mit steigender Concurrency, je Stufe
200/401/429/sonst zählen, Rate-Limit-Header anzeigen, höchste Stufe mit
100 % OK ausgeben. Bricht früh ab, falls schon der 1er-Burst kein 200
liefert (dann stimmt Payload/Endpoint/Key nicht — kein Sinn weiterzufeuern).
"""
from __future__ import annotations

import asyncio
import os
import time
from collections import Counter

import httpx

_BASE = (os.getenv("B_API_BASE_URL")
         or "https://b-api.staging.openeduhub.net/api/v1/llm").rstrip("/")
B_API_URL = f"{_BASE}/openai/chat/completions"
KEY_VAR = "B_API_KEY_STAGING"

MODEL = os.getenv("LLM_CHAT_MODEL") or "gpt-5.4-mini"
SYSTEM = (
    "Du bist Boerdi, ein freundlicher Lerncoach für Schüler:innen auf der "
    "Plattform WirLernenOnline (WLO). Du duzt, antwortest knapp und in einfacher "
    "Sprache. Antworte in 2-4 Sätzen wenn nicht ausdrücklich mehr verlangt ist."
)
PROMPT = [
    {"role": "system", "content": SYSTEM},
    {"role": "user", "content": "Brauche Übungsmaterial zur Bruchrechnung für Klasse 7."},
]
# GPT-5-Kontrakt: verbosity + reasoning_effort, KEIN max_tokens/temperature.
PAYLOAD = {
    "model": MODEL,
    "messages": PROMPT,
    "verbosity": "low",
    "reasoning_effort": "low",
}

CONCURRENCIES = [1, 3, 5, 8, 12, 16, 20, 24, 32]
PAUSE_BETWEEN_BURSTS_S = 8.0  # großzügiges Reset-Fenster


async def _one(client: httpx.AsyncClient, key: str, idx: int) -> dict:
    t0 = time.perf_counter()
    try:
        r = await client.post(
            B_API_URL,
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json=PAYLOAD,
            timeout=90,
        )
        dur = round((time.perf_counter() - t0) * 1000)
        return {
            "idx": idx,
            "status": r.status_code,
            "ms": dur,
            "headers": dict(r.headers),
            "body_len": len(r.content),
            "body_preview": r.text[:120] if r.status_code != 200 else "",
        }
    except Exception as e:
        return {
            "idx": idx,
            "status": 0,
            "ms": round((time.perf_counter() - t0) * 1000),
            "headers": {},
            "body_len": 0,
            "body_preview": f"{type(e).__name__}: {e}",
        }


async def _burst(client: httpx.AsyncClient, key: str, concurrency: int) -> list[dict]:
    print(f"\n=== Burst-Test mit {concurrency} parallelen Requests ===")
    t0 = time.perf_counter()
    tasks = [_one(client, key, i) for i in range(concurrency)]
    results = await asyncio.gather(*tasks)
    total_dur = round((time.perf_counter() - t0) * 1000)
    statuses = Counter(r["status"] for r in results)
    oks = [r["ms"] for r in results if r["status"] == 200]
    print(f"  Total burst time: {total_dur}ms")
    print(f"  Statuses: {dict(statuses)}")
    if oks:
        oks_sorted = sorted(oks)
        p50 = oks_sorted[len(oks_sorted) // 2]
        print(f"  OK-Latenz: min={min(oks)}ms  p50={p50}ms  max={max(oks)}ms")
    rl_headers = {}
    for r in results:
        for k, v in r["headers"].items():
            if any(t in k.lower() for t in ("ratelimit", "rate-limit", "retry-after", "x-rate")):
                rl_headers[k] = v
    if rl_headers:
        print(f"  Rate-limit-Header: {rl_headers}")
    errs = [r for r in results if r["status"] != 200]
    if errs:
        e = errs[0]
        print(f"  Erstes Error-Beispiel: HTTP {e['status']}  {e['body_preview']!r}")
    return results


async def main() -> None:
    key = os.environ.get(KEY_VAR)
    if not key:
        print(f"FEHLER: {KEY_VAR} nicht gesetzt — abbrechen.")
        return
    print(f"Probing STAGING b-api-openai: {B_API_URL}")
    print(f"Modell: {MODEL}  (GPT-5-Params: verbosity=low, reasoning_effort=low)")
    print(f"Concurrency-Stufen: {CONCURRENCIES}")
    safe_max_concurrency = 0
    last_throttled_at = None
    async with httpx.AsyncClient() as client:
        for i, c in enumerate(CONCURRENCIES):
            results = await _burst(client, key, c)
            ok = sum(1 for r in results if r["status"] == 200)
            # Früh-Abbruch: wenn schon der 1er-Burst scheitert, stimmt
            # Payload/Endpoint/Key nicht — kein Sinn, 100 Calls zu feuern.
            if i == 0 and ok == 0:
                print("\nABBRUCH: 1er-Burst lieferte kein 200 — Payload/Endpoint/Key prüfen.")
                return
            if ok == c:
                safe_max_concurrency = c
            else:
                last_throttled_at = c
                print(f"  → Drosselung erkannt bei {c} ({ok}/{c} OK)")
            await asyncio.sleep(PAUSE_BETWEEN_BURSTS_S)
    print()
    print("=" * 70)
    print(f"  Höchste sichere Concurrency mit 100% OK: {safe_max_concurrency}")
    if last_throttled_at:
        print(f"  Erste Throttle-Stufe (>=1 Fehler): {last_throttled_at}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
