"""Scan ALLER AcademicCloud-Chatmodelle auf "Thinking"/Reasoning-Output.

Ziel: herausfinden, welche Modelle Reasoning mitliefern und WIE — damit wir
wissen, was (falls überhaupt) gefiltert werden muss, wenn die App ein Modell
nutzt.

Pro Modell wird EIN reasoning-induzierender Prompt (Proportional-Aufgabe)
geschickt und die VOLLE Antwort inspiziert:

  * Zusatz-Felder im message-Objekt (reasoning_content / reasoning / thinking …)
    → die App liest NUR message.content, ein separates Feld wird also
    automatisch ignoriert (kein Filter nötig).
  * Thinking-Marker IM sichtbaren content (<think>…</think>, <|channel|>analysis…
    harmony-Marker, ◁think▷ u.a.) → würde beim User landen → FILTER NÖTIG.
  * Leere Antwort bei finish_reason=length → verstecktes Reasoning hat das
    Budget gefressen (Modell für interaktiven Chat unbrauchbar).

Strikt SERIELL (AcademicCloud erlaubt keine parallelen Calls). Embedding-
Modelle werden übersprungen. Key aus B_API_KEY_STAGING; App-B_API_KEY unangetastet.

Aufruf (aus backend/):
    python scripts/scan_thinking_staging.py
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import string
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

B_API_BASE = "https://b-api.staging.openeduhub.net/api/v1/llm"
AC_BASE = f"{B_API_BASE}/academiccloud"
KEY_VAR = "B_API_KEY_STAGING"

# Reasoning-induzierende Aufgabe: Proportionalrechnung mit kurzer Begründung.
# Triggert bei Reasoning-Modellen "Thinking", lässt Direkt-Modelle aber knapp
# antworten.
SYSTEM = "Du bist ein knapper Lerncoach. Antworte auf Deutsch."
PROMPT = ("Ein Geschäft verkauft 3 Stifte für 2,40 Euro. Wie viel kosten 7 Stifte? "
          "Nenne kurz den Rechenweg und das Ergebnis.")

MAX_TOKENS = 2500   # großzügig, damit Thinking + Antwort sichtbar werden
TIMEOUT_S = 90
MAX_RETRIES = 1
RETRY_BACKOFF_S = 3.0

# Modelle, die KEINE Chat-Modelle sind (Embeddings etc.) → überspringen.
SKIP_SUBSTRINGS = ("e5-", "embed", "bge", "jina", "rerank")

# Marker, die zeigen, dass Reasoning IM sichtbaren content steckt.
THINK_MARKERS = [
    "<think", "</think", "<thinking", "</thinking",
    "<reason", "</reason", "<reasoning", "</reasoning",
    "<|channel|>", "<|message|>", "<|start|>", "<|end|>", "<|assistant|>",
    "assistantfinal", "◁think▷", "◁/think▷", "[think]", "[/think]",
    "analysis<|", "<|im_start|>",
]
# message-Felder, die KEIN normaler Chat-Output sind (= Reasoning-Seitenkanal).
KNOWN_MSG_KEYS = {"role", "content", "tool_calls", "function_call", "refusal",
                  "annotations", "audio"}


def _uniq() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


def _find_markers(text: str) -> list[str]:
    low = text.lower()
    return [m for m in THINK_MARKERS if m.lower() in low]


async def _models(key: str) -> list[str]:
    async with httpx.AsyncClient(timeout=30) as cli:
        r = await cli.get(f"{AC_BASE}/models", headers={"X-API-KEY": key})
    r.raise_for_status()
    data = r.json()
    items = data if isinstance(data, list) else data.get("data", [])
    return sorted((m["id"] if isinstance(m, dict) else str(m)) for m in items)


async def _scan_one(client: httpx.AsyncClient, key: str, model: str) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": f"{PROMPT} (ID: {_uniq()})"}],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.3,
    }
    last = ""
    for attempt in range(MAX_RETRIES + 1):
        t0 = time.perf_counter()
        try:
            r = await client.post(f"{AC_BASE}/chat/completions",
                                  headers={"X-API-KEY": key, "Content-Type": "application/json"},
                                  json=body, timeout=TIMEOUT_S)
            dur = round((time.perf_counter() - t0) * 1000)
            if r.status_code != 200:
                last = f"HTTP {r.status_code}: {r.text[:80]}"
                if attempt < MAX_RETRIES and r.status_code in (401, 429, 500, 502, 503):
                    await asyncio.sleep(RETRY_BACKOFF_S)
                    continue
                return {"model": model, "ok": False, "reachable": False,
                        "err": last, "latency_ms": dur}
            d = r.json()
            ch = (d.get("choices") or [{}])[0]
            msg = ch.get("message") or {}
            content = msg.get("content") or ""
            reasoning_field = (msg.get("reasoning_content") or msg.get("reasoning")
                               or msg.get("thinking") or "")
            extra_keys = [k for k in msg.keys() if k not in KNOWN_MSG_KEYS]
            usage = d.get("usage") or {}
            markers = _find_markers(content)
            return {
                "model": model, "ok": True, "reachable": True,
                "latency_ms": dur, "finish": ch.get("finish_reason"),
                "ct": usage.get("completion_tokens"),
                "content_chars": len(content.strip()),
                "reasoning_field_chars": len(reasoning_field),
                "extra_keys": extra_keys,
                "leak_markers": markers,
                "content_head": content.strip()[:120],
            }
        except Exception as e:
            dur = round((time.perf_counter() - t0) * 1000)
            last = f"{type(e).__name__}: {str(e)[:80]}"
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF_S)
                continue
            return {"model": model, "ok": False, "reachable": False,
                    "err": last, "latency_ms": dur}
    return {"model": model, "ok": False, "reachable": False, "err": last or "exhausted"}


def _categorize(r: dict) -> str:
    if not r.get("reachable"):
        return "UNREACHABLE"
    if r["leak_markers"]:
        return "LEAK_IN_CONTENT"
    if r["content_chars"] == 0 and r.get("finish") == "length":
        return "EMPTY_HIDDEN_REASONING"
    if r["content_chars"] == 0:
        return "EMPTY_OTHER"
    if r["reasoning_field_chars"] > 0 or r["extra_keys"]:
        return "SEPARATE_FIELD"
    return "CLEAN"


CAT_VERDICT = {
    "CLEAN":                  "sauber — kein Reasoning im Output, kein Filter nötig",
    "SEPARATE_FIELD":         "Reasoning in separatem Feld → App liest nur .content → AUTO-ignoriert",
    "LEAK_IN_CONTENT":        "⚠️  Thinking IM sichtbaren Text → FILTER NÖTIG, falls dieses Modell genutzt wird",
    "EMPTY_HIDDEN_REASONING": "✋ leere Antwort (Reasoning fraß Budget) → für Chat unbrauchbar",
    "EMPTY_OTHER":            "leere Antwort (anderer Grund)",
    "UNREACHABLE":            "nicht erreichbar (Timeout/Fehler)",
}


async def main() -> None:
    key = (os.getenv(KEY_VAR) or "").strip()
    print("=" * 88)
    print("  THINKING/REASONING-SCAN — ALLE AcademicCloud-Chatmodelle × B-API STAGING")
    if not key:
        print(f"\nERROR: {KEY_VAR} nicht gesetzt.")
        sys.exit(1)
    print(f"  key: {key[:6]}*** · Prompt: Proportionalrechnung · max_tokens={MAX_TOKENS}")
    print("=" * 88)

    all_models = await _models(key)
    chat_models = [m for m in all_models if not any(s in m.lower() for s in SKIP_SUBSTRINGS)]
    skipped = [m for m in all_models if m not in chat_models]
    print(f"\n  Katalog: {len(all_models)} Modelle · Chat-Scan: {len(chat_models)} · "
          f"übersprungen (Embedding etc.): {skipped}")
    print(f"  (seriell — Reasoning-Modelle können je 20-90s dauern)\n")

    results: list[dict] = []
    async with httpx.AsyncClient() as client:
        for i, m in enumerate(chat_models, 1):
            r = await _scan_one(client, key, m)
            r["category"] = _categorize(r)
            results.append(r)
            if r.get("reachable"):
                mk = f"  MARKER={r['leak_markers']}" if r["leak_markers"] else ""
                xk = f"  extra_keys={r['extra_keys']}" if r["extra_keys"] else ""
                print(f"  [{i:>2}/{len(chat_models)}] {m:34s} {r['category']:22s} "
                      f"{r['latency_ms']:>6}ms finish={r.get('finish'):<6} "
                      f"out={r['content_chars']:>4}ch rsn_field={r['reasoning_field_chars']:>4}ch"
                      f"{xk}{mk}", flush=True)
                if r["leak_markers"] or (r["content_chars"] and r["category"] != "CLEAN"):
                    print(f"        head: {r['content_head']!r}", flush=True)
            else:
                print(f"  [{i:>2}/{len(chat_models)}] {m:34s} {r['category']:22s} "
                      f"{r.get('err')}", flush=True)

    # ── Zusammenfassung gruppiert nach Kategorie ──
    print("\n" + "=" * 88)
    print("  ZUSAMMENFASSUNG — was müssen wir filtern?")
    print("=" * 88)
    order = ["LEAK_IN_CONTENT", "EMPTY_HIDDEN_REASONING", "SEPARATE_FIELD",
             "CLEAN", "EMPTY_OTHER", "UNREACHABLE"]
    for cat in order:
        members = [r["model"] for r in results if r["category"] == cat]
        if not members:
            continue
        print(f"\n  {cat}  — {CAT_VERDICT[cat]}")
        for m in members:
            print(f"      - {m}")

    # JSON-Detail speichern
    out_dir = Path(__file__).resolve().parent / "bench_results"
    out_dir.mkdir(exist_ok=True)
    # Zeitstempel via Umgebungssicht (Date.now darf nicht hart importiert werden) —
    # datetime.now ist im Skript ok (kein Workflow-Resume-Kontext).
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    fp = out_dir / f"thinking-scan-{ts}.json"
    fp.write_text(json.dumps({"endpoint": AC_BASE, "prompt": PROMPT,
                              "max_tokens": MAX_TOKENS, "results": results},
                             indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  Detail-JSON: {fp}")

    leaks = [r["model"] for r in results if r["category"] == "LEAK_IN_CONTENT"]
    print("\n  → FAZIT: " + (
        f"Diese Modelle leaken Thinking in den sichtbaren Text und bräuchten einen "
        f"Filter, falls genutzt: {leaks}" if leaks else
        "KEIN Modell leakt Thinking in den sichtbaren content. Separat-Feld-Modelle "
        "werden von der App automatisch ignoriert. Für den Default mistral-large-3 "
        "ist nichts zu tun."))


if __name__ == "__main__":
    asyncio.run(main())
