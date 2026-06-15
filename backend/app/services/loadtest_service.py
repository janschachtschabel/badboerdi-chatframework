"""Lasttest-Service — Skalierbarkeits-Selbsttest für das Studio.

Fährt ein Stufen-Profil (steigende Parallelität) mit einem gemischten
Abfrage-Mix gegen die EIGENE Chat-Pipeline und misst pro Stufe
Latenz-Perzentile, Fehlerrate und Durchsatz; parallel werden CPU- und
RAM-Verbrauch des Backend-Prozesses gesampelt. Ergebnis: eine Kurve
"Latenz/Fehler vs. gleichzeitige Nutzer", aus der das Studio die stabile
Parallel-Last ableitet.

Designentscheidungen:
- Requests laufen über ``httpx.ASGITransport`` direkt gegen die App —
  kein Netz-Socket, aber die KOMPLETTE Pipeline inkl. Middleware,
  Rate-Limiter, Klassifikation, MCP-Tools und LLM-Calls. Jeder virtuelle
  Nutzer bekommt eine eigene Doku-IP (198.51.100.x, TEST-NET-2) und
  Session — so verteilt sich das per-IP-Rate-Limit wie bei echten
  Nutzern und verfälscht die Messung nicht.
- ECHTE LLM-/MCP-Calls → echte Kosten und Staging-Last. Das Profil ist
  hart gedeckelt (max. 6 Stufen, 32 parallel, 200 Requests gesamt) und
  der Start liegt bewusst hinter einem Studio-Endpoint mit Warnhinweis.
- Persistenz als JSON unter ``data/loadtests/<run_id>.json`` — nach
  jeder Stufe geschrieben, damit das Studio den Fortschritt pollen kann.

Sessions des Lasttests tragen das Präfix ``loadtest-`` und landen wie
normale Chats in DB/Quality-Logs (realistisch; per Datenschutz-Purge
entfernbar).
"""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import psutil

logger = logging.getLogger(__name__)

LOADTEST_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "loadtests"

# ── Abfrage-Mix ──────────────────────────────────────────────────────
# Jede Kategorie bildet einen anderen Pipeline-Pfad ab (Pattern in
# Klammern). Topics rotieren, damit Tool-/Prompt-Caches nicht jeden
# Request identisch bedienen.
_TOPICS = [
    "Photosynthese", "Bruchrechnung", "Klimawandel", "Elektrizität",
    "Mittelalter", "Prozentrechnung", "Zellbiologie", "Französische Revolution",
]

MIX_TEMPLATES: dict[str, dict[str, Any]] = {
    "wissen": {
        "label": "Wissensfrage (M04 — RAG, keine Tools)",
        "prompt": "Was ist {topic}? Erkläre kurz.",
    },
    "suche": {
        "label": "Material-Suche (M05/M06 — MCP-Suche + Reranker)",
        "prompt": "Suche Arbeitsblätter zu {topic}",
    },
    "orientierung": {
        "label": "Orientierung (M15 — leichtester Pfad)",
        "prompt": "Was kannst du eigentlich?",
    },
    "lernpfad": {
        "label": "Lernpfad (M09 — teuerster Pfad: Suche + Generator)",
        "prompt": "Erstelle einen Lernpfad zu {topic}",
    },
}

# Harte Sicherheits-Caps (unabhängig vom Studio-Input)
MAX_STAGES = 6
MAX_CONCURRENCY = 32
MAX_REQUESTS_PER_STAGE = 60
MAX_TOTAL_REQUESTS = 200
REQUEST_TIMEOUT_S = 120


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_path(run_id: str) -> Path:
    return LOADTEST_DIR / f"{run_id}.json"


def save_run(run: dict[str, Any]) -> None:
    LOADTEST_DIR.mkdir(parents=True, exist_ok=True)
    _run_path(run["id"]).write_text(
        json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def load_run(run_id: str) -> dict[str, Any] | None:
    p = _run_path(run_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_runs() -> list[dict[str, Any]]:
    """Kompakte Liste (ohne Samples/Stage-Details) für die Übersicht."""
    LOADTEST_DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict[str, Any]] = []
    for p in sorted(LOADTEST_DIR.glob("*.json"), reverse=True):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
            out.append({
                "id": r.get("id"),
                "status": r.get("status"),
                "created_at": r.get("created_at"),
                "finished_at": r.get("finished_at"),
                "profile": r.get("profile"),
                "summary": r.get("summary"),
                "error": r.get("error"),
            })
        except Exception:
            continue
    return out


def delete_run(run_id: str) -> bool:
    p = _run_path(run_id)
    if p.exists():
        p.unlink()
        return True
    return False


def any_run_running() -> str | None:
    for r in list_runs():
        if r.get("status") == "running":
            return str(r.get("id"))
    return None


def validate_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Profil normalisieren + hart deckeln. Wirft ValueError bei Unsinn."""
    stages = [int(s) for s in (profile.get("stages") or [1, 2, 4])]
    stages = [max(1, min(MAX_CONCURRENCY, s)) for s in stages][:MAX_STAGES]
    if not stages:
        raise ValueError("Mindestens eine Stufe nötig.")

    rps = int(profile.get("requests_per_stage") or 6)
    rps = max(1, min(MAX_REQUESTS_PER_STAGE, rps))

    total = rps * len(stages)
    if total > MAX_TOTAL_REQUESTS:
        raise ValueError(
            f"Profil zu groß: {total} Requests gesamt (Limit {MAX_TOTAL_REQUESTS}). "
            "Stufenzahl oder Requests/Stufe reduzieren."
        )

    raw_mix = profile.get("mix") or {"wissen": 1, "suche": 1, "orientierung": 1}
    mix: dict[str, int] = {}
    for k, v in raw_mix.items():
        if k not in MIX_TEMPLATES:
            raise ValueError(f"Unbekannte Mix-Kategorie: {k!r}")
        w = max(0, min(10, int(v)))
        if w:
            mix[k] = w
    if not mix:
        raise ValueError("Mix darf nicht leer sein (alle Gewichte 0).")

    p95_threshold = float(profile.get("p95_threshold_s") or 20.0)
    p95_threshold = max(1.0, min(120.0, p95_threshold))

    return {
        "stages": stages,
        "requests_per_stage": rps,
        "mix": mix,
        "p95_threshold_s": p95_threshold,
        "total_requests": total,
    }


def _mix_sequence(mix: dict[str, int], n: int) -> list[str]:
    """Deterministische Round-Robin-Expansion der Gewichte auf n Requests."""
    base: list[str] = []
    for key, weight in mix.items():
        base.extend([key] * weight)
    return [base[i % len(base)] for i in range(n)]


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    vs = sorted(values)
    idx = min(len(vs) - 1, max(0, round((pct / 100.0) * (len(vs) - 1))))
    return vs[idx]


async def _sample_resources(samples: list[dict[str, Any]], stop: asyncio.Event) -> None:
    """CPU/RAM alle 0,5 s sampeln, bis stop gesetzt ist."""
    proc = psutil.Process()
    proc.cpu_percent(None)      # Priming — erster Wert wäre sonst 0/Unsinn
    psutil.cpu_percent(None)
    t0 = time.perf_counter()
    while not stop.is_set():
        try:
            samples.append({
                "t": round(time.perf_counter() - t0, 2),
                "proc_cpu": proc.cpu_percent(None),
                "sys_cpu": psutil.cpu_percent(None),
                "rss_mb": round(proc.memory_info().rss / (1024 * 1024), 1),
            })
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            continue


async def _fire_request(
    client: httpx.AsyncClient, kind: str, topic: str, session_id: str,
) -> dict[str, Any]:
    prompt = MIX_TEMPLATES[kind]["prompt"].format(topic=topic)
    payload = {
        "session_id": session_id,
        "message": prompt,
        "environment": {"page_url": "https://staging.openeduhub.net/"},
    }
    t0 = time.perf_counter()
    try:
        r = await client.post("/api/chat", json=payload, timeout=REQUEST_TIMEOUT_S)
        dt = time.perf_counter() - t0
        ok = r.status_code == 200
        return {"kind": kind, "ok": ok, "status": r.status_code, "latency_s": round(dt, 2)}
    except Exception as e:
        dt = time.perf_counter() - t0
        return {
            "kind": kind, "ok": False, "status": 0,
            "latency_s": round(dt, 2), "error": type(e).__name__,
        }


async def execute_load_test(run_id: str, profile: dict[str, Any]) -> None:
    """Hintergrund-Runner — schreibt Fortschritt nach jeder Stufe."""
    run: dict[str, Any] = {
        "id": run_id,
        "status": "running",
        "created_at": _now_iso(),
        "finished_at": None,
        "profile": profile,
        "stages": [],
        "resource_samples": [],
        "summary": None,
        "error": None,
    }
    save_run(run)

    # Lazy-Import vermeidet Zirkularimport (main → router → service).
    from app.main import app as _app

    samples: list[dict[str, Any]] = run["resource_samples"]
    stop = asyncio.Event()
    sampler = asyncio.create_task(_sample_resources(samples, stop))

    try:
        for stage_idx, concurrency in enumerate(profile["stages"]):
            n = profile["requests_per_stage"]
            kinds = _mix_sequence(profile["mix"], n)
            sem = asyncio.Semaphore(concurrency)

            async def _worker(i: int, kind: str) -> dict[str, Any]:
                # Eigene Doku-IP (TEST-NET-2) + Session je virtuellem Nutzer:
                # per-IP-Rate-Limit verteilt sich wie bei echten Besuchern.
                ip = f"198.51.100.{(i % 50) + 1}"
                transport = httpx.ASGITransport(app=_app, client=(ip, 50000 + i))
                topic = _TOPICS[(stage_idx * 7 + i) % len(_TOPICS)]
                sid = f"loadtest-{run_id[:8]}-s{stage_idx}-{i}"
                async with sem:
                    async with httpx.AsyncClient(
                        transport=transport, base_url="http://loadtest.local",
                    ) as client:
                        return await _fire_request(client, kind, topic, sid)

            stage_t0 = time.perf_counter()
            results = await asyncio.gather(
                *[_worker(i, k) for i, k in enumerate(kinds)]
            )
            stage_dt = time.perf_counter() - stage_t0

            lat_ok = [r["latency_s"] for r in results if r["ok"]]
            errors = [r for r in results if not r["ok"]]
            by_kind: dict[str, dict[str, Any]] = {}
            for k in set(kinds):
                ks = [r["latency_s"] for r in results if r["kind"] == k and r["ok"]]
                by_kind[k] = {
                    "n": kinds.count(k),
                    "ok": len(ks),
                    "p50_s": round(_percentile(ks, 50), 2),
                    "p95_s": round(_percentile(ks, 95), 2),
                }

            run["stages"].append({
                "concurrency": concurrency,
                "requests": n,
                "ok": len(lat_ok),
                "errors": len(errors),
                "error_kinds": sorted({r.get("error") or f"HTTP {r['status']}" for r in errors}),
                "p50_s": round(_percentile(lat_ok, 50), 2),
                "p95_s": round(_percentile(lat_ok, 95), 2),
                "max_s": round(max(lat_ok), 2) if lat_ok else 0.0,
                "mean_s": round(statistics.fmean(lat_ok), 2) if lat_ok else 0.0,
                "duration_s": round(stage_dt, 1),
                "rps": round(n / stage_dt, 2) if stage_dt > 0 else 0.0,
                "by_kind": by_kind,
            })
            save_run(run)

        # ── Fazit: höchste Stufe, die Fehler-frei UND unter p95-Schwelle blieb
        threshold = profile["p95_threshold_s"]
        stable = None
        for st in run["stages"]:
            healthy = st["errors"] == 0 and st["p95_s"] <= threshold
            if healthy:
                stable = st["concurrency"]
            else:
                break
        peak_rss = max((s["rss_mb"] for s in samples), default=0.0)
        peak_cpu = max((s["proc_cpu"] for s in samples), default=0.0)
        run["summary"] = {
            "stable_concurrency": stable,
            "p95_threshold_s": threshold,
            "peak_rss_mb": peak_rss,
            "peak_proc_cpu_pct": peak_cpu,
            "total_requests": sum(st["requests"] for st in run["stages"]),
            "total_errors": sum(st["errors"] for st in run["stages"]),
        }
        run["status"] = "completed"
    except Exception as e:
        logger.exception("loadtest %s failed", run_id)
        run["status"] = "failed"
        run["error"] = f"{type(e).__name__}: {e}"
    finally:
        stop.set()
        try:
            await sampler
        except Exception:
            pass
        run["finished_at"] = _now_iso()
        save_run(run)
