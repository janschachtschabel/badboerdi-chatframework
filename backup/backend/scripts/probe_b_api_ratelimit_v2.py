"""Probe der B-API-Rate-Limit mit UNIQUE Payloads + multiplen Modellen.

V1 hatte cache-Treffer (identische Payloads → server gibt same response).
V2 sendet pro Call eine eindeutige Token-Anfrage und mischt Modelle, um
realistische Last zu simulieren.
"""
from __future__ import annotations

import asyncio
import os
import random
import string
import time
from collections import Counter

import httpx

B_API_BASE = "https://b-api.prod.openeduhub.net/api/v1/llm/academiccloud"
KEY_VAR = "B_API_KEY_PROD"

# Realistic mix: schnelle direkte Modelle (mistral, gpt-oss) + Qwen-Reasoning
MODELS = [
    "mistral-large-3-675b-instruct-2512",
    "openai-gpt-oss-120b",
    "qwen3.5-122b-a10b",
]

CONCURRENCIES = [1, 3, 5, 8, 12, 16]
PAUSE_BETWEEN_BURSTS_S = 10.0


def _unique_prompt(idx: int) -> list[dict]:
    """Eindeutige Prompts pro Call — gleiche Form wie der Bench, aber mit
    individuellem Seed um Server-Cache zu umgehen."""
    suffix = "".join(random.choices(string.ascii_lowercase, k=6))
    seed = f"{idx}-{suffix}-{int(time.time()*1000)}"
    return [
        {"role": "system", "content": "Du bist ein Lerncoach für Schüler:innen."},
        {"role": "user", "content": f"Erkläre mir Bruchrechnung in 2 Sätzen. (Anfrage-ID: {seed})"},
    ]


async def _one(client: httpx.AsyncClient, key: str, idx: int, model: str) -> dict:
    body = {
        "model": model,
        "messages": _unique_prompt(idx),
        "max_tokens": 400,
        "temperature": 0.4,
    }
    t0 = time.perf_counter()
    try:
        r = await client.post(
            f"{B_API_BASE}/chat/completions",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json=body,
            timeout=60,
        )
        dur = round((time.perf_counter() - t0) * 1000)
        return {
            "idx": idx, "model": model,
            "status": r.status_code, "ms": dur,
            "headers": dict(r.headers),
            "body_preview": r.text[:120] if r.status_code != 200 else "",
        }
    except Exception as e:
        return {
            "idx": idx, "model": model,
            "status": 0,
            "ms": round((time.perf_counter() - t0) * 1000),
            "headers": {},
            "body_preview": f"{type(e).__name__}: {e}",
        }


async def _burst(client: httpx.AsyncClient, key: str, concurrency: int) -> list[dict]:
    print(f"\n=== Burst {concurrency} parallel mit unique payloads ===")
    t0 = time.perf_counter()
    tasks = [
        _one(client, key, i, MODELS[i % len(MODELS)])
        for i in range(concurrency)
    ]
    results = await asyncio.gather(*tasks)
    total_dur = round((time.perf_counter() - t0) * 1000)
    statuses = Counter(r["status"] for r in results)
    print(f"  Total burst time: {total_dur}ms")
    print(f"  Statuses: {dict(statuses)}")
    print(f"  Min/Median/Max latency: {min(r['ms'] for r in results)}ms / "
          f"{sorted(r['ms'] for r in results)[len(results)//2]}ms / "
          f"{max(r['ms'] for r in results)}ms")

    # Per-model breakdown
    by_model: dict[str, list[int]] = {}
    for r in results:
        by_model.setdefault(r["model"], []).append(r["status"])
    for m, s in by_model.items():
        ok = sum(1 for st in s if st == 200)
        print(f"  {m:42s}: {ok}/{len(s)} OK")

    # Rate-limit headers
    rl = {}
    for r in results:
        for k, v in r["headers"].items():
            if any(t in k.lower() for t in ("ratelimit", "rate-limit", "retry-after")):
                rl[k] = v
    if rl:
        print(f"  Rate-Limit-Header: {rl}")

    # Errors detail
    errs = [r for r in results if r["status"] != 200]
    if errs:
        e = errs[0]
        print(f"  Erstes Error-Beispiel: HTTP {e['status']}  {e['body_preview']!r}")

    return results


async def main() -> None:
    key = os.environ[KEY_VAR]
    print(f"Probing B-API rate limit on {B_API_BASE}")
    print(f"Modelle (rund-robin): {MODELS}")
    print(f"Concurrency-Stufen: {CONCURRENCIES}")
    safe_max = 0
    first_throttle = None
    async with httpx.AsyncClient() as client:
        for c in CONCURRENCIES:
            results = await _burst(client, key, c)
            ok = sum(1 for r in results if r["status"] == 200)
            if ok == c:
                safe_max = c
            elif first_throttle is None:
                first_throttle = c
            await asyncio.sleep(PAUSE_BETWEEN_BURSTS_S)
    print()
    print("=" * 70)
    print(f"Höchste sichere Concurrency mit 100% OK: {safe_max}")
    if first_throttle is not None:
        print(f"Erste Throttle-Stufe (≥1 Fehler): {first_throttle}")
    else:
        print("Keine Drosselung bis Concurrency=" + str(max(CONCURRENCIES)))
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
