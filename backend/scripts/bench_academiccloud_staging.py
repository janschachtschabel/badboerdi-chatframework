"""Benchmark AcademicCloud-Chatmodelle vs. gpt-5.4-mini + Embedding-Speed.

Beantwortet drei Fragen auf b-api.staging.openeduhub.net:

  1) REASONING-LEAK — Liefern die AcademicCloud-Modelle (v.a. der neue
     Default mistral-large-3) "Reasoning"-Output, den wir rausfiltern müssen?
     Unterschieden wird:
       * reasoning_content (separates Feld) → die App liest nur .content,
         also automatisch ignoriert — KEIN Filter nötig.
       * Reasoning IM sichtbaren content (z.B. <think>…</think> oder
         gpt-oss-"harmony"-Kanalmarker <|channel|>…) → würde beim User
         landen → Filter NÖTIG.
  2) SPEED — Latenz der AcademicCloud-Modelle vs. gpt-5.4-mini. gpt-5.4-mini
     wird in zwei Profilen gemessen:
       * effort=low  → tool-LOSE App-Calls (mit Reasoning)
       * effort=none → tool-BEHAFTETE App-Calls (Hauptantwort/Klassifikation;
         dort droppt die App reasoning_effort → schneller)
  3) EMBEDDING-SPEED — e5-mistral-7b-instruct (AcademicCloud) vs.
     text-embedding-3-small (OpenAI). NUR Messung, NICHT in die DB.

Alle Chat-Calls laufen STRIKT SERIELL (AcademicCloud erlaubt keine
parallelen Calls). Keys aus der Umgebung: B_API_KEY_STAGING (+ OPENAI_API_KEY
für die OpenAI-Embedding-Referenz). Die App nutzt weiter zentral B_API_KEY —
hier bewusst NICHT angefasst.

Aufruf (aus backend/):
    python scripts/bench_academiccloud_staging.py
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
from openai import AsyncOpenAI

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

# (label, endpoint, model, style, extra_for_gpt5)
#   style "classic" → max_tokens (shaped) + temperature
#   style "gpt5"    → verbosity=medium (+ optional reasoning_effort)
CHAT_CONFIGS = [
    ("mistral-large-3",       AC_BASE,      "mistral-large-3-675b-instruct-2512", "classic", {}),
    ("gemma-3-27b",           AC_BASE,      "gemma-3-27b-it",                      "classic", {}),
    ("gpt-oss-120b",          AC_BASE,      "openai-gpt-oss-120b",                 "classic", {}),
    ("gpt-5.4-mini eff=low",  OAI_PASSTHRU, "gpt-5.4-mini",  "gpt5", {"reasoning_effort": "low"}),
    ("gpt-5.4-mini eff=none", OAI_PASSTHRU, "gpt-5.4-mini",  "gpt5", {}),
]

PROMPTS = [
    ("fact",    "Was ist Photosynthese? Antworte in genau einem Satz."),
    ("explain", "Erkläre Bruchrechnung für die 7. Klasse in 3-4 kurzen Sätzen."),
    ("list",    "Nenne 3 Lerntipps fürs Vokabellernen, je ein kurzer Satz."),
    ("create",  "Schreibe eine Quizfrage zur Photosynthese mit 4 Optionen (A-D) und markiere die richtige."),
]

BASE_MAX_TOKENS = 400
TIMEOUT_S = 60
MAX_RETRIES = 1
RETRY_BACKOFF_S = 3.0
EMBED_RUNS = 5

# Marker, die zeigen, dass Reasoning IN den sichtbaren content geleakt ist.
LEAK_MARKERS = ["<think", "</think", "<reasoning", "</reasoning",
                "<|channel|>", "<|message|>", "<|start|>", "<|end|>",
                "assistantfinal", "<|assistant|>"]


def _uniq() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


def _find_leak(content: str) -> str:
    low = content.lower()
    for m in LEAK_MARKERS:
        if m in low:
            return m
    return ""


async def _chat_once(client: httpx.AsyncClient, key: str, cfg: tuple, prompt: str) -> dict:
    label, base, model, style, extra = cfg
    user = f"{prompt} (ID: {_uniq()})"
    body: dict = {"model": model,
                  "messages": [{"role": "system", "content": SYSTEM},
                               {"role": "user", "content": user}]}
    if style == "gpt5":
        body["verbosity"] = "medium"
        body.update(extra)  # optional reasoning_effort
    else:
        body["max_tokens"] = _shape_max_tokens(model, BASE_MAX_TOKENS)
        body["temperature"] = 0.4

    last = ""
    for attempt in range(MAX_RETRIES + 1):
        t0 = time.perf_counter()
        try:
            r = await client.post(f"{base}/chat/completions",
                                  headers={"X-API-KEY": key, "Content-Type": "application/json"},
                                  json=body, timeout=TIMEOUT_S)
            dur = round((time.perf_counter() - t0) * 1000)
            if r.status_code != 200:
                last = f"HTTP {r.status_code}: {r.text[:80]}"
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF_S)
                    continue
                return {"ok": False, "label": label, "err": last, "latency_ms": dur}
            d = r.json()
            ch = (d.get("choices") or [{}])[0]
            msg = ch.get("message") or {}
            content = (msg.get("content") or "").strip()
            reasoning = msg.get("reasoning_content") or ""
            usage = d.get("usage") or {}
            return {
                "ok": bool(content), "label": label, "latency_ms": dur,
                "finish": ch.get("finish_reason"),
                "ct": usage.get("completion_tokens"), "pt": usage.get("prompt_tokens"),
                "content_chars": len(content), "reasoning_chars": len(reasoning),
                "leak": _find_leak(content), "preview": content[:90],
            }
        except Exception as e:
            dur = round((time.perf_counter() - t0) * 1000)
            last = f"{type(e).__name__}: {str(e)[:80]}"
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF_S)
                continue
            return {"ok": False, "label": label, "err": last, "latency_ms": dur}
    return {"ok": False, "label": label, "err": last or "exhausted", "latency_ms": 0}


async def bench_chat(key: str) -> dict:
    print("\n" + "=" * 84)
    print("  1+2) CHAT — Reasoning-Leak + Speed (STRIKT SERIELL)")
    print("=" * 84)
    agg: dict = {label: [] for label, *_ in CHAT_CONFIGS}
    async with httpx.AsyncClient() as client:
        for cfg in CHAT_CONFIGS:
            label = cfg[0]
            print(f"\n  --- {label}  [{cfg[2]}] ---")
            for pid, prompt in PROMPTS:
                res = await _chat_once(client, key, cfg, prompt)
                agg[label].append(res)
                if res["ok"]:
                    leak = f"  LEAK={res['leak']!r}" if res["leak"] else ""
                    print(f"    [{pid:8s}] {res['latency_ms']:>6}ms  ct={res.get('ct')}  "
                          f"out={res['content_chars']}ch  rsn_field={res['reasoning_chars']}ch{leak}")
                else:
                    print(f"    [{pid:8s}] FAIL  {res.get('err')}")
    return agg


def summarize_chat(agg: dict) -> None:
    print("\n" + "-" * 84)
    print("  SPEED-VERGLEICH (nur erfolgreiche Calls)")
    print("-" * 84)
    h = f"  {'Konfiguration':22s} | {'ok':>4s} | {'median':>7s} | {'mean':>7s} | {'min':>6s} | {'max':>6s} | {'out⌀':>5s}"
    print(h)
    print("  " + "-" * (len(h) - 2))
    for label, rows in agg.items():
        ok = [r for r in rows if r["ok"]]
        if not ok:
            print(f"  {label:22s} | {0:>4} | (alle fehlgeschlagen)")
            continue
        lat = [r["latency_ms"] for r in ok]
        outc = [r["content_chars"] for r in ok]
        print(f"  {label:22s} | {len(ok):>4} | {int(statistics.median(lat)):>6}ms | "
              f"{int(statistics.mean(lat)):>6}ms | {min(lat):>5}ms | {max(lat):>5}ms | "
              f"{int(statistics.mean(outc)):>5}")

    print("\n" + "-" * 84)
    print("  REASONING-ANALYSE — müssen wir filtern?")
    print("-" * 84)
    for label, rows in agg.items():
        ok = [r for r in rows if r["ok"]]
        if not ok:
            print(f"  {label:22s} : keine Daten")
            continue
        max_rsn = max(r["reasoning_chars"] for r in ok)
        leaks = [r for r in ok if r["leak"]]
        if leaks:
            verdict = (f"⚠️  LEAK im sichtbaren Text ({len(leaks)}/{len(ok)} Calls, "
                       f"z.B. {leaks[0]['leak']!r}) → FILTER NÖTIG")
        elif max_rsn > 0:
            verdict = (f"reasoning_content-Feld vorhanden (max {max_rsn}ch) → "
                       f"App liest nur .content → AUTOMATISCH gefiltert, kein Eingriff")
        else:
            verdict = "sauber — kein Reasoning-Output, kein Filter nötig"
        print(f"  {label:22s} : {verdict}")


# ── 3) Embedding-Speed ────────────────────────────────────────────────
async def _embed_ac(key: str, text: str) -> tuple[int, int]:
    body = {"model": "e5-mistral-7b-instruct", "input": [text]}
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=60) as cli:
        r = await cli.post(f"{AC_BASE}/embeddings",
                           headers={"X-API-KEY": key, "Content-Type": "application/json"},
                           json=body)
    dur = round((time.perf_counter() - t0) * 1000)
    if r.status_code != 200:
        return dur, 0
    emb = (r.json().get("data") or [{}])[0].get("embedding") or []
    return dur, len(emb)


async def bench_embeddings(key: str) -> None:
    print("\n" + "=" * 84)
    print("  3) EMBEDDING-SPEED (seriell, NUR Messung — KEIN DB-Write)")
    print("=" * 84)
    texts = [f"Photosynthese ist ein biologischer Prozess Nr. {i}." for i in range(EMBED_RUNS)]

    # a) AcademicCloud e5-mistral
    ac_lat, ac_dim = [], 0
    for t in texts:
        dur, dim = await _embed_ac(key, t)
        ac_lat.append(dur)
        ac_dim = dim or ac_dim
    print(f"  e5-mistral-7b-instruct (AcademicCloud): "
          f"median {int(statistics.median(ac_lat))}ms  mean {int(statistics.mean(ac_lat))}ms  "
          f"(min {min(ac_lat)} / max {max(ac_lat)})  dim={ac_dim}")

    # b) OpenAI text-embedding-3-small (DB-Pfad-Referenz)
    okey = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not okey:
        print("  text-embedding-3-small (OpenAI): SKIP — kein OPENAI_API_KEY")
        return
    base = (os.getenv("OPENAI_BASE_URL") or "").strip().rstrip("/") or "https://api.openai.com/v1"
    c = AsyncOpenAI(api_key=okey, base_url=base, timeout=60, max_retries=0)
    oa_lat, oa_dim = [], 0
    try:
        for t in texts:
            t0 = time.perf_counter()
            r = await c.embeddings.create(model="text-embedding-3-small", input=t)
            oa_lat.append(round((time.perf_counter() - t0) * 1000))
            oa_dim = len(r.data[0].embedding)
    finally:
        await c.close()
    print(f"  text-embedding-3-small (OpenAI):        "
          f"median {int(statistics.median(oa_lat))}ms  mean {int(statistics.mean(oa_lat))}ms  "
          f"(min {min(oa_lat)} / max {max(oa_lat)})  dim={oa_dim}")
    print("\n  Hinweis: e5-mistral wurde NUR gemessen. Die RAG-DB bleibt 1536-dim/OpenAI.")


async def main() -> None:
    key = (os.getenv(KEY_VAR) or "").strip()
    print("=" * 84)
    print("  AcademicCloud-Bench × B-API STAGING")
    print(f"  AC:   {AC_BASE}")
    print(f"  OAI:  {OAI_PASSTHRU}")
    if not key:
        print(f"\nERROR: {KEY_VAR} nicht gesetzt.")
        sys.exit(1)
    print(f"  key:  {key[:6]}*** (len {len(key)})")
    print(f"  Prompts: {len(PROMPTS)}  ·  Konfigurationen: {len(CHAT_CONFIGS)}  ·  "
          f"Embedding-Runs: {EMBED_RUNS}")

    agg = await bench_chat(key)
    summarize_chat(agg)
    await bench_embeddings(key)

    print("\n" + "=" * 84)
    print("  FAZIT")
    print("=" * 84)
    print("  - Default-Chatmodell AcademicCloud ist jetzt mistral-large-3 (Code gesetzt).")
    print("  - Reasoning-Filter: siehe Tabelle oben (mistral/gemma erwartet sauber;")
    print("    gpt-oss-120b liefert ein separates reasoning_content-Feld → App ignoriert es).")
    print("  - Speed: AcademicCloud-Direktmodelle vs. gpt-5.4-mini (eff=low/none) siehe Tabelle.")


if __name__ == "__main__":
    asyncio.run(main())
