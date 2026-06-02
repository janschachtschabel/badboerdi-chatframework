"""Smoke-Test gegen den DEPLOYTEN Staging-MCP: neues search_wlo_all + Reranking.
Nutzt den echten Produktions-Pfad call_mcp_tool (MCP-Protokoll). Aufruf (backend/):
    python scripts/test_deployed_mcp.py
"""
from __future__ import annotations
import asyncio, json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()  # MCP_SERVER_URL aus .env (Staging-Vercel)
from app.services.mcp_client import call_mcp_tool  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def first_json_obj(s: str):
    """Erstes balanciertes {...}-Objekt aus einem String (Envelope vor _queryMeta)."""
    i = s.find('{')
    if i < 0:
        return None
    depth = 0; instr = False; esc = False
    for j in range(i, len(s)):
        c = s[j]
        if instr:
            if esc: esc = False
            elif c == '\\': esc = True
            elif c == '"': instr = False
        else:
            if c == '"': instr = True
            elif c == '{': depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return s[i:j + 1]
    return None


def titles(results, n=3):
    return [str((x or {}).get("title", ""))[:42] for x in (results or [])[:n]]


async def main():
    import os
    print("MCP:", os.getenv("MCP_SERVER_URL"))

    # 1) search_wlo_all — Envelope mit getrennten Töpfen
    for q in ("Photosynthese", "Bruchrechnung Klasse 7"):
        t0 = time.perf_counter()
        raw = await call_mcp_tool("search_wlo_all", {"query": q, "outputFormat": "json"})
        dur = round((time.perf_counter() - t0) * 1000)
        print(f"\n=== search_wlo_all({q!r}) — {dur}ms, return-len={len(str(raw))} ===")
        obj = first_json_obj(str(raw))
        if not obj:
            print("  KEIN JSON-Objekt gefunden. Head:", str(raw)[:300]); continue
        try:
            env = json.loads(obj)
            for pot in ("content", "collections", "topicPages"):
                p = env.get(pot, {}) or {}
                print(f"  {pot:11s}: count={p.get('count')} total={p.get('total')} → {titles(p.get('results'))}")
        except Exception as e:
            print("  PARSE-FEHLER:", e, "| head:", obj[:300])

    # 2) Reranking-Check: 'Klimawandel' soll Klimawandel-Sammlungen oben zeigen
    raw2 = await call_mcp_tool("search_wlo_collections", {"query": "Klimawandel", "maxResults": 3, "outputFormat": "json"})
    obj2 = first_json_obj(str(raw2))
    print("\n=== search_wlo_collections('Klimawandel') ===")
    if obj2:
        try:
            d = json.loads(obj2)
            print("  →", titles(d.get("results"), 3))
        except Exception as e:
            print("  PARSE-FEHLER:", e, "| head:", obj2[:200])
    else:
        print("  head:", str(raw2)[:200])
    print("\nfertig.")


if __name__ == "__main__":
    asyncio.run(main())
