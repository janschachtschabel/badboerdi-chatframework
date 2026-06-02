"""Generic MCP server probe.

Talks to the WLO MCP server directly (no backend involvement) and:
  1. Lists all tools with their full parameter schemas.
  2. Runs a few search_wlo_content variations to learn what resourceType
     values actually work (label vs URI, plural vs singular, etc.).
  3. Prints raw server responses so we can compare against what our
     backend currently does.

Run: python backend/scripts/mcp_probe.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import httpx

MCP_URL = os.getenv("MCP_SERVER_URL", "https://wlo-mcp-server.vercel.app/mcp")

_id = 0
_session: str | None = None


def _next_id() -> int:
    global _id
    _id += 1
    return _id


def _parse(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # SSE fallback
    last = None
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            data = line[5:].strip()
            if data and data != "[DONE]":
                try:
                    last = json.loads(data)
                except json.JSONDecodeError:
                    pass
    return last or {}


async def _rpc(method: str, params: dict | None = None, notif: bool = False) -> dict:
    global _session
    body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        body["params"] = params
    if not notif:
        body["id"] = _next_id()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if _session and method != "initialize":
        headers["Mcp-Session-Id"] = _session

    async with httpx.AsyncClient(timeout=30.0) as cli:
        r = await cli.post(MCP_URL, json=body, headers=headers)

    sid = r.headers.get("mcp-session-id") or r.headers.get("Mcp-Session-Id")
    if sid:
        _session = sid
    if r.status_code not in (200, 202):
        return {"error": f"HTTP {r.status_code}: {r.text[:300]}"}
    if notif or not r.text.strip():
        return {}
    return _parse(r.text)


async def _handshake():
    await _rpc("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "clientInfo": {"name": "mcp-probe", "version": "1.0"},
    })
    await _rpc("notifications/initialized", notif=True)


def _result_text(rpc_result: dict) -> str:
    r = rpc_result.get("result") or {}
    parts = r.get("content") or []
    out = []
    for p in parts:
        if isinstance(p, dict) and p.get("type") == "text":
            out.append(p.get("text", ""))
        elif isinstance(p, str):
            out.append(p)
    return "\n".join(out)


async def main():
    print(f"=== MCP PROBE: {MCP_URL} ===\n")
    await _handshake()

    # 1. List tools with full schemas
    print("── STEP 1: tools/list ──")
    tools = await _rpc("tools/list")
    for t in (tools.get("result") or {}).get("tools", []):
        name = t.get("name", "?")
        desc = t.get("description", "")
        schema = t.get("inputSchema", {})
        print(f"\n● {name}")
        print(f"  desc: {desc[:180]}")
        props = (schema or {}).get("properties") or {}
        required = (schema or {}).get("required") or []
        for pname, pspec in props.items():
            typ = pspec.get("type", "?")
            pdesc = pspec.get("description", "")
            enum = pspec.get("enum")
            req = " (required)" if pname in required else ""
            extra = f" enum={enum}" if enum else ""
            print(f"    - {pname}: {typ}{req}{extra}")
            if pdesc:
                print(f"        desc: {pdesc[:180]}")

    # 2. Probe lookup_wlo_vocabulary for lrt to see exactly what Arbeitsblatt looks like
    print("\n\n── STEP 2: lookup_wlo_vocabulary vocab=lrt (first 2500 chars) ──")
    r = await _rpc("tools/call", {"name": "lookup_wlo_vocabulary", "arguments": {"vocabulary": "lrt"}})
    txt = _result_text(r)
    print(txt[:2500])

    # 3. Find Arbeitsblatt entry in lrt
    print("\n\n── STEP 3: Find Arbeitsblatt-related entries in lrt vocabulary ──")
    lines = txt.split("\n")
    for i, line in enumerate(lines):
        low = line.lower()
        if "arbeitsblatt" in low or "worksheet" in low or "übungsmaterial" in low or "uebungsmaterial" in low:
            ctx = "\n".join(lines[max(0, i-1):i+3])
            print(f"--- @line {i} ---\n{ctx}\n")

    # 4. Search Bruchrechnung WITHOUT filter to get baseline
    print("\n── STEP 4: search_wlo_content(query='Bruchrechnung') -- NO filter ──")
    r = await _rpc("tools/call", {
        "name": "search_wlo_content",
        "arguments": {"query": "Bruchrechnung", "maxItems": 3},
    })
    print("raw:", _result_text(r)[:1800])
    print()

    # 5. Search Bruchrechnung with resourceType as LABEL "Arbeitsblatt"
    print("\n── STEP 5: search_wlo_content with resourceType='Arbeitsblatt' (LABEL) ──")
    r = await _rpc("tools/call", {
        "name": "search_wlo_content",
        "arguments": {"query": "Bruchrechnung", "resourceType": "Arbeitsblatt", "maxItems": 3},
    })
    print("raw:", _result_text(r)[:1800])
    print()

    # 6. Search Bruchrechnung with resourceType as the URI we resolved earlier
    print("\n── STEP 6: search_wlo_content with resourceType URI c8e52242... (Arbeitsblatt) ──")
    r = await _rpc("tools/call", {
        "name": "search_wlo_content",
        "arguments": {
            "query": "Bruchrechnung",
            "resourceType": "http://w3id.org/openeduhub/vocabs/new_lrt_aggregated/c8e52242-361b-4a2a-b95d-25e516b28b45",
            "maxItems": 3,
        },
    })
    print("raw:", _result_text(r)[:1800])
    print()

    # 7. Search with resourceType URI but NO query (just the filter)
    print("\n── STEP 7: search_wlo_content with resourceType URI only (empty query) ──")
    r = await _rpc("tools/call", {
        "name": "search_wlo_content",
        "arguments": {
            "query": "",
            "resourceType": "http://w3id.org/openeduhub/vocabs/new_lrt_aggregated/c8e52242-361b-4a2a-b95d-25e516b28b45",
            "maxItems": 3,
        },
    })
    print("raw:", _result_text(r)[:1200])
    print()

    # 8. Search with both filters
    print("\n── STEP 8: search_wlo_content query+resourceType(URI)+discipline(URI Mathe=380) ──")
    r = await _rpc("tools/call", {
        "name": "search_wlo_content",
        "arguments": {
            "query": "Bruchrechnung",
            "discipline": "http://w3id.org/openeduhub/vocabs/discipline/380",
            "resourceType": "http://w3id.org/openeduhub/vocabs/new_lrt_aggregated/c8e52242-361b-4a2a-b95d-25e516b28b45",
            "maxItems": 3,
        },
    })
    print("raw:", _result_text(r)[:1800])
    print()

    # 9. Same but with plural/lowercase
    print("\n── STEP 9: resourceType='arbeitsblatt' (lowercase) ──")
    r = await _rpc("tools/call", {
        "name": "search_wlo_content",
        "arguments": {"query": "Bruchrechnung", "resourceType": "arbeitsblatt", "maxItems": 3},
    })
    print("raw:", _result_text(r)[:1200])
    print()

    # 10. Video URI test (we know this works from earlier Photosynthese search)
    print("\n── STEP 10: resourceType URI for Video (38774279...) ──")
    r = await _rpc("tools/call", {
        "name": "search_wlo_content",
        "arguments": {
            "query": "Bruchrechnung",
            "resourceType": "http://w3id.org/openeduhub/vocabs/new_lrt_aggregated/38774279-af36-4ec2-8e70-811d5a51a6a1",
            "maxItems": 3,
        },
    })
    print("raw:", _result_text(r)[:1200])
    print()


if __name__ == "__main__":
    asyncio.run(main())
