"""Benchmark: 5 B-API-AcademicCloud-Modelle × 14 Schüler-Intents.

Misst Latenz, Token-Verbrauch und Output-Charakteristik für jedes
(Modell, Intent)-Paar. Schreibt JSON-Resultate nach
``backend/scripts/bench_results/<timestamp>.json`` und gibt eine
Markdown-Vergleichstabelle auf stdout aus.

Aufruf:
    cd backend
    PYTHONIOENCODING=utf-8 B_API_KEY_PROD=... \\
      python scripts/bench_5_models_schueler.py

WICHTIG: jede User-Message bekommt einen unique Anfrage-ID-Suffix,
damit der serverseitige B-API-Cache umgangen wird — sonst messen wir
nur Cache-Hits (Latenz < 50ms statt der echten 1-30s).

Erwartete Laufzeit: 10-30 Minuten (seriell, weil der B-API-Key nur
1-2 parallele Slots akzeptiert, siehe probe_b_api_ratelimit_v2.py).
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import statistics
import string
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

# Repo root → import path so we can re-use llm_provider's profile shaping
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.llm_provider import _shape_max_tokens, model_profile  # noqa: E402

B_API_BASE = "https://b-api.prod.openeduhub.net/api/v1/llm/academiccloud"
KEY_VAR = "B_API_KEY_PROD"

MODELS = [
    "openai-gpt-oss-120b",
    "glm-4.7",
    "mistral-large-3-675b-instruct-2512",
    "qwen3.5-122b-a10b",
    "qwen3.5-397b-a17b",
]

# Schüler-System-Prompt — kurz gehalten, gleicher Kontext für alle Calls.
SYSTEM_PROMPT = (
    "Du bist Boerdi, ein freundlicher Lerncoach für Schüler:innen auf der "
    "Plattform WirLernenOnline (WLO). Du duzt, antwortest knapp und in einfacher "
    "Sprache. Du kannst Lernmaterial vorschlagen, Fakten erklären, Lernpläne "
    "erstellen und Quiz/Arbeitsblätter generieren. Bei Feedback nimmst du es "
    "ernst. Antworte in 2-4 Sätzen wenn nicht ausdrücklich mehr verlangt ist."
)

# 14 Intents × 1 Schüler-Prompt — Schreibstil bewusst etwas casual.
INTENTS = [
    ("INT-W-01", "WLO kennenlernen",        "Hi, ich bin neu hier. Was kann WLO eigentlich?"),
    ("INT-W-02", "Soft Probing",            "Hallo. Ich brauch Hilfe bei was, weiß aber nicht so genau."),
    ("INT-W-03a","Themenseite entdecken",   "Gibt es eine Übersicht zum Klimawandel?"),
    ("INT-W-03b","Material suchen",         "Brauche Übungsmaterial zur Bruchrechnung für Klasse 7."),
    ("INT-W-03c","Lerninhalt suchen",       "Hast du ein Erklärvideo zur Photosynthese?"),
    ("INT-W-04", "Feedback",                "Das vorhin war doof, hat mir gar nicht geholfen."),
    ("INT-W-05", "Routing-Redaktion",       "Ich glaub im Material zur Mitose ist ein Fehler."),
    ("INT-W-06", "Faktenfragen",            "Was ist Photosynthese?"),
    ("INT-W-07", "Material herunterladen",  "Wie kann ich das Arbeitsblatt zum Drucken runterladen?"),
    ("INT-W-08", "Inhalts-Evaluation",      "Ist dieses Mathevideo von Lukas wirklich gut für Klasse 8?"),
    ("INT-W-09", "Reporting",               "Wie viele Materialien hat WLO eigentlich zur Bruchrechnung?"),
    ("INT-W-10", "Unterrichtsplanung",      "Mach mir bitte einen Lernplan für meine Mathe-Klausur in einer Woche, Thema Bruchrechnung."),
    ("INT-W-11", "Inhalt erstellen",        "Erstell mir ein Quiz zu Bruchrechnung für Klasse 7 mit 5 Fragen."),
    ("INT-W-12", "Canvas-Edit",             "Mach das Quiz einfacher, das ist zu schwer."),
]

# Caller-requested base budget — was BadBoerdi typisch in chat_completions
# fragen würde (mittel-lang Antwort). Per-Modell shaped via _shape_max_tokens.
BASE_MAX_TOKENS = 400

CONCURRENCY = 1   # B-API liefert spurious 401er bei mehreren parallelen
                   # Calls aus derselben Session — daher seriell.
TIMEOUT_S = 90
MAX_RETRIES = 2   # Bei 401 / RemoteProtocolError zwei Mal nachfassen.
RETRY_BACKOFF_S = 3.0


def _unique_suffix() -> str:
    """Random suffix to defeat the B-API server-side response cache.

    Without this, identical User-Messages return cached responses in
    sub-50ms — completely defeating the latency benchmark.
    """
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


async def _call(client: httpx.AsyncClient, key: str, model: str, intent_id: str,
                intent_label: str, user_msg: str) -> dict:
    """Einzel-Call mit Retries für transiente B-API-Fehler.

    Liefert Result-Dict mit Latenz, Tokens, Content-Snippet.
    """
    shaped = _shape_max_tokens(model, BASE_MAX_TOKENS)
    # Append unique invisible token to defeat the server cache.
    user_with_id = f"{user_msg} (Anfrage-ID: {_unique_suffix()})"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_with_id},
        ],
        "max_tokens": shaped,
        "temperature": 0.4,
    }
    last_err = ""
    for attempt in range(MAX_RETRIES + 1):
        t0 = time.perf_counter()
        try:
            r = await client.post(
                f"{B_API_BASE}/chat/completions",
                headers={"X-API-KEY": key, "Content-Type": "application/json"},
                json=body,
                timeout=TIMEOUT_S,
            )
            dur_ms = round((time.perf_counter() - t0) * 1000)
            ok = r.status_code == 200
            # Spurious 401 from B-API under burst load → retry.
            if not ok and r.status_code == 401 and attempt < MAX_RETRIES:
                last_err = f"transient 401 attempt={attempt}"
                await asyncio.sleep(RETRY_BACKOFF_S * (attempt + 1))
                continue
            if not ok:
                return {
                    "model": model, "intent_id": intent_id, "intent_label": intent_label,
                    "ok": False, "status": r.status_code, "latency_ms": dur_ms,
                    "error": r.text[:200] or last_err,
                }
            d = r.json()
            choice = d.get("choices", [{}])[0]
            msg = choice.get("message", {})
            content = (msg.get("content") or "").strip()
            reasoning = msg.get("reasoning_content") or ""
            usage = d.get("usage") or {}
            finish = choice.get("finish_reason", "?")
            return {
                "model": model,
                "intent_id": intent_id,
                "intent_label": intent_label,
                "ok": True,
                "status": 200,
                "latency_ms": dur_ms,
                "finish_reason": finish,
                "max_tokens_sent": shaped,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "reasoning_chars": len(reasoning),
                "content_chars": len(content),
                "content_preview": content[:240],
                "user_msg": user_msg,
            }
        except (httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ConnectError) as e:
            dur_ms = round((time.perf_counter() - t0) * 1000)
            last_err = f"{type(e).__name__}: {e}"
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF_S * (attempt + 1))
                continue
            return {
                "model": model, "intent_id": intent_id, "intent_label": intent_label,
                "ok": False, "status": 0, "latency_ms": dur_ms,
                "error": last_err,
            }
        except Exception as e:  # pragma: no cover — defensive
            dur_ms = round((time.perf_counter() - t0) * 1000)
            return {
                "model": model, "intent_id": intent_id, "intent_label": intent_label,
                "ok": False, "status": 0, "latency_ms": dur_ms,
                "error": f"{type(e).__name__}: {e}",
            }
    # Should be unreachable — retry loop always returns or continues.
    return {
        "model": model, "intent_id": intent_id, "intent_label": intent_label,
        "ok": False, "status": 0, "latency_ms": 0,
        "error": last_err or "exhausted retries",
    }


async def _run() -> list[dict]:
    key = os.environ[KEY_VAR]
    sem = asyncio.Semaphore(CONCURRENCY)
    results: list[dict] = []

    async with httpx.AsyncClient() as client:
        async def _bounded(model: str, intent_id: str, label: str, msg: str):
            async with sem:
                res = await _call(client, key, model, intent_id, label, msg)
                tag = "OK " if res["ok"] else "ERR"
                content_len = res.get("content_chars", 0) if res["ok"] else 0
                tokens = res.get("completion_tokens", "?") if res["ok"] else "—"
                print(f"  [{tag}] {model:42s} {intent_id:8s}  "
                      f"{res['latency_ms']:>5}ms  ct={tokens:>4}  out={content_len:>4}ch",
                      flush=True)
                results.append(res)

        tasks = [
            _bounded(model, iid, lbl, msg)
            for model in MODELS
            for iid, lbl, msg in INTENTS
        ]
        print(f"Running {len(tasks)} calls (concurrency={CONCURRENCY})...")
        await asyncio.gather(*tasks)
    return results


def _aggregate(results: list[dict]) -> dict:
    """Per-Modell Aggregat: median/mean Latenz, Token, Erfolgsquote."""
    by_model: dict[str, dict] = {}
    for m in MODELS:
        rows = [r for r in results if r["model"] == m]
        ok_rows = [r for r in rows if r["ok"]]
        if not ok_rows:
            by_model[m] = {"ok_count": 0, "total": len(rows)}
            continue
        latencies = [r["latency_ms"] for r in ok_rows]
        ct = [r.get("completion_tokens") or 0 for r in ok_rows]
        out_chars = [r.get("content_chars") or 0 for r in ok_rows]
        empties = sum(1 for r in ok_rows if (r.get("content_chars") or 0) < 5)
        truncs = sum(1 for r in ok_rows if r.get("finish_reason") == "length")
        by_model[m] = {
            "ok_count": len(ok_rows),
            "total": len(rows),
            "latency_median_ms": int(statistics.median(latencies)),
            "latency_mean_ms": int(statistics.mean(latencies)),
            "latency_min_ms": min(latencies),
            "latency_max_ms": max(latencies),
            "completion_tokens_median": int(statistics.median(ct)),
            "completion_tokens_total": sum(ct),
            "out_chars_median": int(statistics.median(out_chars)),
            "out_chars_per_token_avg": (sum(out_chars) / sum(ct)) if sum(ct) else 0,
            "empty_responses": empties,
            "truncated_at_length": truncs,
            "profile": model_profile(m),
        }
    return by_model


def _print_table(agg: dict) -> None:
    print("\n" + "=" * 100)
    print("VERGLEICHS-TABELLE (14 Intents × Schüler-Prompt)")
    print("=" * 100)
    h = (
        f"{'Modell':40s} | {'OK/14':>6s} | {'med ms':>7s} | {'mean ms':>8s} | "
        f"{'CT med':>7s} | {'out med':>8s} | {'ch/tok':>7s} | {'empty':>5s} | {'trunc':>5s}"
    )
    print(h)
    print("-" * len(h))
    for m, s in agg.items():
        if s.get("ok_count", 0) == 0:
            print(f"{m:40s} | {s.get('ok_count',0)}/{s.get('total','?')}  | (alle Calls fehlgeschlagen)")
            continue
        print(
            f"{m:40s} | "
            f"{s['ok_count']:>3d}/{s['total']:<3d} | "
            f"{s['latency_median_ms']:>7d} | "
            f"{s['latency_mean_ms']:>8d} | "
            f"{s['completion_tokens_median']:>7d} | "
            f"{s['out_chars_median']:>8d} | "
            f"{s['out_chars_per_token_avg']:>7.2f} | "
            f"{s['empty_responses']:>5d} | "
            f"{s['truncated_at_length']:>5d}"
        )
    print()
    print("Spalten:")
    print("  OK/14    : Erfolgreiche Calls von 14 Intents")
    print("  med ms   : Median-Latenz pro Call")
    print("  mean ms  : Mittel-Latenz pro Call")
    print("  CT med   : Median completion_tokens (inkl. Reasoning bei Qwen)")
    print("  out med  : Median sichtbare Antwort-Länge in Zeichen")
    print("  ch/tok   : Output-Effizienz (Zeichen pro completion-Token)")
    print("  empty    : Calls mit <5 Zeichen Output (Reasoning hat Budget gefressen)")
    print("  trunc    : Calls mit finish_reason=length (Budget zu knapp)")


def _save_results(results: list[dict], agg: dict) -> Path:
    out_dir = Path(__file__).resolve().parent / "bench_results"
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    fp = out_dir / f"5models-schueler-{ts}.json"
    fp.write_text(
        json.dumps(
            {
                "timestamp": ts,
                "endpoint": B_API_BASE,
                "models": MODELS,
                "intents": [{"id": i, "label": l, "user_msg": m} for i, l, m in INTENTS],
                "base_max_tokens": BASE_MAX_TOKENS,
                "results": results,
                "aggregates": agg,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return fp


def main() -> None:
    if not os.environ.get(KEY_VAR):
        print(f"ERROR: {KEY_VAR} not set in environment")
        sys.exit(1)
    print(f"Endpoint: {B_API_BASE}")
    print(f"Modelle:  {len(MODELS)}")
    print(f"Intents:  {len(INTENTS)}")
    print(f"Calls:    {len(MODELS) * len(INTENTS)}")
    print()
    results = asyncio.run(_run())
    agg = _aggregate(results)
    _print_table(agg)
    fp = _save_results(results, agg)
    print(f"\nDetails geschrieben nach: {fp}")


if __name__ == "__main__":
    main()
