"""Probe the B-API rate limit empirically.

Strategy:
- Send N parallel-burst requests at increasing concurrency levels
  (1, 2, 3, 5, 8, 12).
- Per burst: count 200, 401, 429, other errors. Print response headers
  the first time each shape is observed (looking for X-RateLimit-*,
  Retry-After, etc.).
- Use the smallest, cheapest model to keep costs/latency low.
- Find the largest concurrency level that still yields 100% success.
"""
from __future__ import annotations

import asyncio
import os
import time
from collections import Counter

import httpx

B_API_BASE = "https://b-api.prod.openeduhub.net/api/v1/llm/academiccloud"
KEY_VAR = "B_API_KEY_PROD"

# Realistic Schüler-Payload (~150 prompt tokens) wie im echten Bench.
MODEL = "mistral-large-3-675b-instruct-2512"
SYSTEM = (
    "Du bist Boerdi, ein freundlicher Lerncoach für Schüler:innen auf der "
    "Plattform WirLernenOnline (WLO). Du duzt, antwortest knapp und in einfacher "
    "Sprache. Du kannst Lernmaterial vorschlagen, Fakten erklären, Lernpläne "
    "erstellen und Quiz/Arbeitsblätter generieren. Bei Feedback nimmst du es "
    "ernst. Antworte in 2-4 Sätzen wenn nicht ausdrücklich mehr verlangt ist."
)
PROMPT = [
    {"role": "system", "content": SYSTEM},
    {"role": "user", "content": "Brauche Übungsmaterial zur Bruchrechnung für Klasse 7."},
]
PAYLOAD = {"model": MODEL, "messages": PROMPT, "max_tokens": 400, "temperature": 0.4}

CONCURRENCIES = [1, 3, 5, 8, 12, 16, 24, 32]
PAUSE_BETWEEN_BURSTS_S = 8.0  # generous reset window


async def _one(client: httpx.AsyncClient, key: str, idx: int) -> dict:
    t0 = time.perf_counter()
    try:
        r = await client.post(
            f"{B_API_BASE}/chat/completions",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json=PAYLOAD,
            timeout=60,
        )
        dur = round((time.perf_counter() - t0) * 1000)
        return {
            "idx": idx,
            "status": r.status_code,
            "ms": dur,
            "headers": dict(r.headers),
            "body_len": len(r.content),
            "body_preview": r.text[:80] if r.status_code != 200 else "",
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
    print(f"  Total burst time: {total_dur}ms")
    print(f"  Statuses: {dict(statuses)}")
    # Look for rate-limit headers in any response
    rl_headers = {}
    for r in results:
        for k, v in r["headers"].items():
            if any(t in k.lower() for t in ("ratelimit", "rate-limit", "retry-after", "x-rate")):
                rl_headers[k] = v
    if rl_headers:
        print(f"  Rate-limit-Header gefunden: {rl_headers}")
    # Show error bodies once
    errs = [r for r in results if r["status"] != 200]
    if errs:
        e = errs[0]
        print(f"  Erstes Error-Beispiel: HTTP {e['status']}  {e['body_preview']!r}")
    return results


async def main() -> None:
    key = os.environ[KEY_VAR]
    print(f"Probing B-API rate limit on {B_API_BASE}")
    print(f"Modell: {MODEL}, Payload-Größe: ~{sum(len(m['content']) for m in PROMPT)} Bytes")
    print(f"Concurrency-Stufen: {CONCURRENCIES}")
    safe_max_concurrency = 0
    last_throttled_at = None
    async with httpx.AsyncClient() as client:
        for c in CONCURRENCIES:
            results = await _burst(client, key, c)
            ok = sum(1 for r in results if r["status"] == 200)
            if ok == c:
                safe_max_concurrency = c
            else:
                last_throttled_at = c
                print(f"  → Drosselung erkannt bei {c}")
                # Don't break — show all stages
            await asyncio.sleep(PAUSE_BETWEEN_BURSTS_S)
    print()
    print("=" * 70)
    print(f"  Höchste sichere Concurrency mit 100% OK: {safe_max_concurrency}")
    if last_throttled_at:
        print(f"  Erste Throttle-Stufe (≥1 Fehler): {last_throttled_at}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
