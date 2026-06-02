"""Verifiziert den DEPLOYTEN MCP: get_topic_page_content (json, Widget-Query).
Aufruf (backend/):  python scripts/test_topic_deployed.py
"""
from __future__ import annotations
import asyncio, json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()
from app.services.mcp_client import call_mcp_tool, _first_json_object  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Nachhaltigkeit (LTP) aus dem Screenshot
COLL = "a91cc1e7-1f32-4448-83f9-daf51ece5584"


async def main():
    import os
    print("MCP:", os.getenv("MCP_SERVER_URL"))
    t0 = time.perf_counter()
    raw = await call_mcp_tool("get_topic_page_content", {"collectionId": COLL, "outputFormat": "json"})
    dur = round((time.perf_counter() - t0) * 1000)
    print(f"call dauer={dur}ms  return-len={len(str(raw))}")
    frag = _first_json_object(str(raw)) or str(raw)
    try:
        env = json.loads(frag)
    except Exception as e:
        print("PARSE-FEHLER:", e, "| head:", str(raw)[:400])
        return
    print(f"variantTitle={env.get('variantTitle')!r}  swimlaneCount={env.get('swimlaneCount')}  topicPageUrl={env.get('topicPageUrl')}")
    for i, sl in enumerate(env.get("swimlanes", []), 1):
        items = sl.get("items", [])
        print(f"  [{i}] {sl.get('heading','')!r} ({sl.get('type')}) items={len(items)} hasMore={sl.get('hasMore')}")
        for it in items[:3]:
            print(f"       - {str(it.get('title',''))[:48]}  [{it.get('nodeType')}] url={'ja' if it.get('wlo_url') else 'nein'}")


if __name__ == "__main__":
    asyncio.run(main())
