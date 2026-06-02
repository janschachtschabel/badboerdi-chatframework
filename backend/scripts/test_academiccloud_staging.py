"""AcademicCloud-Anbindung über die B-API STAGING testen.

Prüft die OEH-B-API → AcademicCloud-Strecke (GWDG-Modelle) auf
``b-api.staging.openeduhub.net`` — getrennt vom OpenAI-Passthrough
(den deckt ``test_b_api_endpoints.py`` ab).

Was getestet wird
-----------------
  1. GET  /academiccloud/models       — Katalog-Discovery; findet die
                                         EXAKTEN Modellnamen auf Staging
                                         (gemma / gpt-oss / mistral / …).
  2. POST /academiccloud/chat/completions
                                       — pro Modell ein Single-Call,
                                         STRIKT SERIELL, mit
                                         ``_shape_max_tokens`` für die
                                         Reasoning-Modelle (Qwen/gpt-oss).
  3. POST /academiccloud/embeddings    — e5-mistral-7b-instruct: NUR
                                         Reichweite + Dimension prüfen.
                                         NICHT für unsere RAG-DB benutzen.
  4. OpenAI /v1/embeddings (nativ)     — text-embedding-3-small: der Pfad,
                                         den die App real für die RAG-DB
                                         nutzt (1536 dim, DB bleibt wie sie
                                         ist).
  5. Parallel-Probe (2 gleichzeitig)   — DOKUMENTIERT, dass AcademicCloud
                                         parallele Calls NICHT zulässt
                                         (spurious 401 / Fehler unter Last).

WICHTIG
-------
* AcademicCloud erlaubt KEINE parallelen Calls → alle Chat-Tests laufen
  strikt seriell (CONCURRENCY = 1). Die Parallel-Probe in Schritt 5 ist
  bewusst isoliert und beeinflusst die Pass/Fail-Wertung der Modelle nicht.
* Keys: liest ``B_API_KEY_STAGING`` + ``OPENAI_API_KEY`` aus der Umgebung.
  Die App selbst nutzt weiterhin zentral ``B_API_KEY`` — hier bewusst
  NICHT angefasst (kein Hardcode von Secrets).

Aufruf (PowerShell, aus ``backend/``)::

    python scripts/test_academiccloud_staging.py

Optional: eigene Modell-Auswahl (überschreibt die Auto-Discovery)::

    $env:AC_TEST_MODELS = "gemma-3-27b-it,openai-gpt-oss-120b,mistral-large-3-675b-instruct-2512"
    python scripts/test_academiccloud_staging.py
"""
from __future__ import annotations

import asyncio
import os
import random
import string
import sys
import time
from pathlib import Path

import httpx
from openai import AsyncOpenAI

# Repo root → import path, um llm_provider's Token-Shaping wiederzuverwenden.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.llm_provider import _shape_max_tokens, model_profile  # noqa: E402

# Windows-Konsole UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ── Konfiguration ────────────────────────────────────────────────────
B_API_BASE = "https://b-api.staging.openeduhub.net/api/v1/llm"
AC_BASE = f"{B_API_BASE}/academiccloud"
KEY_VAR = "B_API_KEY_STAGING"

# Vom User empfohlene Modelle (mind. 2 testen — manche sind zeitweise
# nicht erreichbar). Wir matchen per Familie gegen den Live-Katalog, damit
# der EXAKTE Staging-Name benutzt wird, und halten je einen bekannten
# Fallback bereit (falls /models eine Familie nicht listet).
FAMILIES = [
    # (Label,          Substring-Match im Katalog,  Fallback-Name)
    ("gemma",          "gemma",                      "gemma-3-27b-it"),
    ("gpt-oss-120b",   "gpt-oss-120b",               "openai-gpt-oss-120b"),
    ("mistral-large",  "mistral-large",              "mistral-large-3-675b-instruct-2512"),
    # Referenz: aktueller AcademicCloud-Default in llm_provider.py
    ("qwen3.5-122b",   "qwen3.5-122b",               "qwen3.5-122b-a10b"),
]

AC_EMBED_MODEL = "e5-mistral-7b-instruct"   # NUR-Test, NICHT für die DB
OPENAI_EMBED_MODEL = "text-embedding-3-small"  # realer DB-Pfad (1536 dim)

BASE_MAX_TOKENS = 200      # was die App typisch für eine kurze Antwort fragt
TIMEOUT_S = 90
MAX_RETRIES = 2
RETRY_BACKOFF_S = 3.0


def _ok(m: str) -> None:
    print(f"  [OK]   {m}", flush=True)


def _fail(m: str) -> None:
    print(f"  [FAIL] {m}", flush=True)


def _skip(m: str) -> None:
    print(f"  [SKIP] {m}", flush=True)


def _uniq() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


def _ac_client(key: str) -> AsyncOpenAI:
    """OpenAI-SDK-Client für AcademicCloud — exakt wie llm_provider.get_client()
    für ``b-api-academiccloud`` (base_url + X-API-KEY-Header)."""
    return AsyncOpenAI(
        api_key=key or "unused",
        base_url=AC_BASE,
        default_headers={"X-API-KEY": key} if key else None,
        timeout=TIMEOUT_S,
        max_retries=0,
    )


# ── 1. Katalog-Discovery ──────────────────────────────────────────────
async def discover_models(key: str) -> list[str]:
    """GET /academiccloud/models → sortierte Namensliste.

    Der B-API ``/models``-Endpunkt liefert auf Prod eine bare-list, auf
    Staging das OpenAI-Envelope — wir parsen beide robust.
    """
    print("\n--- 1) Katalog-Discovery (/academiccloud/models) ---")
    try:
        async with httpx.AsyncClient(timeout=30) as cli:
            r = await cli.get(f"{AC_BASE}/models", headers={"X-API-KEY": key})
        if r.status_code != 200:
            _fail(f"/models — HTTP {r.status_code}: {r.text[:160]}")
            return []
        data = r.json()
        items = data if isinstance(data, list) else data.get("data", [])
        names = sorted((m["id"] if isinstance(m, dict) else str(m)) for m in items)
        envelope = "bare-list" if isinstance(data, list) else "openai-envelope"
        _ok(f"/models — {len(names)} Modelle ({envelope})")
        # Interessante Familien hervorheben (genau das, was der User sehen will)
        interesting = ("gemma", "gpt-oss", "mistral", "qwen", "glm", "llama",
                       "e5-", "deepseek")
        hits = [n for n in names if any(t in n.lower() for t in interesting)]
        print("       Relevante Modelle im Katalog:")
        for n in hits:
            print(f"         - {n}")
        return names
    except Exception as e:
        _fail(f"/models — {type(e).__name__}: {str(e)[:160]}")
        return []


def pick_models(names: list[str]) -> list[tuple[str, str, str]]:
    """Wähle je Familie den ersten passenden Katalog-Namen, sonst Fallback.

    Returns Liste von (label, model_name, source) mit source ∈ {catalog, fallback}.
    """
    override = (os.getenv("AC_TEST_MODELS") or "").strip()
    if override:
        out = [(m.strip(), m.strip(), "env-override") for m in override.split(",") if m.strip()]
        return out
    lower = {n.lower(): n for n in names}
    chosen: list[tuple[str, str, str]] = []
    for label, sub, fallback in FAMILIES:
        match = next((orig for low, orig in lower.items() if sub in low), None)
        if match:
            chosen.append((label, match, "catalog"))
        else:
            chosen.append((label, fallback, "fallback"))
    return chosen


# ── 2. Chat-Completions (seriell) ─────────────────────────────────────
async def test_chat(client: AsyncOpenAI, label: str, model: str) -> dict:
    """Ein Single-Call mit Retry für transiente B-API-Fehler (401/Protocol)."""
    shaped = _shape_max_tokens(model, BASE_MAX_TOKENS)
    prompt = f"Antworte in genau einem kurzen Satz: Was ist Photosynthese? (ID: {_uniq()})"
    last_err = ""
    for attempt in range(MAX_RETRIES + 1):
        t0 = time.perf_counter()
        try:
            r = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "Du bist ein knapper, freundlicher Lerncoach."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=shaped,
                temperature=0.4,
            )
            dur = round((time.perf_counter() - t0) * 1000)
            choice = r.choices[0]
            msg = choice.message
            content = (msg.content or "").strip()
            reasoning = getattr(msg, "reasoning_content", None) or ""
            usage = r.usage
            ct = usage.completion_tokens if usage else None
            pt = usage.prompt_tokens if usage else None
            ok = bool(content)
            res = {
                "label": label, "model": model, "ok": ok, "status": 200,
                "latency_ms": dur, "finish_reason": choice.finish_reason,
                "max_tokens_sent": shaped, "prompt_tokens": pt, "completion_tokens": ct,
                "reasoning_chars": len(reasoning), "content_chars": len(content),
                "content_preview": content[:160],
            }
            if ok:
                _ok(f"{label:14s} [{model}]  {dur:>5}ms  ct={ct}  out={len(content)}ch"
                    f"  rsn={len(reasoning)}ch")
                print(f"           → {content[:140]!r}")
            else:
                _fail(f"{label:14s} [{model}]  LEERE Antwort (finish={choice.finish_reason}, "
                      f"ct={ct}, reasoning={len(reasoning)}ch — Budget von Reasoning gefressen?)")
            return res
        except Exception as e:
            dur = round((time.perf_counter() - t0) * 1000)
            last_err = f"{type(e).__name__}: {str(e)[:160]}"
            # Transiente 401/Protocol-Fehler → nachfassen
            if attempt < MAX_RETRIES and ("401" in last_err or "RemoteProtocol" in last_err
                                          or "Timeout" in last_err or "Connect" in last_err):
                _skip(f"{label:14s} [{model}]  transient ({last_err}) → retry {attempt + 1}")
                await asyncio.sleep(RETRY_BACKOFF_S * (attempt + 1))
                continue
            _fail(f"{label:14s} [{model}]  {last_err}")
            return {"label": label, "model": model, "ok": False, "status": 0,
                    "latency_ms": dur, "error": last_err}
    return {"label": label, "model": model, "ok": False, "status": 0,
            "latency_ms": 0, "error": last_err or "exhausted retries"}


# ── 3+4. Embeddings ───────────────────────────────────────────────────
async def test_embed_academiccloud(key: str) -> dict:
    """e5-mistral-7b-instruct auf AcademicCloud — NUR Reichweite + Dimension.
    NICHT für unsere RAG-DB benutzen (die bleibt 1536-dim / OpenAI)."""
    print("\n--- 3) Embeddings AcademicCloud (e5-mistral, NUR-Test) ---")
    body = {"model": AC_EMBED_MODEL, "input": ["Photosynthese ist ein biologischer Prozess."]}
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=60) as cli:
            r = await cli.post(f"{AC_BASE}/embeddings",
                               headers={"X-API-KEY": key, "Content-Type": "application/json"},
                               json=body)
        dur = round((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            _fail(f"{AC_EMBED_MODEL} — HTTP {r.status_code}: {r.text[:160]}")
            return {"ok": False, "status": r.status_code}
        d = r.json()
        emb = (d.get("data") or [{}])[0].get("embedding") or []
        dim = len(emb)
        _ok(f"{AC_EMBED_MODEL} — {dur}ms, Dimension {dim} "
            f"(erwartet 4096 — NICHT für die DB, die bleibt 1536/OpenAI)")
        return {"ok": dim > 0, "status": 200, "dim": dim, "latency_ms": dur}
    except Exception as e:
        _fail(f"{AC_EMBED_MODEL} — {type(e).__name__}: {str(e)[:160]}")
        return {"ok": False, "status": 0, "error": str(e)[:160]}


async def test_embed_openai() -> dict:
    """text-embedding-3-small via nativem OpenAI — der reale RAG-DB-Pfad.
    Beweist, dass die DB-Strecke unangetastet weiterläuft, wenn der Chat
    auf AcademicCloud zeigt."""
    print("\n--- 4) Embeddings OpenAI (text-embedding-3-small, realer DB-Pfad) ---")
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        _skip("OPENAI_API_KEY nicht gesetzt — DB-Embedding-Pfad nicht prüfbar")
        return {"ok": None}
    base = (os.getenv("OPENAI_BASE_URL") or "").strip().rstrip("/") or "https://api.openai.com/v1"
    c = AsyncOpenAI(api_key=key, base_url=base, timeout=60, max_retries=0)
    t0 = time.perf_counter()
    try:
        r = await c.embeddings.create(model=OPENAI_EMBED_MODEL,
                                      input="Photosynthese ist ein biologischer Prozess.")
        dur = round((time.perf_counter() - t0) * 1000)
        dim = len(r.data[0].embedding)
        _ok(f"{OPENAI_EMBED_MODEL} — {dur}ms, Dimension {dim} (erwartet 1536, DB-kompatibel)")
        return {"ok": dim == 1536, "status": 200, "dim": dim, "latency_ms": dur}
    except Exception as e:
        _fail(f"{OPENAI_EMBED_MODEL} — {type(e).__name__}: {str(e)[:160]}")
        return {"ok": False, "status": 0, "error": str(e)[:160]}
    finally:
        await c.close()


# ── 5. Parallel-Probe (dokumentiert das No-Parallel-Verhalten) ────────
async def probe_parallel(key: str, model: str) -> None:
    print("\n--- 5) Parallel-Probe (2 gleichzeitig — AcademicCloud erlaubt das NICHT) ---")

    async def _one(i: int) -> tuple[int, int, str]:
        body = {
            "model": model,
            "messages": [{"role": "user", "content": f"Sag in 3 Worten Hallo. (ID: {_uniq()})"}],
            "max_tokens": _shape_max_tokens(model, 60),
            "temperature": 0.3,
        }
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as cli:
                r = await cli.post(f"{AC_BASE}/chat/completions",
                                   headers={"X-API-KEY": key, "Content-Type": "application/json"},
                                   json=body)
            return i, r.status_code, "" if r.status_code == 200 else r.text[:100]
        except Exception as e:
            return i, 0, f"{type(e).__name__}: {str(e)[:80]}"

    t0 = time.perf_counter()
    results = await asyncio.gather(_one(0), _one(1))
    dur = round((time.perf_counter() - t0) * 1000)
    statuses = [s for _, s, _ in results]
    ok = sum(1 for s in statuses if s == 200)
    print(f"       2 parallele Calls auf [{model}] — {dur}ms gesamt, Status={statuses}")
    if ok == 2:
        print("       → Beide OK. (Staging toleriert hier 2 parallele Calls; trotzdem "
              "bleibt die App seriell, da AcademicCloud das offiziell nicht zusichert.)")
    else:
        for i, s, body in results:
            if s != 200:
                print(f"       → Call {i}: HTTP {s}  {body!r}")
        print("       → BESTÄTIGT: parallele Calls scheitern → App muss seriell bleiben.")


# ── Main ──────────────────────────────────────────────────────────────
async def main() -> None:
    key = (os.getenv(KEY_VAR) or "").strip()
    print("=" * 78)
    print("  AcademicCloud × B-API STAGING — Integrationstest")
    print(f"  base: {AC_BASE}")
    if not key:
        print(f"\nERROR: {KEY_VAR} nicht gesetzt. In PowerShell z.B.:")
        print(f"  $env:{KEY_VAR} = [Environment]::GetEnvironmentVariable('{KEY_VAR}','User')")
        sys.exit(1)
    print(f"  key:  {key[:6]}*** (len {len(key)})")
    print("=" * 78)

    names = await discover_models(key)
    chosen = pick_models(names)
    print("\n--- 2) Chat-Completions (STRIKT SERIELL, CONCURRENCY=1) ---")
    print("       Getestete Modelle:")
    for label, model, src in chosen:
        prof = model_profile(model)
        ptxt = f"  profile={prof}" if prof else ""
        print(f"         - {label:14s} → {model}  [{src}]{ptxt}")
    print()

    client = _ac_client(key)
    chat_results: list[dict] = []
    for label, model, _src in chosen:
        res = await test_chat(client, label, model)
        chat_results.append(res)
    await client.close()

    ac_embed = await test_embed_academiccloud(key)
    oa_embed = await test_embed_openai()

    # Parallel-Probe auf einem Modell, das oben erfolgreich war (sonst skip).
    ok_model = next((r["model"] for r in chat_results if r.get("ok")), None)
    if ok_model:
        await probe_parallel(key, ok_model)
    else:
        print("\n--- 5) Parallel-Probe übersprungen (kein erfolgreiches Chat-Modell) ---")

    # ── Zusammenfassung ──
    print("\n" + "=" * 78)
    print("  ZUSAMMENFASSUNG")
    print("=" * 78)
    print(f"\n  Chat-Modelle (seriell) — Endpoint: {AC_BASE}")
    hdr = f"  {'Label':14s} | {'Modell':42s} | {'Status':6s} | {'ms':>6s} | {'out':>5s} | {'ct':>5s}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    chat_ok = 0
    for r in chat_results:
        st = "OK" if r.get("ok") else (f"HTTP{r['status']}" if r.get("status") else "ERR")
        if r.get("ok"):
            chat_ok += 1
        print(f"  {r['label']:14s} | {r['model']:42s} | {st:6s} | "
              f"{r.get('latency_ms', 0):>6} | {r.get('content_chars', 0):>5} | "
              f"{r.get('completion_tokens') or 0:>5}")
    print(f"\n  Chat: {chat_ok}/{len(chat_results)} Modelle OK")
    print(f"  Embedding AcademicCloud (e5-mistral): "
          f"{'OK dim=' + str(ac_embed.get('dim')) if ac_embed.get('ok') else 'FEHLER'}  "
          f"(NUR-Test, nicht für DB)")
    oa = oa_embed.get("ok")
    if oa:
        oa_txt = f"OK dim={oa_embed.get('dim')}"
    elif oa is None:
        oa_txt = "SKIP (kein OPENAI_API_KEY)"
    else:
        oa_txt = "FEHLER"
    print(f"  Embedding OpenAI (DB-Pfad, 1536):     {oa_txt}")
    print()
    print("  Hinweise:")
    print("   - AcademicCloud-Chat läuft seriell (keine parallelen Calls).")
    print("   - Die RAG-DB bleibt unangetastet: Embeddings laufen weiter über OpenAI")
    print("     (text-embedding-3-small, 1536 dim). e5-mistral wurde NUR auf Reichweite")
    print("     geprüft, nicht in die DB geschrieben.")
    print("   - Provider-Umschaltung der App (zum echten Betrieb) via .env:")
    print("       LLM_PROVIDER=b-api-academiccloud")
    print("       B_API_BASE_URL=https://b-api.staging.openeduhub.net/api/v1/llm")
    print("       LLM_CHAT_MODEL=<einer der OK-Modellnamen oben>")
    print("       (B_API_KEY zentral = Staging-Key; OPENAI_API_KEY bleibt für Embeddings.)")


if __name__ == "__main__":
    asyncio.run(main())
