"""Präziser Speed-Vergleich: AcademicCloud-Modelle vs. gpt-5.4-mini.

Sauberere Methodik als der grobe Bench:
  * FIXE Last: ein mittellanger Prompt, pro Call ein eindeutiger ID-Suffix
    (umgeht den B-API-Server-Cache → echte Inferenz-Latenz, keine Cache-Hits).
  * ROUND-ROBIN-Interleaving: in jeder Runde wird jedes Modell genau einmal
    gemessen → alle Modelle sehen dieselben Last-/Tageszeit-Fenster, ein
    einzelner Staging-Lastspike trifft alle gleich statt nur eines.
  * WARMUP: ein verworfener Call pro Modell (gegen Cold-Start-Verzerrung).
  * N=10 Messungen pro Modell, volle Verteilung (median, p25/p75, min/max, stdev).

Alles STRIKT SERIELL (AcademicCloud erlaubt keine parallelen Calls).
Baseline = gpt-5.4-mini eff=none (so ruft die App heute den Hauptantwort-Call
mit Tools auf → reasoning_effort wird gedroppt). mistral wird relativ dazu
ausgewiesen.

Keys aus der Umgebung: B_API_KEY_STAGING. App-B_API_KEY unangetastet.

Aufruf (aus backend/):
    python scripts/speed_compare_staging.py
    $env:SPEED_N = "15"; python scripts/speed_compare_staging.py   # mehr Samples
"""
from __future__ import annotations

import asyncio
import os
import random
import statistics
import string
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.llm_provider import _shape_max_tokens  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

B_API_BASE = "https://b-api.staging.openeduhub.net/api/v1/llm"
AC_BASE = f"{B_API_BASE}/academiccloud"
OAI_PASSTHRU = f"{B_API_BASE}/openai"
KEY_VAR = "B_API_KEY_STAGING"

SYSTEM = "Du bist Boerdi, ein knapper, freundlicher Lerncoach. Antworte direkt, ohne Vorrede."
PROMPT = "Erkläre einer Schülerin der 7. Klasse Bruchrechnung in 3-4 kurzen Sätzen."

# (label, base, model, style, extra)
CONFIGS = [
    ("mistral-large-3",       AC_BASE,      "mistral-large-3-675b-instruct-2512", "classic", {}),
    ("gemma-3-27b",           AC_BASE,      "gemma-3-27b-it",                      "classic", {}),
    ("gpt-oss-120b",          AC_BASE,      "openai-gpt-oss-120b",                 "classic", {}),
    ("gpt-5.4-mini eff=low",  OAI_PASSTHRU, "gpt-5.4-mini",  "gpt5", {"reasoning_effort": "low"}),
    ("gpt-5.4-mini eff=none", OAI_PASSTHRU, "gpt-5.4-mini",  "gpt5", {}),
]
BASELINE = "gpt-5.4-mini eff=none"

N = int((os.getenv("SPEED_N") or "10").strip())
BASE_MAX_TOKENS = 400
TIMEOUT_S = 60


def _uniq() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


def _body(cfg: tuple) -> dict:
    _, _, model, style, extra = cfg
    b: dict = {"model": model,
               "messages": [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": f"{PROMPT} (ID: {_uniq()})"}]}
    if style == "gpt5":
        b["verbosity"] = "medium"
        b.update(extra)
    else:
        b["max_tokens"] = _shape_max_tokens(model, BASE_MAX_TOKENS)
        b["temperature"] = 0.4
    return b


async def _call(client: httpx.AsyncClient, key: str, cfg: tuple) -> tuple[int, bool]:
    """Returns (latency_ms, ok). ok=False on non-200/exception (excluded from stats)."""
    _, base, *_ = cfg
    t0 = time.perf_counter()
    try:
        r = await client.post(f"{base}/chat/completions",
                              headers={"X-API-KEY": key, "Content-Type": "application/json"},
                              json=_body(cfg), timeout=TIMEOUT_S)
        dur = round((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            return dur, False
        content = ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return dur, bool(content.strip())
    except Exception:
        return round((time.perf_counter() - t0) * 1000), False


async def main() -> None:
    key = (os.getenv(KEY_VAR) or "").strip()
    print("=" * 80)
    print("  PRÄZISER SPEED-VERGLEICH × B-API STAGING")
    print(f"  N={N} pro Modell · Round-Robin · Warmup verworfen · seriell")
    if not key:
        print(f"\nERROR: {KEY_VAR} nicht gesetzt.")
        sys.exit(1)
    print(f"  key: {key[:6]}*** · Prompt: {PROMPT!r}")
    print("=" * 80)

    samples: dict[str, list[int]] = {c[0]: [] for c in CONFIGS}
    fails: dict[str, int] = {c[0]: 0 for c in CONFIGS}

    async with httpx.AsyncClient() as client:
        # Warmup (discarded) — defeats cold-start on the first measured sample.
        print("\n  Warmup (verworfen): ", end="", flush=True)
        for cfg in CONFIGS:
            await _call(client, key, cfg)
            print(f"{cfg[0].split()[0]} ", end="", flush=True)
        print("\n")

        for rnd in range(1, N + 1):
            line = f"  Runde {rnd:>2}/{N}: "
            for cfg in CONFIGS:
                dur, ok = await _call(client, key, cfg)
                if ok:
                    samples[cfg[0]].append(dur)
                    line += f"{cfg[0].split()[0][:7]:>7}={dur:>5} "
                else:
                    fails[cfg[0]] += 1
                    line += f"{cfg[0].split()[0][:7]:>7}=ERR   "
            print(line, flush=True)

    # ── Stats ──
    print("\n" + "=" * 80)
    print("  ERGEBNIS (nur erfolgreiche Calls)")
    print("=" * 80)
    base_med = statistics.median(samples[BASELINE]) if samples.get(BASELINE) else None

    h = (f"  {'Modell':22s} | {'n':>2s} | {'median':>7s} | {'p25':>6s} | {'p75':>6s} | "
         f"{'min':>5s} | {'max':>6s} | {'stdev':>6s} | {'vs base':>8s}")
    print(h)
    print("  " + "-" * (len(h) - 2))
    # Sort by median ascending (fastest first)
    ordered = sorted(CONFIGS, key=lambda c: statistics.median(samples[c[0]]) if samples[c[0]] else 9e9)
    for cfg in ordered:
        label = cfg[0]
        data = samples[label]
        if not data:
            print(f"  {label:22s} | {0:>2} | (keine erfolgreichen Calls, {fails[label]} Fehler)")
            continue
        med = statistics.median(data)
        if len(data) >= 2:
            q = statistics.quantiles(data, n=4)
            p25, p75 = int(q[0]), int(q[2])
            sd = int(statistics.pstdev(data))
        else:
            p25 = p75 = int(med)
            sd = 0
        rel = ""
        if base_med:
            pct = (med - base_med) / base_med * 100
            rel = f"{pct:+.0f}%"
        ferr = f"  (+{fails[label]} err)" if fails[label] else ""
        print(f"  {label:22s} | {len(data):>2} | {int(med):>6}ms | {p25:>5}ms | {p75:>5}ms | "
              f"{min(data):>4}ms | {max(data):>5}ms | {sd:>5}ms | {rel:>8s}{ferr}")

    print(f"\n  Baseline (vs base = 0%): {BASELINE}  "
          f"(= so ruft die App heute den Hauptantwort-Call mit Tools auf)")
    print("  Interpretation: 'vs base' < 0% = schneller als die aktuelle Produktions-Latenz,")
    print("                  > 0% = langsamer. stdev klein = stabile Latenz.")


if __name__ == "__main__":
    asyncio.run(main())
