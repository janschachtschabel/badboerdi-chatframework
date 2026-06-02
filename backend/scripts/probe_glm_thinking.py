"""Gezielt prüfen: KÖNNEN glm-4.7 / gemma-3 / mistral-3 Reasoning liefern —
und WO landet es (separates Feld vs. <think>-Tag im content)?

Der breite Scan testete nur einen LEICHTEN Prompt mit Default-Parametern
(= Default-Verhalten). Hier provozieren wir Reasoning aktiv:
  * schwerer, mehrstufiger Prompt
  * explizite Thinking-Schalter (vLLM/GLM: chat_template_kwargs.enable_thinking,
    sowie thinking / reasoning_effort als Fallback-Konventionen)

Für jeden Fall: finish, ct, len(content), len(reasoning), len(reasoning_content),
Leak-Marker im content. So sehen wir, ob ein Modell unter Last/Schaltung doch
<think> in den sichtbaren Text kippt (→ Filter-Relevanz).

Seriell. Key aus B_API_KEY_STAGING. App-B_API_KEY unangetastet.
Aufruf (aus backend/):  python scripts/probe_glm_thinking.py
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

# Schwerer, mehrstufiger Prompt — provoziert Reasoning bei fähigen Modellen.
HARD = ("In einem Korb liegen rote und blaue Kugeln, zusammen 20 Stück. "
        "Es sind viermal so viele rote wie blaue Kugeln, minus 5. "
        "Wie viele rote und blaue Kugeln sind es? Denke Schritt für Schritt "
        "und nenne den vollständigen Rechenweg.")

THINK_MARKERS = ["<think", "</think", "<thinking", "<reason", "<|channel|>",
                 "<|message|>", "assistantfinal", "◁think▷"]

# (Label, model, extra_body)
CASES = [
    ("glm-4.7  | default",            "glm-4.7", {}),
    ("glm-4.7  | enable_thinking",    "glm-4.7", {"chat_template_kwargs": {"enable_thinking": True}}),
    ("glm-4.7  | thinking=true",      "glm-4.7", {"thinking": True}),
    ("glm-4.7  | reasoning_effort=hi","glm-4.7", {"reasoning_effort": "high"}),
    ("gemma-3  | enable_thinking",    "gemma-3-27b-it", {"chat_template_kwargs": {"enable_thinking": True}}),
    ("mistral-3| enable_thinking",    "mistral-large-3-675b-instruct-2512", {"chat_template_kwargs": {"enable_thinking": True}}),
]


def _uniq() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


async def _call(client, key, model, extra):
    body = {"model": model,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": f"{HARD} (ID: {_uniq()})"}],
            "max_tokens": 2500, "temperature": 0.3}
    body.update(extra)
    t0 = time.perf_counter()
    try:
        r = await client.post(f"{AC_BASE}/chat/completions",
                              headers={"X-API-KEY": key, "Content-Type": "application/json"},
                              json=body, timeout=90)
    except Exception as e:
        return {"ok": False, "err": f"{type(e).__name__}: {str(e)[:90]}",
                "ms": round((time.perf_counter() - t0) * 1000)}
    dur = round((time.perf_counter() - t0) * 1000)
    if r.status_code != 200:
        return {"ok": False, "status": r.status_code, "body": r.text[:140], "ms": dur}
    d = r.json()
    ch = (d.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    content = msg.get("content") or ""
    low = content.lower()
    return {"ok": True, "ms": dur, "finish": ch.get("finish_reason"),
            "ct": (d.get("usage") or {}).get("completion_tokens"),
            "content_len": len(content),
            "reasoning_len": len(msg.get("reasoning") or ""),
            "reasoning_content_len": len(msg.get("reasoning_content") or ""),
            "markers": [m for m in THINK_MARKERS if m in low],
            "content_head": content[:140], }


async def main():
    key = (os.getenv(KEY_VAR) or "").strip()
    if not key:
        print(f"ERROR: {KEY_VAR} nicht gesetzt."); sys.exit(1)
    print("=" * 84)
    print("  KANN reasoning erzwungen werden? glm-4.7 / gemma-3 / mistral-3 (schwerer Prompt)")
    print("=" * 84)
    async with httpx.AsyncClient() as client:
        for label, model, extra in CASES:
            print(f"\n--- {label} ---")
            r = await _call(client, key, model, extra)
            if not r["ok"]:
                if r.get("status"):
                    print(f"  HTTP {r['status']}  {r['body']!r}  ({r['ms']}ms)  "
                          f"→ Parameter evtl. nicht akzeptiert")
                else:
                    print(f"  FEHLER {r.get('err')}  ({r['ms']}ms)")
                continue
            print(f"  {r['ms']:>6}ms  finish={r['finish']}  ct={r['ct']}")
            print(f"  content={r['content_len']}ch  reasoning={r['reasoning_len']}ch  "
                  f"reasoning_content={r['reasoning_content_len']}ch  "
                  f"marker_im_content={r['markers'] or 'KEINE'}")
            print(f"  content[:140]: {r['content_head']!r}")

    print("\n" + "=" * 84)
    print("  Lesart: reasoning/reasoning_content > 0  → Reasoning im SEPARATEN Feld (App ignoriert)")
    print("          marker_im_content gesetzt        → Reasoning im SICHTBAREN Text → FILTER nötig")
    print("          beides 0 / keine Marker          → echtes Direkt-Modell (kein Reasoning)")


if __name__ == "__main__":
    asyncio.run(main())
